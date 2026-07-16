/**
 * The TREC RAG 2026 research agent — pi-agent-core's `runAgentLoop` over
 * pi-ai's Amazon Bedrock backend, with ClimbMix-only retrieval tools.
 *
 * Flow per topic:
 *  1. agentic tool loop (search + get_document, max --max-rounds LLM turns),
 *  2. one final strict-JSON model turn that emits sentence/citation pairs
 *     citing ClimbMix docids,
 *  3. docids are mapped to reference indices (docids never retrieved during
 *     the run are dropped), the answer is trimmed to the 1024-word budget,
 *  4. both artifacts are written to data/outputs/pi-agent/.
 */
import {
  completeSimple,
  type AssistantMessage,
  type Context,
  type Message,
} from "@mariozechner/pi-ai";
import {
  runAgentLoop,
  type AgentContext,
  type AgentEvent,
  type AgentLoopConfig,
  type ThinkingLevel,
} from "@mariozechner/pi-agent-core";
import { DEFAULT_K, DEFAULT_MAX_ROUNDS, TEAM_ID } from "./config.js";
import { resolveBedrockModel } from "./model.js";
import { classifyId } from "./search.js";
import { createGetDocumentTool, createSearchTool, type ToolDetails } from "./tools.js";
import {
  nowIso,
  TrajectoryBuilder,
  type ItemTiming,
  type RunStatus,
  type StepStats,
  type TokenUsage,
  type Trajectory,
} from "./trajectory.js";
import {
  buildRagOutput,
  saveRun,
  validateRagOutput,
  type AnswerSentence,
  type RagOutput,
  type SavedPaths,
} from "./outputs.js";

const SYSTEM_PROMPT = `You are a research agent for the TREC RAG 2026 track. You write long-form, evidence-grounded answers to research questions using ONLY the ClimbMix corpus, accessed through your two tools:

- search: hybrid dense (Jina-v5) + sparse (BM25) retrieval over ClimbMix, fused with Reciprocal Rank Fusion. Returns ranked snippets with parent document ids (docid).
- get_document: fetch the full text of one ClimbMix document by docid.

Method:
1. Decompose the question into sub-questions and run several searches with varied phrasings (typically 4-10 searches across the whole task) to cover every aspect of the topic.
2. Skim the returned snippets; call get_document on at least the 3-5 most promising docids to read the full documents before relying on them — snippets alone are often misleading.
3. Track which docid supports each claim. Only claims supported by documents you actually retrieved may appear in the final answer. Do not rely on prior knowledge you cannot ground in a retrieved document.
4. When you have enough evidence, stop calling tools and write the final answer: a well-structured research report in plain prose, under 900 words, where every factual sentence is attributable to one or more retrieved ClimbMix docids.

Citations always use ClimbMix document ids like shard_00459_61697 (never chunk ids like shard_00459_61697_p3).
You have no web access; the two tools above are your only information sources.`;

const FINALIZE_PROMPT = `Now convert your final answer into strict JSON — output ONLY the JSON object, with no markdown fences and no commentary:

{"answer": [{"text": "<exactly one sentence>", "citations": ["<docid>", ...]}, ...]}

Rules:
- Split the answer into individual sentences, one per array element, preserving the report's content and order.
- "citations" lists 0-3 ClimbMix docids (e.g. "shard_00459_61697") that directly support that sentence, strongest support first. Only cite docids returned by your searches in this conversation; never invent docids and never cite chunk ids (strip any _p<n> suffix).
- Every factual sentence should carry at least one citation.
- Keep the total across all sentences at or below 900 words.`;

export interface RunAgentOptions {
  queryId: string;
  query: string;
  modelId: string;
  k?: number;
  maxRounds?: number;
  thinkingLevel?: ThinkingLevel;
  runId?: string;
  runDesc?: string;
  log?: (line: string) => void;
}

