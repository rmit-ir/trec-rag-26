# Context package for architecture proposal

## 1. The challenge (TREC RAG 2026, RAG task)

- Given: a narrative (open-ended deep-research question) and access to the
  ClimbMix-400b corpus via a Pyserini-style retrieval API (search returns
  `{docid, rank, score, doc}`; a separate endpoint fetches full doc text by
  `docid`).
- Task: retrieve relevant evidence and return a summarized answer grounded in
  that evidence. No fixed evidence set is provided — the system does its own
  retrieval. **No web search, no browsing — ClimbMix only. No other corpus.**
- Output: one JSON object per narrative, `answer[]` = array of
  `{text, citations}` objects ("sentence-level", but Markdown headings/labels
  may be their own objects too). `citations` = 0-3 entries, each either a
  0-based index into a `references[]` array of ClimbMix docids or a docid
  directly. Whole answer capped at 1,024 words (`sum(len(t.split()) for t in
  texts)`).
- Evaluation (by TREC organizers, not us): (a) pairwise system-vs-system
  battles judged blind, (b) per-response nugget/rubric scoring
  (AutoNuggetizer-style) against narrative-specific criteria, (c) **weighted
  citation precision** (of sentences with >=1 citation, are the citations
  correct) and **weighted citation recall** (of all sentences, are they
  supported — an uncited sentence scores 0 recall). Precision and recall are
  both real, separately scored axes — a system that hedges by not citing
  loses on recall; a system that cites sloppily loses on precision.
- **Deadline: 2026-08-08 — 2 days from now.** Whatever is proposed must be
  buildable and runnable end-to-end well inside that window, not a research
  program.

## 2. Our stack (what any new system must sit on top of)

Repo: a TREC RAG 2026 submission repo. `src/systems/<name>/` holds each
system; all share three layers under `src/`:

