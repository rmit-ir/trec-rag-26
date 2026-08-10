# open_weight_agent — open-weight-only fork of brief_revise_agent + a blind scout (TREC RAG 2026)

**Every model call in this pipeline runs an open-weight model** — main
research/writer, requirements-brief analyst, blind obligation scout,
reviewer. No OpenAI `gpt-5.6-*` model, no proprietary Bedrock model
(`anthropic.*`), anywhere in the default/deployable configuration.
`agent.ALLOWED_MODELS` is the enforced allowlist; `agent._check_model`
raises before any provider is constructed if a caller passes anything
else, in any role — with one explicit, loudly-labeled exception: a
support role (never the main writer) may opt into a proprietary model via
`--brief-backend openai`/`--scout-backend openai`/`--review-backend
openai`, a diagnostic-only escape hatch for offline role-decoupling
experiments (never submission-eligible; see `_check_model`'s own
docstring and `worklogs/2026-08-09-oss-agent-open-weight-system.md`).

## Design lineage

`worklogs/assets/2026-08-07-factor-analysis-report/report.typ` ranks every
system in this repo (§10.2–10.3): `aus_agent_v2` is the strongest system by
every available comparison (best arena performer, §5) but the most
expensive by a wide margin (\$1,096.72 documented build cost, README) and
depends on `gpt-5.6-*` throughout; `brief_revise_agent`'s base cell ties it
exactly on standalone rubric grading (2.267/3, §4.5) at roughly 1/50th the
cost (\$21.61 vs. \$1,096.72 for a 15-topic batch, §7), with a much simpler
architecture: one pre-flight requirements brief + one review/revise pass
over the shared `agent_harness.agent.run_agent` loop.

`open_weight_agent` takes `brief_revise_agent` as its base — reusing its
`brief.py`/`review.py`/`adjacent_pages.py` modules directly via import,
not by copying them — and adds exactly one structural idea ported from
`aus_agent_v2`: its blind obligation-scout stage (`plan_critic.py`,
`systems/open_weight_agent/scout.py`), a second independent pre-flight call shown
only the original request, never the requirements brief's own output. This
is taxonomy factor **S14** (newly added,
`worklogs/assets/2026-08-07-terra-factor-taxonomy-final.md`).

Two factors already confirmed in the report are adopted as defaults rather
than re-derived from scratch:

- **S5 `adjacent_page_augmentation`** — on by default (zero extra LLM
  calls; confirmed real for both `sol` and `qwen`, report §4.2).
- **S6 `retrieval_engine_set`** — `hybrid` alone, not the
  `semantic,keyword` default pair. The report's own §4.6 confirms this is
  the one retrieval-engine lever that is both cheaper AND scores higher on
  standalone rubric, replicated on two independent 15-topic sets — but
  that evidence is `sol`-specific (OpenAI backend); `open_weight_agent`'s own
  bake-off (below) re-checks it holds for an open-weight main model rather
  than assuming it transfers unchecked.

## What was checked and NOT adopted

Per the same report, every other tested harness toggle
(`search_preview_chars`/positional preview, `judge_relevance_tool`,
`commit_release`, wider `retrieval_engine_set`, the closure critic) was
null or negative on standalone rubric (§4.2, `@tab-moves`) — not retested
here, since re-testing a factor with two independent negative results
elsewhere in this repo would not be a slim use of budget.

**LLM-generated search-result snippets/previews (S9's generated level)**
were specifically checked against the repo's own historical evidence before
being ruled out, not skipped by default: `worklogs/2026-08-06-facets-agent-
two-tier-v2-improvements.md`'s best-tuned variant (full-question snippets +
citation re-verification) still leaves citation *support* at roughly half
of the full-staging default (12.5% vs. 23.6% `full_support`) despite a real
59–67% processed-token reduction, and the report's own §4.5 axis breakdown
finds **References & Citation Quality is the weakest rubric axis in every
single cell scored** (mean 0.167/2). Shipping a mechanism with a documented
citation-support regression on top of the one axis every cell already fails
hardest would be working against the report's own strongest finding, not
with it — so open_weight_agent stages full search-result text (`stage_search_results
=True`, no preview cap), like `brief_revise_agent`'s own base cell.