export interface RunAgentResult {
  trajectory: Trajectory;
  output: RagOutput;
  paths: SavedPaths;
  violations: string[];
}

function textOf(content: { type: string }[] | string | undefined): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((b: any) => b.type === "text")
    .map((b: any) => b.text)
    .join("\n");
}

/** Extract the first JSON object from a model reply (tolerates fences). */
function extractJson(text: string): any {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const candidates = [fenced?.[1], text];
  for (const c of candidates) {
    if (!c) continue;
    const start = c.indexOf("{");
    const end = c.lastIndexOf("}");
    if (start === -1 || end <= start) continue;
    try {
      return JSON.parse(c.slice(start, end + 1));
    } catch {
      /* try next candidate */
    }
  }
  throw new Error(`Could not parse JSON from model reply: ${text.slice(0, 200)}...`);
}

interface RawSentence {
  text: string;
  citations: string[];
}

function parseSentences(obj: any): RawSentence[] {
  const arr = Array.isArray(obj) ? obj : obj?.answer;
  if (!Array.isArray(arr)) throw new Error("finalize JSON has no 'answer' array");
  const out: RawSentence[] = [];
  for (const s of arr) {
    if (typeof s?.text !== "string" || !s.text.trim()) continue;
    const cits = Array.isArray(s.citations) ? s.citations.filter((c: unknown) => typeof c === "string") : [];
    out.push({ text: s.text.trim(), citations: cits });
  }
  if (out.length === 0) throw new Error("finalize JSON contained no usable sentences");
  return out;
}

const countWords = (s: string): number => s.split(/\s+/).filter(Boolean).length;

function statsFromUsage(usage: any): StepStats | undefined {
  if (!usage || typeof usage !== "object") return undefined;
  const tokens: TokenUsage = {
    input: Number(usage.input ?? 0),
    output: Number(usage.output ?? 0),
    cache_read: Number(usage.cacheRead ?? 0),
    cache_write: Number(usage.cacheWrite ?? 0),
    total: Number(
      usage.totalTokens ??
        Number(usage.input ?? 0) +
          Number(usage.output ?? 0) +
          Number(usage.cacheRead ?? 0) +
          Number(usage.cacheWrite ?? 0),
    ),
  };
  return { tokens, cost_usd: Number(usage.cost?.total ?? 0) };
}

function addStepStats(a: StepStats | undefined, b: StepStats | undefined): StepStats | undefined {
  if (!a) return b;
  if (!b) return a;
  const at = a.tokens ?? {};
  const bt = b.tokens ?? {};
  return {
    ...a,
    ...b,
    tokens: {
      input: Number(at.input ?? 0) + Number(bt.input ?? 0),
      output: Number(at.output ?? 0) + Number(bt.output ?? 0),
      cache_read: Number(at.cache_read ?? 0) + Number(bt.cache_read ?? 0),
      cache_write: Number(at.cache_write ?? 0) + Number(bt.cache_write ?? 0),
      total: Number(at.total ?? 0) + Number(bt.total ?? 0),
    },
    cost_usd: Number(a.cost_usd ?? 0) + Number(b.cost_usd ?? 0),
  };
}

/** docid strings → reference indices; drops never-retrieved docids, maps
 *  chunk ids to parents, caps 3 citations/sentence, enforces the 1024-word
 *  budget, and keeps only cited references. */
export function assembleAnswer(
  sentences: RawSentence[],
  retrieved: ReadonlySet<string>,
): { references: string[]; answer: AnswerSentence[] } {
  // Trim to the word budget first (whole sentences from the end).
  const kept: RawSentence[] = [];
  let words = 0;
  for (const s of sentences) {
    const w = countWords(s.text);
    if (words + w > 1024) break;
    kept.push(s);
    words += w;
  }

  const references: string[] = [];
  const refIndex = new Map<string, number>();
  const answer: AnswerSentence[] = kept.map((s) => {
    const cits: number[] = [];
    for (const raw of s.citations) {
      const { docid } = classifyId(raw.trim()); // chunk id → parent docid
      if (!retrieved.has(docid)) continue; // drop docids never retrieved
      let idx = refIndex.get(docid);
      if (idx === undefined) {
        idx = references.length;
        references.push(docid);
        refIndex.set(docid, idx);
      }
      if (!cits.includes(idx)) cits.push(idx);
      if (cits.length === 3) break; // max 3 citations per sentence
    }
    return { text: s.text, citations: cits };
  });
  return { references, answer };
}

