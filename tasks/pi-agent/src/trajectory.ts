/**
 * Trajectory recording — TS port of `src/ragrun/trajectory.py`.
 * Produces a dict shaped like the reference sample
 * `data/sample-files/run_InfoSeekQA_1000_20260625T230857966818Z.json`.
 */

export { nowIso, TZ } from "./time.js";

/** Optional wall-clock timing on a result item (additive — old artifacts
 *  without these stay valid). Timestamps are Melbourne-local ISO 8601 with
 *  ms precision and offset (`nowIso()`), e.g. `2026-07-16T18:21:34.342+10:00`.
 *  Items sharing a `turn` with overlapping [t_start, t_end] ran in PARALLEL;
 *  viewers render them in parallel lanes. */
export interface ItemTiming {
  t_start?: string;
  t_end?: string;
  /** 0-based model-turn index. */
  turn?: number;
}

export interface ReasoningItem extends ItemTiming {
  type: "reasoning";
  tool_name: null;
  arguments: null;
  output: string;
}

export interface ToolCallItem extends ItemTiming {
  type: "tool_call";
  tool_name: string;
  arguments: string;
  output: string;
  failed: boolean;
  returned_docids?: string[];
  returned?: { docid: string; score: number }[];
  [extra: string]: unknown;
}

export interface OutputTextItem extends ItemTiming {
  type: "output_text";
  tool_name: null;
  arguments: null;
  output: string;
}

export type TrajectoryItem = ReasoningItem | ToolCallItem | OutputTextItem;

export type RunStatus = "completed" | "failed" | "budget_exhausted";

export interface Trajectory {
  metadata: Record<string, unknown>;
  query_id: string;
  tool_call_counts: Record<string, number>;
  tool_call_counts_all: Record<string, number>;
  status: RunStatus;
  retrieved_docids: string[];
  result: TrajectoryItem[];
  /** Melbourne-local ISO run bounds (optional, additive). */
  started_at?: string;
  ended_at?: string;
  raw_messages?: unknown[];
}

export class TrajectoryBuilder {
  readonly queryId: string;
  readonly metadata: Record<string, unknown>;
  readonly result: TrajectoryItem[] = [];
  private readonly docids = new Set<string>();

  constructor(queryId: string, query: string, metadata: Record<string, unknown> = {}) {
    this.queryId = queryId;
    this.metadata = { ...metadata };
    // The sample format carries the query in metadata.query_source.
    if (!("query_source" in this.metadata)) this.metadata.query_source = query;
  }

  /** One block of model thinking (interleaved between tool calls). */
  addReasoning(text: string, timing: ItemTiming = {}): void {
    if (text) {
      const item: ReasoningItem = { type: "reasoning", tool_name: null, arguments: null, output: text };
      addTiming(item, timing);
      this.result.push(item);
    }
  }

  /** One executed tool call. `failed: true` counts in tool_call_counts_all only. */
  addToolCall(
    toolName: string,
    args: unknown,
    output: string,
    opts: {
      returned?: { docid: string; score: number }[];
      returnedDocids?: string[];
      failed?: boolean;
      /** Real execution bounds + model-turn index of this call. */
      timing?: ItemTiming;
      extras?: Record<string, unknown>;
    } = {},
  ): void {
    let returnedDocids = opts.returnedDocids;
    if (returnedDocids === undefined && opts.returned !== undefined) {
      returnedDocids = opts.returned.map((h) => h.docid);
    }
    const item: ToolCallItem = {
      type: "tool_call",
      tool_name: toolName,
      arguments: typeof args === "string" ? args : JSON.stringify(args),
      output,
      failed: opts.failed ?? false,
    };
    if (returnedDocids !== undefined) {
      item.returned_docids = [...returnedDocids];
      for (const d of returnedDocids) this.docids.add(d);
    }
    if (opts.returned !== undefined) item.returned = opts.returned;
    addTiming(item, opts.timing ?? {});
    if (opts.extras) Object.assign(item, opts.extras);
    this.result.push(item);
  }

  /** The final answer text (last item of result). */
  addOutputText(text: string, timing: ItemTiming = {}): void {
    const item: OutputTextItem = { type: "output_text", tool_name: null, arguments: null, output: text };
    addTiming(item, timing);
    this.result.push(item);
  }

  get retrievedDocids(): Set<string> {
    return this.docids;
  }

  finalize(
    status: RunStatus = "completed",
    rawMessages?: unknown[],
    opts: { startedAt?: string; endedAt?: string } = {},
  ): Trajectory {
    const countsOk: Record<string, number> = {};
    const countsAll: Record<string, number> = {};
    for (const item of this.result) {
      if (item.type !== "tool_call") continue;
      const name = item.tool_name;
      countsAll[name] = (countsAll[name] ?? 0) + 1;
      if (!item.failed) countsOk[name] = (countsOk[name] ?? 0) + 1;
    }
    const traj: Trajectory = {
      metadata: this.metadata,
      query_id: this.queryId,
      tool_call_counts: countsOk,
      tool_call_counts_all: countsAll,
      status,
      retrieved_docids: [...this.docids].sort(),
      result: this.result,
    };
    if (opts.startedAt !== undefined) traj.started_at = opts.startedAt;
    if (opts.endedAt !== undefined) traj.ended_at = opts.endedAt;
    if (rawMessages !== undefined) traj.raw_messages = rawMessages;
    return traj;
  }
}

/** Attach optional timing/turn fields (additive; old readers ignore). */
function addTiming(item: ItemTiming, timing: ItemTiming): void {
  if (timing.t_start !== undefined) item.t_start = timing.t_start;
  if (timing.t_end !== undefined) item.t_end = timing.t_end;
  if (timing.turn !== undefined) item.turn = timing.turn;
}