**Correction, found while preparing a follow-up deep-research prompt**:
that "weakest axis" claim is true in aggregate across the report's 30
proprietary-model cells, but open_weight_agent's own per-axis numbers (below)
show the opposite for this system specifically — References & Citation
Quality is open_weight_agent's *best*-scoring axis (0.667/2, beats both
proprietary progenitors), not its worst. The decision not to adopt
snippets still stands (no positive evidence for them either way, and the
regression risk is real on principle), but the stated reason above is
weaker than it looks — the real gap is Implicit Criteria and Synthesis
of Information (see the per-axis table in the worklog and
`worklogs/assets/2026-08-09-oss-agent-deep-research-prompt.md`), and
future work here should prioritize those two, not citation mechanisms.

## Model bake-off (this system's own evidence, not inherited)

Round 1 (three models confirmed usable under this account at the time):
`openai.gpt-oss-120b-1:0`, `qwen.qwen3-next-80b-a3b`,
`moonshot.kimi-k2-thinking`. Round 2 (2026-08-09, after a design review with
gpt-5.6-sol and Gemini Deep Research — `worklogs/assets/2026-08-09-oss-agent-
sol-plan-review.md` — plus a real Bedrock catalog check that found several
more open-weight models already enabled on the account): `zai.glm-5`,
`deepseek.v3.2`, `moonshotai.kimi-k2.5`, `qwen.qwen3-235b-a22b-2507-v1:0`.
All run as the MAIN writer model (brief/review/scout roles held to the same
model — see the run-id table below) on the same 15-topic dev subset the
factor-analysis report itself tuned on
(`worklogs/assets/2026-08-09-oss-agent-exp15-topics.tsv`, the exact 15 qids
of `br-model-main-sol-exp15-b1`), scored with the same standalone-rubric
protocol (`gpt-5.6-terra` judge) so every number is directly comparable.

| Model | Standalone overall (0–3) | Notes |
|---|---:|---|
| `qwen.qwen3-next-80b-a3b` (round-1 winner) | 1.200 | 15/15 clean, `safety_max_rounds=30` |
| `openai.gpt-oss-120b-1:0` | 1.200 | needed `safety_max_rounds=100`; 1 retry for a transient shared-harness `KeyError` |
| `moonshot.kimi-k2-thinking` | 1.071 (14/15) | 1 topic reproducibly failed/hung across three attempts |
| `deepseek.v3.2` | 1.200 | tied round-1 winner; first attempt showed 0.933 due to an AWS-token expiry contaminating 3/15 topics mid-run, corrected by regenerating just those topics |
| `moonshotai.kimi-k2.5` | 1.333 | |
| `qwen.qwen3-235b-a22b-2507-v1:0` | 0.867 | **worse than the smaller round-1 `qwen3-next-80b-a3b`**, confirmed on clean data (same token-expiry contamination as deepseek, same fix) — bigger/newer is not automatically better here |
| `us.meta.llama3-3-70b-instruct-v1:0` | excluded | smoke test: 0 tool calls across 4 rounds under this harness's Converse schema, never recovers — a real reliability failure, not run to completion |
| **`zai.glm-5`** | **1.467** | **winner**, replicated on an independent 15-topic set (below) |

**Winner: `zai.glm-5`**, replicated on the exact independent "new15" topic
set the original factor-analysis report used for its own replication work
(`worklogs/assets/2026-08-09-oss-agent-new15-topics.tsv`): `glm-5` scored
1.333 there against a freshly-run `qwen3-next-80b-a3b` baseline's 0.867 —
Δ=+0.467, LARGER than the exp15 set's own +0.267, the opposite of what a
regression-to-the-mean artifact would look like. `agent.DEFAULT_MODEL` is
now `"zai.glm-5"`.

