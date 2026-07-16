/**
 * Dual execution recording.
 *
 * `trajectory.json` is a strict compatibility artifact shaped like:
 * data/sample-files/run_InfoSeekQA_1000_20260625T230857966818Z.json
 *
 * Rich viewer instrumentation (timings, tokens, documents, context state) is
 * recorded separately and embedded only at `output.json.trace`.
 */

export { nowIso, TZ } from "./time.js";

export interface ItemTiming {
  t_start?: string;
  t_end?: string;
  /** 0-based model-turn index. */
  turn?: number;
}

export interface TokenUsage {
  input?: number;
  output?: number;
  cache_read?: number;
  cache_write?: number;
  total?: number;
}

export interface StepStats {
  duration_ms?: number;
  tokens?: TokenUsage;
  cost_usd?: number;
  returned_documents?: number;
  context_tokens?: number;
  context_budget_tokens?: number;
  elapsed_ms?: number;
  [key: string]: unknown;
}

/** A structured document surfaced by a retrieval action. Search actions carry
 * snippets; get_document actions carry fetched full text. */
export interface TraceDocument {
  /** Retrieval-unit id (may be a chunk id). */
  id: string;
  /** Parent ClimbMix document id. */
  docid: string;
  kind?: "document" | "chunk";
  rank?: number;
  score?: number;
  text?: string | null;
  metadata?: Record<string, unknown>;
}

export interface RejectedContextDocument {
  docid: string;
  reason?: string;
}

export interface StepContext {
  /** Documents made transiently available by this step/action. */
  staged?: string[];
  /** Documents explicitly selected for durable full-text context. */
  committed?: string[];
  /** Documents explicitly discarded by the agent. */
  rejected?: RejectedContextDocument[];
}

export interface TraceItemExtras {
  parent_id?: string | null;
  stats?: StepStats;
  documents?: TraceDocument[];
  context?: StepContext;
}

// ---------------------------------------------------------------------------
// Strict trajectory types — do not add viewer instrumentation here.
// ---------------------------------------------------------------------------

export interface ReasoningItem {
  type: "reasoning";
  tool_name: null;
  arguments: null;
  output: string;
}

export interface ToolCallItem {
  type: "tool_call";
  tool_name: string;
  arguments: string;
  output: string;
  returned_docids?: string[];
  returned?: { docid: string; score: number }[];
  [extra: string]: unknown;
}

export interface OutputTextItem {
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
  raw_messages: unknown[];
}

// ---------------------------------------------------------------------------
// Rich output.trace types.
// ---------------------------------------------------------------------------

export interface TraceStep extends ItemTiming {
  id: string;
  parent_id?: string | null;
  type: "generation" | "reasoning" | "tool_call" | "output_text";
  tool_name: string | null;
  arguments: unknown;
  output: string;
  failed?: boolean;
  returned_docids?: string[];
  returned?: { docid: string; score: number }[];
  stats?: StepStats;
  documents?: TraceDocument[];
  context?: StepContext;
  [extra: string]: unknown;
}

export interface OutputTrace {
  schema_version: "trec-rag-trace/1";
  query_id: string;
  status: RunStatus;
  started_at?: string;
  ended_at?: string;
  duration_ms?: number;
  metadata: Record<string, unknown>;
  summary: {
    tool_call_counts: Record<string, number>;
    tool_call_counts_all: Record<string, number>;
    retrieved_docids: string[];
    usage?: unknown;
  };
  steps: TraceStep[];
  raw_messages: unknown[];
}

export class TrajectoryBuilder {
  readonly queryId: string;
  readonly metadata: Record<string, unknown>;
  /** Strict sample-compatible trajectory result. */
  readonly result: TrajectoryItem[] = [];
  /** Rich steps used only for output.trace. */
  readonly traceSteps: TraceStep[] = [];
  private readonly docids = new Set<string>();
  private readonly failedToolSteps = new Set<number>();

  constructor(queryId: string, query: string, metadata: Record<string, unknown> = {}) {
    this.queryId = queryId;
    this.metadata = { ...metadata };
    if (!("query_source" in this.metadata)) this.metadata.query_source = query;
  }

  addReasoning(
    text: string,
    timing: ItemTiming = {},
    traceExtras: TraceItemExtras = {},
  ): void {
    if (!text) return;
    this.result.push({
      type: "reasoning",
      tool_name: null,
      arguments: null,
      output: text,
    });
    this.traceSteps.push(
      makeTraceStep(
        this.traceSteps.length,
        {
          type: "reasoning",
          tool_name: null,
          arguments: null,
          output: text,
        },
        timing,
        traceExtras,
      ),
    );
  }

  /** Rich-only model span for provider turns that contain no textual
   * reasoning/narration. Nothing is appended to strict trajectory.result. */
  addModelStep(
    output = "",
    timing: ItemTiming = {},
    traceExtras: TraceItemExtras & {
      arguments?: unknown;
      [key: string]: unknown;
    } = {},
  ): void {
    const { arguments: input = null, ...extras } = traceExtras;
    this.traceSteps.push(
      makeTraceStep(
        this.traceSteps.length,
        {
          type: "generation",
          tool_name: null,
          arguments: input,
          output,
        },
        timing,
        extras,
      ),
    );
  }

