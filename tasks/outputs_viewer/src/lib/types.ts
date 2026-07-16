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
  hasTrajectory: boolean;
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
}

export interface TrajectoryStep {
  type: "reasoning" | "tool_call" | "output_text" | string;
  tool_name?: string | null;
  arguments?: unknown;
  output?: string | null;
  failed?: boolean;
  returned?: { docid: string; score?: number }[];
  returned_docids?: string[];
  /** optional timing contract (src/ragrun/trajectory.py): ISO 8601 UTC, ms precision */
  t_start?: string;
  t_end?: string;
  /** 0-based model-turn index; same-turn items with overlapping times ran in parallel */
  turn?: number;
  [k: string]: unknown;
}

export interface TrajectoryFile {
  metadata: Record<string, unknown>;
  query_id?: string;
  tool_call_counts?: Record<string, number>;
  tool_call_counts_all?: Record<string, number>;
  status?: string;
  retrieved_docids?: string[];
  result?: TrajectoryStep[];
  /** optional run-level timing bounds (ISO 8601 UTC) */
  started_at?: string;
  ended_at?: string;
}

export interface SessionDetail {
  header: SessionHeader;
  output: OutputFile;
  /** trajectory with raw_messages stripped (can be huge) */
  trajectory: TrajectoryFile | null;
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

export type FeedbackTargetType = "answer" | "paragraph" | "citation";

export interface FeedbackTarget {
  type: FeedbackTargetType;
  paragraphIndex?: number;
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
  if (t.type === "paragraph") return `paragraph:${t.paragraphIndex ?? -1}`;
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