- `agent_harness` — a staged-context, tool-calling research-agent loop
  (`run_agent`). One provider conversation accumulates across turns. Model
  calls `search` (full-text ClimbMix retrieval, results staged for exactly
  one turn) and must then call `commit_context` (keep some staged docs
  verbatim, reject the rest — rejected ones compact to decision markers, not
  deleted from the run's own record). Runs until a token-budget/round cap,
  then the model writes a final cited-prose report (parsed into the
  sentence+citations shape). Callers can override the system prompt, tool
  schemas, engine set, and (new, just shipped) a `pre_final_hook` that can
  send the model back once before accepting a final report. Two LLM backends
  wired in: Bedrock (Claude) and OpenAI-compatible (incl. Azure).
- `tools.search_tool` — the retrieval tool surface: `semantic`, `keyword`,
  `ssr` (Boolean/proximity), `lucene_bool` engines over ClimbMix, one
  `search` tool call names an engine + query + k.
- `ragrun` — trajectory/output artifact building (`TrajectoryBuilder`,
  `build_rag_output`, `save_run`, `validate_rag_output`) — produces exactly
  the JSONL shape §1 describes.

**Existing systems and what each one already tried** (this is the important
part — read before proposing anything, since two prior attempts at
multi-agent decomposition both lost to the simplest system):

1. **`aus_agent`** — THE STRONG BASELINE. One model, one continuously
   accumulating conversation, a long heavily-tuned system prompt (~267
   lines). No separate researcher/finalizer/formatter/compressor role, no
   phase-changing prompt. Retains a large uncurated evidence pool. This is
   what everything else is measured against, and it currently **wins ~77%
   of rubric battles against every other system in this repo.**
2. **`facet_rag`** — a *scripted* multi-agent pipeline: one planner call
   decomposes the narrative into facets, then each facet runs its own
   orchestrator/analyzer/curator loop **concurrently** (`ThreadPoolExecutor`,
   isolated context per facet), a curator trims each facet's evidence before
   final synthesis. **Lost to aus_agent on every one of 5 measured topics on
   UMBRELA (reference relevance)**, despite *beating* aus_agent on
   full-citation-support-rate (0.44 vs 0.35). Root cause: the curator
   over-trims — "content starvation" — each facet's isolated context arrives
   at final synthesis too thin, even though what little survives is well
   supported. (`worklogs/2026-08-05-facet-rag-honest-rebaseline.md`)
3. **`facets_agent`** — the opposite bet: ONE continuous tool-calling agent
   (same `agent_harness` loop as aus_agent) but given a *much shorter*
   prompt (~80 lines) that asks the model to *itself* enact facet_rag's
   process (decompose into facets, search each on complementary engines,
   curate, self-check). **Also loses to aus_agent** — most recent
   measurement (30-topic dev set, this session): aus_agent wins 20 topics
   clean, facets_agent wins 4 clean, 6 ambiguous (76.7% pooled battle
   preference for aus_agent). An LLM root-cause diagnosis attributed the
   loss ~evenly to two things unrelated to facet_rag's failure mode:
   **`not_decomposed`** (47.8% — an implicit requirement, e.g. a compliance
   regime or cost analysis the narrative never names explicitly, never
   makes it into the model's own facet list at all) and
   **`covered_but_shallow`** (47.4% — the facet IS searched, but the final
   answer names a category, e.g. "use caching", instead of the specific
   mechanism the corpus actually surfaced, e.g. "Redis + TTL/eviction").
4. `ali_deepresearch` — a faithful port of Alibaba's Tongyi-DeepResearch
   ReAct agent (single continuous loop, its own prompt/format), web tools
   swapped for ClimbMix tools.
5. `o3_deep_research`, `claude-code-research` — thin adapters around
   OpenAI's o3 deep-research mode / Claude Code itself, respectively, doing
   their own internal orchestration we don't control.

**The pattern that should worry you:** the two systems that already tried
"decompose into sub-tasks + isolate each sub-task's context" (facet_rag,
scripted; facets_agent, single-agent-prompted-to-self-decompose) BOTH lost to
the one system that just gives one model one long prompt, one continuous
context, and a big evidence pool, for two different reasons (over-curation
vs. under-disciplined self-decomposition). A third naive decomposition
architecture that doesn't specifically address *both* failure modes is
likely to lose the same way a third time.

## 3. Candidate open-source frameworks researched (pick one, justify against
the failure modes above)

**A. LangChain `open_deep_research`** (github.com/langchain-ai/open_deep_research,
MIT, LangGraph-based). Supervisor-researcher architecture: a supervisor
agent splits the query into subtopics and spawns parallel sub-agent
researchers, each with its own isolated context window; sub-agents return
findings *with citations* to the supervisor, which decides if more digging
is needed and then orchestrates final report writing. Model/search-tool
pluggable (MCP). Ranked #6 on Deep Research Bench as of the search that
found it. **This is architecturally very close to facet_rag** — same
supervisor+parallel-isolated-subagent shape — so if chosen, the proposal
must explain concretely what changes to avoid facet_rag's content-starvation
failure (e.g.: does the supervisor see full sub-agent transcripts rather
than a compressed summary? is there a synthesis-time re-grounding step
against full document text rather than sub-agent prose?).

**B. GPT Researcher** (github.com/assafelovic/gpt-researcher, most-starred
open-source deep-research project, ~27.6k stars). Different shape: planner
generates research questions, execution/crawler agents gather evidence in
parallel, then a distinct pipeline of roles work the *same shared draft*
sequentially — Editor (plans the outline), Reviewer (validates the draft
against criteria), Reviser (fixes what the reviewer flagged), Writer,
Publisher. The reviewer/reviser loop is a built-in self-correction pass
against explicit criteria, which maps unusually well onto TREC's own
citation-precision/recall split (a reviewer role could directly check
"is every claim cited, is every citation correct" before the run ends) —
this is architecturally different from A/facet_rag's problem (it's a
correctness pass on a shared draft, not context-isolated parallel research),
so it may sidestep the content-starvation risk entirely, at the cost of not
attacking `not_decomposed` as directly.

**C. ByteDance DeerFlow** (github.com/bytedance/deer-flow, LangGraph-based,
~59k stars). A heavier general-purpose "SuperAgent" (research + code +
create), supervisor-orchestrated stateful pipeline with sandboxing,
checkpointing, memory, parallel sub-agents, MCP integration. Powerful but
substantially more infrastructure than a narrow cited-QA task needs — noted
as the least time-appropriate option given the 2-day deadline, included
here only for completeness / to be explicitly ruled out with reasons if you
agree.

## 4. What I'm asking you to do

1. Pick the best-fit framework of the three above (or a hybrid of A and B's
   ideas) for THIS task, and justify the choice explicitly against facet_rag
   and facets_agent's specific, already-measured failure modes — not in the
   abstract.
2. Propose a concrete candidate system architecture for a NEW
   `src/systems/<name>/` in this repo: component/role breakdown, control
   flow (sequence of calls/turns), how it retrieves (which of our engines,
   how many calls, at what granularity), how it decides when to stop, how it
   produces the final `answer[]`/`references[]` shape, and specifically how
   its design prevents (a) facet_rag's content-starvation and (b)
   facets_agent's not-decomposed / covered-but-shallow gaps.
3. Say plainly whether it should reuse `agent_harness.run_agent` (single
   continuous loop, like aus_agent/facets_agent) or needs its own
   orchestration layer (like facet_rag), and why.
4. Be realistic about the 2-day deadline: flag anything in your design that
   is a stretch goal vs. what's truly needed for a working, submittable v1.
