/** Shared (client-safe) types for API payloads. No secrets, no fs. */

export interface SessionHeader {
  system: string;
  sessionId: string; // "<ts>.<slug>"
  ts: string; // timestamp part of the basename
  slug: string;
  mtime: number; // newest mtime of the pair, ms epoch
  narrativeId?: string;
  narrativeSnippet?: string; // first words only
  status?: string;
  runId?: string;
  model?: string;
  hasTrace: boolean;
}

export interface OutputsIndex {
  systems: { system: string; sessionCount: number }[];
  sessions: SessionHeader[];
  scannedAt: string;
}

export interface AnswerSentence {
  text: string;
  citations: number[];
}

/** Track cap on total answer words (rag-task.md; enforced by both validators). */
export const ANSWER_WORD_LIMIT = 1024;

/**
 * Total answer words, counted exactly as the track validators do
 * (`src/ragrun/outputs.py` / `tasks/pi-agent/src/outputs.ts`): whitespace-split
 * words over each sentence's text. Traces do not carry this number — it is
 * always derived from the answer itself.
 */
export function countAnswerWords(answer: AnswerSentence[]): number {
  return answer.reduce(
    (n, s) => n + s.text.split(/\s+/).filter(Boolean).length,
    0,
  );
}

export interface OutputFile {
  metadata: {
    team_id?: string;
    narrative_id?: string;
    narrative?: string;
    run_id?: string;
    run_desc?: string;
    [k: string]: unknown;
  };
  references: string[];
  answer: AnswerSentence[];
  trace?: TraceFile;
}

export interface TokenStats {
  input?: number;
  input_uncached?: number;
  output?: number;
  cache_read?: number;
  cache_write?: number;
  total?: number;
  processed_input?: number;
  processed?: number;
  context_tokens?: number;
  peak_context_tokens?: number;
  context_budget_tokens?: number;
  budget?: number;
}

export interface StepStats {
  duration_ms?: number;
  tokens?: TokenStats;
  cumulative_tokens?: TokenStats;
  cost_usd?: number;
  returned_documents?: number;
  context_tokens?: number;
  peak_context_tokens?: number;
  context_budget_tokens?: number;
  elapsed_ms?: number;
  [k: string]: unknown;
}

export interface StepContext {
  staged?: string[];
  committed?: string[];
  rejected?: { docid: string; reason?: string }[];
}

export interface TraceStep {
  id?: string;
  parent_id?: string | null;
  type: "reasoning" | "tool_call" | "output_text" | string;
  tool_name?: string | null;
  input?: unknown;
  arguments?: unknown;
  output?: unknown;
  tool_call_id?: string;
  failed?: boolean;
  returned?: { docid: string; score?: number }[];
  returned_docids?: string[];
  context?: StepContext;
  stats?: StepStats;
  /** ISO 8601 with UTC offset and millisecond precision. */
  t_start?: string;
  t_end?: string;
  /** 0-based model-turn index; same-turn items with overlapping times ran in parallel */
  turn?: number;
  [k: string]: unknown;
}

export interface TraceFile {
  schema_version?: string;
  metadata: Record<string, unknown>;
  /** Harness settings the run was launched with (e.g. max_committed_per_step). */
  config?: Record<string, unknown>;
  query_id?: string;
  status?: string;
  input?: unknown;
  output?: unknown;
  summary?: {
    tool_call_counts?: Record<string, number>;
    tool_call_counts_all?: Record<string, number>;
    retrieved_docids?: string[];
    tokens?: TokenStats;
    usage?: unknown;
  };
  steps?: TraceStep[];
  started_at?: string;
  ended_at?: string;
  duration_ms?: number;
}

export interface SessionDetail {
  header: SessionHeader;
  output: OutputFile;
  /** Loaded exclusively from output.json.trace. */
  trace: TraceFile | null;
}

export interface DocResult {
  requestedId: string;
  resolvedId: string;
  kind: "document" | "chunk";
  /** which backend actually served the text */
  source: "dense" | "pyserini";
  /** true when a chunk id fell back to fetching its parent document */
  parentFallback: boolean;
  text: string;
}

/** Lifecycle of a viewer-spawned agent run. */
export type RunStatus = "running" | "completed" | "failed" | "timeout";

export interface RunRecord {
  /** Viewer-side handle (uuid), distinct from the harness `--run-id`. */
  id: string;
  /** The `--run-id` passed to run.py; groups the artifacts it writes. */
  runId: string;
  system: string;
  query: string;
  status: RunStatus;
  startedAt: number; // ms epoch
  endedAt?: number;
  pid?: number | null;
  exitCode?: number | null;
  signal?: string | null;
  /** Set once the wall-clock cap fires, before the process actually exits. */
  timedOut?: boolean;
  error?: string;
  /** Bounded tail of the child's stdout+stderr. */
  logTail: string[];
}

export type FeedbackTargetType = "answer" | "sentence" | "citation";

export interface FeedbackTarget {
  type: FeedbackTargetType;
  sentenceIndex?: number;
  docid?: string;
}

export interface FeedbackRecord {
  id: string;
  user: string;
  system: string;
  sessionId: string;
  target: FeedbackTarget;
  rating: "up" | "down" | null;
  comment: string;
  tags: string[];
  createdAt: string; // ISO
}

/** Stable key identifying a feedback target within (user, system, session). */
export function targetKey(t: FeedbackTarget): string {
  if (t.type === "sentence") return `sentence:${t.sentenceIndex ?? -1}`;
  if (t.type === "citation") return `citation:${t.docid ?? ""}`;
  return "answer";
}

/** Chunk ids look like <docid>_p<n>; rows are pure digits so this is unambiguous. */
export function isChunkId(id: string): boolean {
  return /_p\d+$/.test(id);
}
export function parentDocid(id: string): string {
  return isChunkId(id) ? id.replace(/_p\d+$/, "") : id;
}