**A related diagnostic reversed a hypothesis both external reviews were
built on.** Swapping a single support role (blind scout, or the
requirements-brief analyst) from `qwen` to the *proprietary* `gpt-5.6-luna`
— main writer held at `qwen` throughout, diagnostic-only via
`--scout-backend openai`/`--brief-backend openai` (never a deployable
config, see `agent.py::_check_model`'s own docstring) — made the system
WORSE (1.000 and 1.067 vs. 1.200 all-qwen), not better. The earlier
observation that a mixed-proprietary-support-role pipeline scored 0.200
higher than `open_weight_agent`'s own all-open-weight config was comparing two
DIFFERENT systems' architectures, not an isolated role swap; this is the
first clean single-variable test, and it says a support role's output
needs to "speak the same language" as the model consuming it more than it
needs to be individually stronger. Full detail:
`worklogs/2026-08-09-oss-agent-open-weight-system.md`.

## Ablations (qwen, same 15 topics)

| Run-id | Change from default | Standalone overall | Δ vs. default (1.200) |
|---|---|---:|---:|
| `oss-ablate-qwen-noscout-exp15` | `--no-plan-critic` (S14 off) | 1.200 | 0.000 (tie on holistic score) |
| `oss-ablate-qwen-noadj-exp15` | `--disable-adjacent-pages` (S5 off) | 0.800 | **-0.400** |

Two findings:

1. **S14 (blind scout) ties on the holistic `overall` score but moves the
   axis it targets.** `Implicit Criteria` mean (0–2) is 0.694 with the
   scout on vs. 0.571 with it off — the report's own finding that a
   structural factor can help one axis without moving the noisy 0–3
   holistic score much (§4's own axis-breakdown methodology). Kept ON:
   real, axis-specific signal in the intended direction, and the marginal
   cost is one extra cheap-model call per topic.
2. **S5 (adjacent-page augmentation) is decisively confirmed for
   qwen**, and by a much larger margin than the original report's own
   qwen-specific test (-0.400 here vs. -0.133 there — different harness
   config, same direction). Kept ON, not a close call.

See `worklogs/2026-08-09-oss-agent-open-weight-system.md` for the full
run-id/score/cost breakdown, the plan-critic and adjacent-page ablations,
and the reasoning behind the final default config below.

## Default configuration

`zai.glm-5` in all four roles (main, brief, scout, review), `hybrid`-only
retrieval, adjacent-page augmentation on, blind scout on. Standalone rubric
score on the same 15-topic dev subset the factor-analysis report tuned on:
**1.467/3** (`gpt-5.6-terra` judge, same protocol), replicated at 1.333 on
an independent topic set. This does not reach `brief_revise_agent`'s base
cell (2.267) or `aus_agent_v2` (2.267) — generator-model quality was
already this repo's single largest standalone-score factor for proprietary
models (report §4.2/§7, ~10x any structural lever), and that effect
carries over: no combination of structural levers tested here closes the
~0.8-point remaining gap to a `gpt-5.6-*` main model. What this system
demonstrates is the SAME architecture (brief + blind scout + hybrid
retrieval + review/revise) built entirely from open-weight Bedrock models,
at a small fraction of even `brief_revise_agent`'s already-cheap per-topic
cost.

*The S5/S14 ablations above (adjacent-page augmentation, blind scout) were
run and confirmed on `qwen.qwen3-next-80b-a3b`, before the round-2 model
bake-off — not re-confirmed on `glm-5` specifically. Carried over as
defaults on the strength of that evidence, not re-tested; a real gap, not
an oversight.*

## Tier-2 attempts (all rejected — full account in the worklog)

Two design reviews (gpt-5.6-sol, Claude Opus 4.8) converged on two
successive architecture proposals meant to close the remaining gap. Both
were built, piloted on the same 15 topics, and both scored WORSE than
the plain baseline above — see `worklogs/2026-08-09-oss-agent-open-
weight-system.md`'s "Tier-2 build round" section and the full review
transcript in `worklogs/assets/2026-08-09-oss-agent-sol-plan-review.md`
for the complete reasoning chain (including a third, subtractive pilot
that definitively resolved *why*: the existing review pass is
protecting citation quality, not costing it). `--synthesis-compiler`
(`blueprint.py`) and `--review-scout-obligations` remain in the code,
off by default, as two real, documented negative results.

## CLI

```bash
uv run --group open-weight-agent python src/systems/open_weight_agent/run.py --qid <qid>
uv run --group open-weight-agent python src/systems/open_weight_agent/run.py \
    --query "..." --model qwen.qwen3-next-80b-a3b
uv run --group open-weight-agent python src/systems/open_weight_agent/run.py --all
```

`--model`/`--brief-model`/`--review-model`/`--scout-model` each accept only
an `agent.ALLOWED_MODELS` id (argparse `choices=`, so an invalid value
fails at argument-parsing time, before any import-level side effect).
Region is auto-derived per model (`agent.DEFAULT_REGION_BY_MODEL`) unless
overridden — `qwen.*`/`moonshot.*` only serve this account in
`us-east-1`/`us-west-2`.

## Tests

`tests/systems/test_open_weight_agent.py` — offline coverage for the model
allowlist (rejects a disallowed model in any of the four roles before any
provider is built), the scout stage's rendering and end-to-end wiring, and
one `@pytest.mark.live` smoke test against real Bedrock + ClimbMix. Run:

```bash
bash scripts/test.sh tests/systems/test_open_weight_agent.py
```
