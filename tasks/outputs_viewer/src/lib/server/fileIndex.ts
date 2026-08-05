import "server-only";
import fs from "node:fs";
import path from "node:path";
import { OUTPUTS_DIR } from "./env";
import type { OutputsIndex, SessionHeader } from "@/lib/types";

/**
 * In-memory index over data/outputs/<system>/<ts>.<slug>.output.json.
 *
 * Cheap per-request re-scan: readdir + stat everything (a few hundred entries),
 * then re-read ONLY files whose (mtimeMs, size) signature changed since the
 * cached header was extracted. Full file contents are never retained — just a
 * small header per session.
 */

interface CachedHeader {
  sig: string; // mtimeMs:size of the file the header came from
  narrativeId?: string;
  narrativeSnippet?: string;
  runId?: string;
  status?: string;
  model?: string;
  hasTrace?: boolean;
}

const outputHeaderCache = new Map<string, CachedHeader>(); // key: abs path of output.json

function sigOf(st: fs.Stats): string {
  return `${st.mtimeMs}:${st.size}`;
}

function snippet(text: string | undefined, words = 14): string | undefined {
  if (!text) return undefined;
  const parts = text.trim().split(/\s+/);
  const s = parts.slice(0, words).join(" ");
  return parts.length > words ? `${s}…` : s;
}

function readOutputHeader(file: string, st: fs.Stats): CachedHeader {
  const sig = sigOf(st);
  const hit = outputHeaderCache.get(file);
  if (hit && hit.sig === sig) return hit;
  let h: CachedHeader = { sig };
  try {
    const data = JSON.parse(fs.readFileSync(file, "utf8"));
    const meta = data?.metadata ?? {};
    h = {
      sig,
      narrativeId: meta.narrative_id,
      narrativeSnippet: snippet(meta.narrative),
      runId: meta.run_id,
      hasTrace: data?.trace != null && typeof data.trace === "object",
      status:
        typeof data?.trace?.status === "string" ? data.trace.status : undefined,
      model:
        typeof data?.trace?.metadata?.model === "string"
          ? data.trace.metadata.model
          : undefined,
    };
  } catch {
    // unparsable file: keep an empty header, still listed
  }
  outputHeaderCache.set(file, h);
  return h;
}

const OUTPUT_RE = /^(?<ts>[^.]+)\.(?<slug>.+)\.output\.json$/;

/**
 * Tie-break for sessions sharing a timestamp: topic order, ascending.
 *
 * Agent runs each get their own microsecond stamp, so this never fires for
 * them. Imported baselines do collide by construction — the organizers publish
 * one JSONL per run with no per-topic time, so every session of a baseline
 * carries that file's single synthetic stamp. Without this they would list in
 * readdir order; with it they list rag2026-0 … rag2026-118.
 */
function compareNarrativeId(a: SessionHeader, b: SessionHeader): number {
  const n = (h: SessionHeader) => Number(/(\d+)\s*$/.exec(h.narrativeId ?? "")?.[1]);
  const [x, y] = [n(a), n(b)];
  if (Number.isFinite(x) && Number.isFinite(y) && x !== y) return x - y;
  return a.sessionId.localeCompare(b.sessionId);
}

export function scanOutputs(): OutputsIndex {
  const sessions: SessionHeader[] = [];
  const systems: { system: string; sessionCount: number }[] = [];

  let systemDirs: string[] = [];
  try {
    systemDirs = fs
      .readdirSync(OUTPUTS_DIR, { withFileTypes: true })
      .filter((d) => d.isDirectory() && !d.name.startsWith("_"))
      .map((d) => d.name)
      .sort();
  } catch {
    return { systems: [], sessions: [], scannedAt: new Date().toISOString() };
  }

  for (const system of systemDirs) {
    const dir = path.join(OUTPUTS_DIR, system);
    let files: string[] = [];
    try {
      files = fs.readdirSync(dir);
    } catch {
      continue;
    }
    let count = 0;
    for (const name of files) {
      if (name.endsWith(".violations.json")) continue;
      const m = OUTPUT_RE.exec(name);
      if (!m || !m.groups) continue;
      const { ts, slug } = m.groups as { ts: string; slug: string };
      const sessionId = `${ts}.${slug}`;
      const outPath = path.join(dir, name);
      let outSt: fs.Stats;
      try {
        outSt = fs.statSync(outPath);
      } catch {
        continue;
      }
      const oh = readOutputHeader(outPath, outSt);
      sessions.push({
        system,
        sessionId,
        ts,
        slug,
        mtime: outSt.mtimeMs,
        narrativeId: oh.narrativeId,
        narrativeSnippet: oh.narrativeSnippet,
        runId: oh.runId,
        status: oh.status,
        model: oh.model,
        hasTrace: oh.hasTrace === true,
      });
      count += 1;
    }
    if (count > 0) systems.push({ system, sessionCount: count });
  }

  sessions.sort(
    (a, b) => b.ts.localeCompare(a.ts) || compareNarrativeId(a, b),
  );
  return { systems, sessions, scannedAt: new Date().toISOString() };
}

/** Resolve the artifact paths for one session; null when absent or path-unsafe. */
export function sessionPaths(
  system: string,
  sessionId: string,
): { outPath: string } | null {
  // Path-safety: components must not escape data/outputs. `+` is legal —
  // new artifact stamps look like 20260716T182552491269+1000 (offset suffix);
  // the id is otherwise treated as an opaque string.
  if (!/^[\w.+-]+$/.test(system) || !/^[\w.+-]+$/.test(sessionId)) return null;
  const outPath = path.join(OUTPUTS_DIR, system, `${sessionId}.output.json`);
  if (!fs.existsSync(outPath)) return null;
  return { outPath };
}