  addToolCall(
    toolName: string,
    args: unknown,
    output: string,
    opts: {
      returned?: { docid: string; score: number }[];
      returnedDocids?: string[];
      failed?: boolean;
      timing?: ItemTiming;
      stats?: StepStats;
      documents?: TraceDocument[];
      context?: StepContext;
      /** Sample-compatible trajectory extras such as k/original_query. */
      extras?: Record<string, unknown>;
    } = {},
  ): void {
    let returnedDocids = opts.returnedDocids;
    if (returnedDocids === undefined && opts.returned !== undefined) {
      returnedDocids = opts.returned.map((hit) => hit.docid);
    }
    const argumentsText = typeof args === "string" ? args : JSON.stringify(args);

    const strictItem: ToolCallItem = {
      type: "tool_call",
      tool_name: toolName,
      arguments: argumentsText,
      output,
    };
    if (returnedDocids !== undefined) {
      strictItem.returned_docids = [...returnedDocids];
      for (const docid of returnedDocids) this.docids.add(docid);
    }
    if (opts.returned !== undefined) strictItem.returned = opts.returned;
    if (opts.extras) Object.assign(strictItem, opts.extras);
    this.result.push(strictItem);

    const traceIndex = this.traceSteps.length;
    if (opts.failed) this.failedToolSteps.add(traceIndex);
    this.traceSteps.push(
      makeTraceStep(
        traceIndex,
        {
          ...strictItem,
          arguments: args,
          failed: opts.failed ?? false,
        },
        opts.timing ?? {},
        {
          stats: opts.stats,
          documents: opts.documents,
          context: opts.context,
        },
      ),
    );
  }

  addOutputText(
    text: string,
    timing: ItemTiming = {},
    traceExtras: TraceItemExtras = {},
  ): void {
    const strictItem: OutputTextItem = {
      type: "output_text",
      tool_name: null,
      arguments: null,
      output: text,
    };
    this.result.push(strictItem);
    this.traceSteps.push(
      makeTraceStep(this.traceSteps.length, strictItem, timing, traceExtras),
    );
  }

  get retrievedDocids(): Set<string> {
    return this.docids;
  }

  private counts(): {
    ok: Record<string, number>;
    all: Record<string, number>;
  } {
    const ok: Record<string, number> = {};
    const all: Record<string, number> = {};
    this.traceSteps.forEach((step, index) => {
      if (step.type !== "tool_call" || !step.tool_name) return;
      all[step.tool_name] = (all[step.tool_name] ?? 0) + 1;
      if (!this.failedToolSteps.has(index)) {
        ok[step.tool_name] = (ok[step.tool_name] ?? 0) + 1;
      }
    });
    return { ok, all };
  }

  /** Strict trajectory projection. Timings and rich trace fields are omitted. */
  finalize(status: RunStatus = "completed", rawMessages?: unknown[]): Trajectory {
    const counts = this.counts();
    return {
      metadata: this.metadata,
      query_id: this.queryId,
      tool_call_counts: counts.ok,
      tool_call_counts_all: counts.all,
      status,
      retrieved_docids: [...this.docids].sort(),
      result: this.result,
      raw_messages: rawMessages ?? [],
    };
  }

  /** Rich trace projection embedded only under output.json.trace. */
  finalizeTrace(
    status: RunStatus = "completed",
    rawMessages?: unknown[],
    opts: { startedAt?: string; endedAt?: string } = {},
  ): OutputTrace {
    const counts = this.counts();
    const trace: OutputTrace = {
      schema_version: "trec-rag-trace/1",
      query_id: this.queryId,
      status,
      metadata: { ...this.metadata },
      summary: {
        tool_call_counts: counts.ok,
        tool_call_counts_all: counts.all,
        retrieved_docids: [...this.docids].sort(),
      },
      steps: this.traceSteps,
      raw_messages: rawMessages ?? [],
    };
    if (opts.startedAt !== undefined) trace.started_at = opts.startedAt;
    if (opts.endedAt !== undefined) trace.ended_at = opts.endedAt;
    const started = opts.startedAt ? Date.parse(opts.startedAt) : Number.NaN;
    const ended = opts.endedAt ? Date.parse(opts.endedAt) : Number.NaN;
    if (Number.isFinite(started) && Number.isFinite(ended) && ended >= started) {
      trace.duration_ms = ended - started;
    }
    if (this.metadata.usage !== undefined) trace.summary.usage = this.metadata.usage;
    return trace;
  }
}

function makeTraceStep(
  index: number,
  base: {
    type: TraceStep["type"];
    tool_name: string | null;
    arguments: unknown;
    output: string;
    failed?: boolean;
  },
  timing: ItemTiming,
  extras: TraceItemExtras,
): TraceStep {
  const step: TraceStep = {
    ...base,
    id: `step-${String(index).padStart(4, "0")}`,
  } as TraceStep;
  if (timing.t_start !== undefined) step.t_start = timing.t_start;
  if (timing.t_end !== undefined) step.t_end = timing.t_end;
  if (timing.turn !== undefined) {
    step.turn = timing.turn;
    step.parent_id = extras.parent_id ?? `turn-${timing.turn}`;
  } else if (extras.parent_id !== undefined) {
    step.parent_id = extras.parent_id;
  }

  const start = timing.t_start ? Date.parse(timing.t_start) : Number.NaN;
  const end = timing.t_end ? Date.parse(timing.t_end) : Number.NaN;
  const duration =
    Number.isFinite(start) && Number.isFinite(end) && end >= start
      ? end - start
      : undefined;
  if (duration !== undefined || extras.stats !== undefined) {
    step.stats = {
      ...(duration !== undefined ? { duration_ms: duration } : {}),
      ...(extras.stats ?? {}),
    };
  }
  if (extras.documents !== undefined) step.documents = [...extras.documents];
  if (extras.context !== undefined) step.context = { ...extras.context };
  return step;
}
