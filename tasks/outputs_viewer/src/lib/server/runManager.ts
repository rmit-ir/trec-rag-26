import "server-only";
import { spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import { createWriteStream, mkdirSync, type WriteStream } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { REPO_ROOT, getEnv } from "./env";
import type { RunRecord, RunStatus } from "@/lib/types";

/**
 * Tracks `aus_agent` child processes spawned from the viewer.
 *
 * Design notes:
 * - Spawned with an argv ARRAY and no shell, so arbitrary query text can never
 *   be interpreted as shell syntax.
 * - `detached: true` puts each child in its OWN process group. `uv run` execs a
 *   python child, so signalling only the direct child would leave python alive;
 *   killing the whole group (`process.kill(-pid, ...)`) reaps the entire tree.
 * - The child inherits `process.env` verbatim. AWS credentials are resolved by
 *   boto3's default chain (repo `.env` locally, EC2 instance profile in prod);
 *   nothing here injects, forwards, validates, or strips AWS_* variables.
 * - State lives on `globalThis` so the Next dev server's module HMR does not
 *   silently fork a second, empty registry and lose track of live children.
 */

/** Hard wall-clock cap: a run still alive after this is killed. */
const DEFAULT_TIMEOUT_MS = 10 * 60 * 1000;
/** Grace period between SIGTERM and the SIGKILL follow-up. */
const KILL_GRACE_MS = 10_000;
/** How many runs may be in flight at once. */
const DEFAULT_MAX_CONCURRENT = 2;
/** Bounded stdout/stderr tail retained per run, in lines. */
const LOG_TAIL_LINES = 40;

function timeoutMs(): number {
  const raw = getEnv("AUS_AGENT_RUN_TIMEOUT_MS");
  const n = raw ? Number(raw) : NaN;
  return Number.isFinite(n) && n > 0 ? n : DEFAULT_TIMEOUT_MS;
}

function maxConcurrent(): number {
  const raw = getEnv("AUS_AGENT_MAX_CONCURRENT_RUNS");
  const n = raw ? Number(raw) : NaN;
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : DEFAULT_MAX_CONCURRENT;
}

interface LiveRun {
  record: RunRecord;
  child: ChildProcess;
  timer: NodeJS.Timeout;
  killTimer?: NodeJS.Timeout;
  logStream?: WriteStream;
}

/** Directory under the system tmp dir holding one full log file per run. */
function logDir(): string {
  return path.join(tmpdir(), "aus_agent_runs");
}

/**
 * Open the per-run log file. Best-effort: a failure to open (odd tmp perms,
 * disk full) must not block the run itself, so it degrades to tail-only.
 */
function openLogFile(runId: string): { stream: WriteStream; logPath: string } | null {
  try {
    const dir = logDir();
    mkdirSync(dir, { recursive: true });
    const logPath = path.join(dir, `${runId}.log`);
    return { stream: createWriteStream(logPath, { flags: "a" }), logPath };
  } catch {
    return null;
  }
}

interface Registry {
  live: Map<string, LiveRun>;
  /** Finished runs, newest last; trimmed to HISTORY_LIMIT. */
  history: RunRecord[];
  exitHookInstalled: boolean;
}

const HISTORY_LIMIT = 50;

const GLOBAL_KEY = "__ausAgentRunRegistry__";
type GlobalWithRegistry = typeof globalThis & { [GLOBAL_KEY]?: Registry };

function registry(): Registry {
  const g = globalThis as GlobalWithRegistry;
  if (!g[GLOBAL_KEY]) {
    g[GLOBAL_KEY] = { live: new Map(), history: [], exitHookInstalled: false };
  }
  return g[GLOBAL_KEY];
}

/** Signal a child's whole process group; falls back to the bare pid. */
function killGroup(child: ChildProcess, signal: NodeJS.Signals): void {
  if (child.pid == null || child.exitCode !== null || child.signalCode !== null) return;
  try {
    process.kill(-child.pid, signal);
  } catch {
    try {
      child.kill(signal);
    } catch {
      /* already gone */
    }
  }
}

/**
 * Best-effort teardown when the server itself goes away. Detached children
 * outlive their parent by design, so without this a dev-server restart would
 * orphan a run with no timer left to bound it.
 */
function installExitHook(reg: Registry): void {
  if (reg.exitHookInstalled) return;
  reg.exitHookInstalled = true;
  const teardown = () => {
    for (const run of reg.live.values()) killGroup(run.child, "SIGKILL");
  };
  process.on("exit", teardown);
  for (const sig of ["SIGINT", "SIGTERM"] as const) {
    process.on(sig, () => {
      teardown();
      process.exit(130);
    });
  }
}

function appendLog(record: RunRecord, chunk: string): void {
  const lines = chunk.split(/\r?\n/).filter((l) => l.length > 0);
  if (lines.length === 0) return;
  record.logTail.push(...lines);
  if (record.logTail.length > LOG_TAIL_LINES) {
    record.logTail.splice(0, record.logTail.length - LOG_TAIL_LINES);
  }
}

function finish(reg: Registry, id: string, status: RunStatus, patch: Partial<RunRecord>): void {
  const run = reg.live.get(id);
  if (!run) return;
  clearTimeout(run.timer);
  if (run.killTimer) clearTimeout(run.killTimer);
  reg.live.delete(id);
  const record: RunRecord = {
    ...run.record,
    ...patch,
    status,
    endedAt: Date.now(),
  };
  if (run.logStream) {
    run.logStream.end(
      `# run ${record.runId} finished ${new Date().toISOString()} status=${status}` +
        `${record.error ? ` error=${record.error}` : ""}\n`,
    );
  }
  const summary =
    `[aus_agent ${record.runId}] finished status=${status}` +
    `${record.error ? ` error=${record.error}` : ""}` +
    `${record.logPath ? ` log=${record.logPath}` : ""}`;
  (status === "completed" ? console.log : console.error)(summary);
  reg.history.push(record);
  if (reg.history.length > HISTORY_LIMIT) reg.history.splice(0, reg.history.length - HISTORY_LIMIT);
}

export interface StartRunResult {
  ok: boolean;
  record?: RunRecord;
  error?: string;
  /** HTTP status the caller should use when `ok` is false. */
  status?: number;
}

/**
 * Spawn an `aus_agent` run for `query` and return immediately.
 *
 * The returned record is a snapshot; poll `listRuns()` for progress. The run's
 * artifact appears in data/outputs/aus_agent once the harness writes it.
 */
export function startRun(query: string): StartRunResult {
  const trimmed = query.trim();
  if (!trimmed) return { ok: false, error: "query required", status: 400 };
  if (trimmed.length > 4000) {
    return { ok: false, error: "query too long (max 4000 chars)", status: 400 };
  }

  const reg = registry();
  installExitHook(reg);

  const limit = maxConcurrent();
  if (reg.live.size >= limit) {
    return {
      ok: false,
      error: `too many runs in flight (${reg.live.size}/${limit}); wait for one to finish`,
      status: 429,
    };
  }

  const id = randomUUID();
  const runId = `viewer-${new Date().toISOString().replace(/[-:.]/g, "").slice(0, 15)}`;
  // argv array + no shell: `trimmed` is passed as one opaque execve argument.
  const argv = [
    "run",
    "--group",
    "aus-agent",
    "python",
    "src/systems/aus_agent/run.py",
    "--query",
    trimmed,
    "--run-id",
    runId,
  ];
  const bin = getEnv("UV_BIN", "uv") as string;

  let child: ChildProcess;
  try {
    child = spawn(bin, argv, {
      cwd: REPO_ROOT,
      // Inherit verbatim — boto3 resolves creds on its own. PYTHONUNBUFFERED
      // defeats python's block-buffering on piped stdout so logs stream live.
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      stdio: ["ignore", "pipe", "pipe"],
      detached: true, // own process group, so we can kill the whole tree
    });
  } catch (e) {
    return { ok: false, error: `spawn failed: ${String(e)}`, status: 500 };
  }

  const logFile = openLogFile(runId);
  logFile?.stream.write(
    `# aus_agent run ${runId} started ${new Date().toISOString()}\n# query: ${trimmed}\n`,
  );
  console.log(
    `[aus_agent ${runId}] started pid=${child.pid}` +
      `${logFile ? ` log=${logFile.logPath}` : ""}`,
  );

  const record: RunRecord = {
    id,
    runId,
    system: "aus_agent",
    query: trimmed,
    status: "running",
    startedAt: Date.now(),
    pid: child.pid ?? null,
    logTail: [],
    logPath: logFile?.logPath,
  };

  const timer = setTimeout(() => {
    const run = reg.live.get(id);
    if (!run) return;
    run.record.timedOut = true;
    killGroup(run.child, "SIGTERM");
    // If SIGTERM is ignored/blocked, escalate. The 'exit' handler resolves the
    // record either way; this only guarantees the process cannot survive.
    run.killTimer = setTimeout(() => killGroup(run.child, "SIGKILL"), KILL_GRACE_MS);
  }, timeoutMs());

  const live: LiveRun = { record, child, timer, logStream: logFile?.stream };
  reg.live.set(id, live);

  const onChunk = (c: string) => {
    appendLog(record, c);
    logFile?.stream.write(c);
    // Echo to the Next.js server console so failures are visible in `pnpm start`.
    for (const line of c.split(/\r?\n/)) {
      if (line) console.log(`[aus_agent ${runId}]`, line);
    }
  };
  child.stdout?.setEncoding("utf8");
  child.stdout?.on("data", onChunk);
  child.stderr?.setEncoding("utf8");
  child.stderr?.on("data", onChunk);

  child.on("error", (err) => {
    finish(reg, id, "failed", { error: String(err) });
  });

  child.on("exit", (code, signal) => {
    const timedOut = live.record.timedOut === true;
    const status: RunStatus = timedOut
      ? "timeout"
      : code === 0
        ? "completed"
        : "failed";
    finish(reg, id, status, {
      exitCode: code,
      signal: signal ?? null,
      error: timedOut
        ? `killed after ${Math.round(timeoutMs() / 1000)}s timeout`
        : code === 0
          ? undefined
          : `exited with code ${code}${signal ? ` (${signal})` : ""}`,
    });
  });

  return { ok: true, record: { ...record } };
}

/** Snapshot of in-flight runs plus recent history (newest first). */
export function listRuns(): { running: RunRecord[]; recent: RunRecord[] } {
  const reg = registry();
  const running = [...reg.live.values()].map((r) => ({ ...r.record }));
  const recent = [...reg.history].reverse();
  return { running, recent };
}