export async function runResearchAgent(opts: RunAgentOptions): Promise<RunAgentResult> {
  const startedAt = nowIso();
  const k = opts.k ?? DEFAULT_K;
  const maxRounds = opts.maxRounds ?? DEFAULT_MAX_ROUNDS;
  const thinkingLevel: ThinkingLevel = opts.thinkingLevel ?? "medium";
  const log = opts.log ?? ((line: string) => console.error(line));
  const model = resolveBedrockModel(opts.modelId);
  const runId = opts.runId ?? `pi-agent-${opts.modelId.split(".").pop()}`;
  const runDesc =
    opts.runDesc ??
    "pi-agent (pi-agent-core/pi-ai on Amazon Bedrock): agentic ClimbMix-only RAG — iterative hybrid " +
      "dense+sparse retrieval with RRF fusion plus full-document fetch, followed by a strict-JSON " +
      "sentence/citation generation turn.";

  const tb = new TrajectoryBuilder(opts.queryId, opts.query, {
    model: opts.modelId,
    provider: "amazon-bedrock",
    api: "bedrock-converse-stream",
    framework: "@mariozechner/pi-agent-core 0.73.1 + @mariozechner/pi-ai 0.73.1",
    thinking_level: thinkingLevel,
    k,
    max_rounds: maxRounds,
    query_source: opts.query,
    team_id: TEAM_ID,
    run_id: runId,
  });

  const tools = [createSearchTool(k), createGetDocumentTool()];
  const context: AgentContext = { systemPrompt: SYSTEM_PROMPT, messages: [], tools };

  let rounds = 0;
  let finalAnswerText = "";
  let sawError: string | undefined;
  // Wall-clock timing state (Melbourne-local, `nowIso()`), all additive fields.
  let turnIndex = -1; // 0-based model-turn index, bumped on each turn_start
  let turnT0 = startedAt; // start of the current model turn (LLM request)
  let lastAssistantTiming: ItemTiming | undefined; // fallback bounds for output_text
  let lastAssistantStats: StepStats | undefined;
  const pendingCalls = new Map<string, { args: unknown; tStart: string }>();

  const config: AgentLoopConfig = {
    model,
    reasoning: thinkingLevel === "off" ? undefined : thinkingLevel,
    convertToLlm: (messages) => messages as Message[],
    // Same-turn tool calls execute concurrently (Promise.all inside
    // pi-agent-core's executeToolCallsParallel), so their output trace steps
    // share a `turn` with genuinely overlapping [t_start, t_end].
    toolExecution: "parallel",
    shouldStopAfterTurn: () => {
      rounds += 1;
      if (rounds >= maxRounds) {
        log(`[agent] max rounds (${maxRounds}) reached — stopping loop`);
        return true;
      }
      return false;
    },
  };

  const onEvent = (event: AgentEvent): void => {
    switch (event.type) {
      case "turn_start":
        turnIndex += 1;
        turnT0 = nowIso();
        log(`[agent] turn ${turnIndex + 1}/${maxRounds}`);
        break;
      case "message_end": {
        const msg = event.message as AssistantMessage;
        if (msg.role !== "assistant") break;
        // Model-turn bounds: turn_start (request sent) → assistant stream end.
        const timing: ItemTiming = { t_start: turnT0, t_end: nowIso(), turn: turnIndex };
        const stats = statsFromUsage(msg.usage);
        lastAssistantTiming = timing;
        lastAssistantStats = stats;
        if (msg.stopReason === "error" || msg.errorMessage) {
          sawError = msg.errorMessage ?? "assistant turn failed";
          log(`[agent] model error: ${sawError}`);
        }
        const hasToolCalls = msg.content.some((b) => b.type === "toolCall");
        let statsAttached = false;
        for (const block of msg.content) {
          if (block.type === "thinking" && block.thinking) {
            tb.addReasoning(block.thinking, timing, statsAttached ? {} : { stats });
            statsAttached = true;
            log(`[agent] thinking: ${block.thinking.replace(/\s+/g, " ").slice(0, 120)}...`);
          } else if (block.type === "text" && block.text.trim()) {
            if (hasToolCalls) {
              // Interleaved commentary between tool calls — keep as reasoning.
              tb.addReasoning(block.text, timing, statsAttached ? {} : { stats });
              statsAttached = true;
            } else {
              finalAnswerText = finalAnswerText ? `${finalAnswerText}\n${block.text}` : block.text;
            }
          }
        }
        if (hasToolCalls && !statsAttached) {
          tb.addModelStep("", timing, { stats });
        }
        break;
      }
      case "tool_execution_start":
        pendingCalls.set(event.toolCallId, { args: event.args, tStart: nowIso() });
        log(`[agent] tool ${event.toolName}(${JSON.stringify(event.args)})`);
        break;
      case "tool_execution_end": {
        const pending = pendingCalls.get(event.toolCallId);
        pendingCalls.delete(event.toolCallId);
        const args = pending?.args ?? {};
        const details = (event.result?.details ?? {}) as ToolDetails;
        const output = textOf(event.result?.content);
        tb.addToolCall(event.toolName, args, output, {
          returned: details.returned,
          returnedDocids: details.returnedDocids,
          failed: event.isError,
          timing: { t_start: pending?.tStart, t_end: nowIso(), turn: turnIndex },
          documents: details.documents,
          context: details.returnedDocids?.length
            ? { staged: [...details.returnedDocids] }
            : undefined,
          stats: { returned_documents: details.returnedDocids?.length ?? 0 },
          extras: event.toolName === "search" ? { k: (args as any).k ?? k } : undefined,
        });
        const n = details.returnedDocids?.length ?? 0;
        log(`[agent] tool ${event.toolName} -> ${event.isError ? "ERROR" : `${n} docids`}`);
        break;
      }
      default:
        break;
    }
  };

  // ---- 1. agentic tool loop -------------------------------------------------
  const loopMessages = await runAgentLoop(
    [{ role: "user", content: opts.query, timestamp: Date.now() } as Message],
    context,
    config,
    onEvent,
  );

  let status: RunStatus;
  if (sawError && !finalAnswerText) status = "failed";
  else if (finalAnswerText) status = "completed";
  else status = "budget_exhausted";

  // ---- 2. final strict-JSON turn -------------------------------------------
  const rawMessages: unknown[] = [...(loopMessages as Message[])];
  let sentences: RawSentence[] = [];
  // The finalize turn is one extra model turn after the loop's last turn.
  let finalizeTiming: ItemTiming | undefined;
  let finalizeStats: StepStats | undefined;
  if (tb.retrievedDocids.size > 0 && status !== "failed") {
    // Bedrock requires toolConfig whenever the replayed transcript contains
    // toolUse/toolResult blocks, so the finalize context keeps the tools
    // declared even though the prompt demands a JSON-only reply.
    const finalizeContext: Context = {
      systemPrompt: SYSTEM_PROMPT,
      messages: [
        ...(loopMessages as Message[]),
        { role: "user", content: FINALIZE_PROMPT, timestamp: Date.now() },
      ],
      tools,
    };
    log("[agent] finalize: requesting strict-JSON sentence/citation answer");
    finalizeTiming = { t_start: nowIso(), turn: turnIndex + 1 };
    try {
      let reply = await completeSimple(model, finalizeContext, {
        reasoning: thinkingLevel === "off" ? undefined : thinkingLevel,
      });
      finalizeTiming.t_end = nowIso();
      finalizeStats = addStepStats(finalizeStats, statsFromUsage(reply.usage));
      rawMessages.push(finalizeContext.messages[finalizeContext.messages.length - 1], reply);
      if (reply.stopReason === "error" || reply.errorMessage) {
        throw new Error(reply.errorMessage ?? "finalize turn failed");
      }
      try {
        sentences = parseSentences(extractJson(textOf(reply.content)));
      } catch (parseErr) {
        log(`[agent] finalize JSON parse failed (${parseErr}); retrying once`);
        const retryContext: Context = {
          systemPrompt: SYSTEM_PROMPT,
          tools,
          messages: [
            ...finalizeContext.messages,
            reply,
            {
              role: "user",
              content:
                "That was not valid JSON. Reply again with ONLY the JSON object in the required schema.",
              timestamp: Date.now(),
            },
          ],
        };
        reply = await completeSimple(model, retryContext, {
          reasoning: thinkingLevel === "off" ? undefined : thinkingLevel,
        });
        finalizeTiming.t_end = nowIso();
        finalizeStats = addStepStats(finalizeStats, statsFromUsage(reply.usage));
        rawMessages.push(retryContext.messages[retryContext.messages.length - 1], reply);
        sentences = parseSentences(extractJson(textOf(reply.content)));
      }
    } catch (err) {
      log(`[agent] finalize turn failed: ${err}`);
      status = "failed";
    }
  } else if (status !== "failed") {
    log("[agent] no documents retrieved — cannot build a grounded answer");
    status = "failed";
  }

  // ---- 3. assemble output ---------------------------------------------------
  const { references, answer } = assembleAnswer(sentences, tb.retrievedDocids);
  if (answer.length === 0 && status === "completed") status = "failed";

  if (!finalAnswerText && sentences.length > 0) {
    finalAnswerText = sentences.map((s) => s.text).join(" ");
  }
  if (finalAnswerText) {
    // Bounds of the final structured-answer turn; if it never ran (or died
    // before its first reply), fall back to the last assistant turn's bounds.
    const timing = finalizeTiming?.t_end !== undefined ? finalizeTiming : lastAssistantTiming;
    tb.addOutputText(finalAnswerText, timing ?? {}, {
      stats: finalizeTiming?.t_end !== undefined ? finalizeStats : lastAssistantStats,
    });
  }

  tb.metadata.rounds_used = rounds;
  const usage = rawMessages
    .filter((m): m is AssistantMessage => (m as any).role === "assistant")
    .reduce(
      (acc, m) => {
        acc.input += m.usage?.input ?? 0;
        acc.output += m.usage?.output ?? 0;
        acc.cache_read += m.usage?.cacheRead ?? 0;
        acc.cache_write += m.usage?.cacheWrite ?? 0;
        acc.total += m.usage?.totalTokens ?? 0;
        acc.cost += m.usage?.cost?.total ?? 0;
        return acc;
      },
      { input: 0, output: 0, cache_read: 0, cache_write: 0, total: 0, cost: 0 },
    );
  tb.metadata.usage = usage;

  const endedAt = nowIso();
  const trajectory = tb.finalize(status, rawMessages);
  const trace = tb.finalizeTrace(status, rawMessages, { startedAt, endedAt });
  const output = buildRagOutput({
    narrativeId: opts.queryId,
    narrative: opts.query,
    runId,
    runDesc,
    references,
    answer: answer.length > 0 ? answer : [{ text: "No grounded answer could be produced.", citations: [] }],
  });

  // ---- 4. persist ------------------------------------------------------------
  const paths = saveRun(opts.query, trajectory, output, { trace });
  const violations = validateRagOutput(output);
  return { trajectory, output, paths, violations };
}
