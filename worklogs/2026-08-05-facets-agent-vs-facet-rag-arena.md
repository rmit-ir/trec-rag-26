# 2026-08-05 — facets_agent vs facet_rag: arena comparison, 15 shared topics

**Branch:** `facets_agent`. Ran `facets_agent` (see
`worklogs/2026-08-05-facets-agent-new-system.md`) on the same 15 topics
`facet_rag` already had answers for, then ran a pairwise arena judge between
the two systems on those 15 topics.

## Finding the 15-topic set

`facet_rag`'s own `data/outputs/facet_rag/` only had 5 topics on this
machine. The 15-topic set `facet_rag` has actually produced answers for lives
in `evaluation-results/arena/answers/facet_rag.15topic.jsonl` on the synced
data dir (`/research/remote/petabyte/users/oleg/trec_rag_26_data/` — see
`CLAUDE.md`'s "Environment Rules"), `run_id=facet_rag.arena_15topic`, one
JSONL row per topic in the flat `{run_id, qid, query, answer, references}`
shape. Copied into this repo's own `evaluation-results/arena/answers/` for a
self-contained run (that dir is gitignored, so this copy is local-only, not
committed).

The 15 qids: `683a58c9a7e7fe4e76958498`, `684397d188c1deceb49af325`,
`684397d188c1deceb49af32d`, `6847465956a0f6376a60535d`,
`6847465956a0f6376a605367`, `6847465956a0f6376a605387`,
`6847465956a0f6376a605391`, `6847465956a0f6376a605404`,
`6847465956a0f6376a60542a`, `6847465956a0f6376a605476`,
`6847465956a0f6376a60547e`, `6847465956a0f6376a60547f`,
`6847465956a0f6376a605492`, `6847465956a0f6376a605493`,
`6847465956a0f6376a6054a7`.

## Running facets_agent on the 15 topics

```bash
export OPENAI_API_KEY="$AZURE_OPENAI_API_KEY"   # see env note below
for q in <the 15 qids above>; do
  uv run --group facets-agent python src/systems/facets_agent/run.py \
    --qid "$q" --run-id facets-agent-15topic
done
```

**Env gotcha hit twice this session:** this repo's `.env` carries the Azure
key as `AZURE_OPENAI_API_KEY`, but `aus_agent.providers.openai.OpenAIProvider`
builds a plain `OpenAI()` client that only reads `OPENAI_API_KEY` — so every
invocation needs `export OPENAI_API_KEY="$AZURE_OPENAI_API_KEY"` first (not
persisted to `.env` itself; credentials aren't edited into tracked/synced
files here). First attempt at the 15-topic run also failed immediately
(argparse error: passed `--run-desc`, which `facets_agent/run.py` — like
`aus_agent/run.py` — doesn't define; `run_agent`'s own default description is
good enough). No partial artifacts were written by that failed attempt
(argparse errors before `run_agent` is ever called), so the retry was clean.

**Result: 15/15 completed**, 0 `.violations.json` files (all pass TREC RAG
track validation), references per topic 8–23, all within the 1024-word cap
(364–1024 words). See the previous worklog for the full per-topic table. Full
run log: `worklogs/assets/2026-08-05-facets-agent-15topic-run.log`.

## Arena comparison

`ragdoll arena compare-all` (the RAGDoll CLI's own arena runner) drives models
through the `pi` binary by default (`ragdoll.config`'s `agent_binary = "pi"`),
and `pi` is not installed on this host (`which pi` → nothing). This matches a
comment already in the repo (`tasks/task-comparison/scripts/judge_test119_arena.py`):
"RAGDoll drives models through the `pi` binary, which is not installed on this
host." Followed that script's established workaround instead of trying to
install `pi`: reuse RAGDoll's judging CONTRACT (`ragdoll.arena.prompts`:
`render_arena_prompt`, `parse_verdict`, `TIE_VERDICTS` — pure prompt
templating and verdict parsing, no `pi` dependency) but execute battles
directly through the Azure OpenAI client, same pattern as that script.

New script: `tasks/task-comparison/scripts/arena_facets_agent_vs_facet_rag.py`
(committed — it's code, unlike its `evaluation-results/` output).

Design, matching `judge_test119_arena.py`'s precedent:

- **Every pair judged in both orders** (facets_agent-as-A /
  facet_rag-as-A) and pooled, so position bias is measured
  (`order_consistency`) rather than silently baked into the result.
- Citations need no explicit stripping: `answer[].text` never carries inline
  `[docid]` markers in either system's organizer-schema output (both harnesses
  strip them before writing that field), so joining sentence texts already
  yields a citation-free, system-unidentifiable answer.
- Judge: `gpt-5.6-luna` via the same Azure OpenAI Chat Completions client
  already used by `judge_test119_arena.py`/`rubric-judge/common.py`.

```bash
set -a; source .env; set +a
export OPENAI_API_KEY="$AZURE_OPENAI_API_KEY"
uv run --group aus-agent python \
  tasks/task-comparison/scripts/arena_facets_agent_vs_facet_rag.py --workers 8
```

15 shared topics × 1 pair × 2 orders = 30 battles.

## Result: facets_agent 30–0–0

| | facets_agent | facet_rag |
|---|---|---|
| Wins (of 30 battles, both orders pooled) | 30 | 0 |
| Ties | 0 | 0 |
| Overall preference rate | 1.0000 | 0.0000 |
| `order_consistency` | 1.0 (all 15 topics agreed in both orientations) | |

Full per-battle verdicts: `evaluation-results/arena/facets_agent-vs-facet_rag-15topic/judgments.jsonl`
(gitignored, local only). Aggregate: `.../summary.json`. Console log (all 30
battles + the aggregate table): `worklogs/assets/2026-08-05-arena-facets-agent-vs-facet-rag.log`.

**This is NOT a clean "facets_agent is better" result — read it with three
caveats, in order of how much they explain:**

1. **One topic (`6847465956a0f6376a605387`, the AI-in-legal-field essay) has a
   real, unambiguous facet_rag defect**: `references: []` and every one of
   its 15 answer sentences carries `citations: []` — a completely uncited
   report. That single battle's outcome is a genuine, deserved loss for
   facet_rag on this specific run, not a judge artifact.
2. **facets_agent's answers are substantially and consistently longer.**
   Per-topic word counts (facets_agent / facet_rag): 600/529, 1024/333,
   834/406, 474/399, 945/355, 957/286, 707/366, 546/264, 612/354, 798/284,
   608/640 (the one topic facet_rag is longer on), 757/413, 364/419, 649/242,
   591/150. facet_rag is under 300 words on 5 of 15 topics for requests that
   explicitly ask for comprehensive, multi-part reports. The arena prompt
   (`PAIRWISE_ANSWER_COMPARISON_NAIVE`) explicitly instructs the judge not to
   reward length by itself, but a known LLM-judge length bias is well
   documented in the literature and cannot be ruled out here — a 15-topic,
   single-judge run has no power to separate "genuinely more complete" from
   "judge rewards length despite instructions."
3. **Self-preference risk**: the judge (`gpt-5.6-luna`) is also facets_agent's
   own answer generator, while facet_rag's generators are different models
   (gpt-oss-120b orchestrator + Qwen3 analyzer). Unlike a support/entailment
   judge (checking whether a citation backs a claim), a preference vote is
   exactly where self-preference bias shows up (same caveat
   `judge_test119_arena.py` raises for its own ours-vs-baseline comparison).

None of these caveats individually explains all 30/30 — the uncited-answer
topic is one battle of 30, and self-preference bias is a documented risk, not
a demonstrated magnitude here. Take the 30–0 sweep as a genuine signal that
facets_agent's answers were substantially fuller and better cited on this
particular facet_rag snapshot, not as a validated head-to-head quality ranking
between the two systems' methods — that would need a rubric-grounded or
support-judge comparison (different judge model ideally), not a single
preference-vote arena pass.

## Follow-ups (not done this session)

- A support/entailment judge comparison (checking whether each system's
  citations actually back their claims) would be a stronger, self-preference-
  resistant signal than this preference vote.
- Re-running with a judge model that generated NEITHER system's answers (e.g.
  Bedrock Claude) would remove the self-preference confound entirely.
- Confirm whether `facet_rag.15topic.jsonl`'s uncited outlier topic reflects
  that system's current behavior or a since-fixed regression, before reading
  too much into that one battle.
