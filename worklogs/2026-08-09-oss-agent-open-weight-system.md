# 2026-08-09 — oss_agent: an open-weight-only system, built from the two best-ranked systems' taxonomy

Branch: `oss-agent-open-weight-system`. Budget cap: \$200 (generation +
judging combined), well under it in practice — Bedrock open-weight models
are far cheaper than the OpenAI `gpt-5.6-*` calls the rest of this repo's
factor-analysis work priced (see totals below).

## Starting point

Read `worklogs/assets/2026-08-07-factor-analysis-report/report.typ` in
full. §10.2–10.3 rank every system in this repo on real evidence:
`aus_agent_v2` is the strongest (best arena performer, most expensive,
\$1,096.72 documented build cost, `gpt-5.6-*` throughout) and
`brief_revise_agent`'s base cell ties it exactly on standalone rubric
(2.267/3) at ~1/50th the cost with a much simpler architecture. These are
the two systems this new system is built from — see
`src/systems/oss_agent/README.md` for the full design rationale.

Constraint: **every model role must be open-weight** (no `gpt-5.6-*`, no
proprietary Bedrock model). Confirmed-usable open-weight Bedrock models
under this account (`agent_harness/providers/bedrock.py`'s own docstring):
`openai.gpt-oss-120b-1:0` (ap-southeast-2/us-east-1),
`qwen.qwen3-next-80b-a3b` (us-east-1/us-west-2 only),
`moonshot.kimi-k2-thinking` (us-east-1/us-west-2 only). No Llama, Mistral,
or DeepSeek model ids exist anywhere in this repo's provider code.

## Topics

Reused the EXACT same 15-topic dev subset the factor-analysis report
tuned on (the qids of `br-model-main-sol-exp15-b1`), extracted from
existing `data/outputs/brief_revise_agent/*.output.json` metadata and saved
to `worklogs/assets/2026-08-09-oss-agent-exp15-topics.tsv` — so every score
below is directly comparable to the report's own table, not a fresh,
differently-hard sample. Per user direction: rubric-only (standalone),
no arena — arena judging is 2x the cost for a confirmatory signal the
report itself showed can diverge from standalone (its own `hybrid`-alone
case study, §5.2/§6), which this slim budget does not need to re-litigate.

## System design

`src/systems/oss_agent/` — reuses `brief_revise_agent.brief`/`.review`/
`.adjacent_pages` directly (import, not copy) and adds one new module,
`scout.py`, porting `aus_agent_v2.plan_critic`'s blind obligation-scout
stage unmodified (same prompt, same parser) with only the rendering
adapted to brief_revise_agent's bullet-appendix format. New taxonomy entry
S14 added to `worklogs/assets/2026-08-07-terra-factor-taxonomy-final.md`
for this factor (it predates this session as `aus_agent_v2`'s own
unconditional default, but was never isolated/A-B'd on its own before now).

Model allowlist (`agent.ALLOWED_MODELS`) enforced BEFORE any provider is
constructed, in all four roles (main writer, brief analyst, scout,
reviewer) — see `tests/systems/test_oss_agent.py` for the regression tests
pinning this.

Defaults adopted without re-testing (already confirmed in the report, on
`sol`/`qwen`, not open-weight-model-specific but not worth re-spending
budget to re-confirm a zero/negative-risk default): S5 adjacent-page
augmentation ON, `hybrid`-only retrieval engine (S6).

**Checked against repo history and explicitly NOT adopted**: LLM-generated
search-result snippets (S9's generated preview level). Even the best-tuned
variant in `worklogs/2026-08-06-facets-agent-two-tier-v2-improvements.md`
(full-question snippets + citation re-verification) leaves citation
*support* at roughly half of full-staging's (12.5% vs. 23.6%
`full_support`), and References & Citation Quality is the report's own
single weakest rubric axis across every cell scored (mean 0.167/2, §4.5) —
adopting a mechanism with a documented citation-support regression on top
of the axis every cell already fails hardest would work against the
report's strongest finding, not with it.

## Real bug hit and fixed: ambient `BEDROCK_REGION`

First live smoke run failed with `ValidationException: The provided model
identifier is invalid` for `openai.gpt-oss-120b-1:0` — the exact
known failure mode `facet_rag/run.py`'s own comment names: `.env`'s
`BEDROCK_REGION=ap-southeast-1` is wrong for non-Anthropic Bedrock models,
and `BedrockProvider`'s region resolution prefers an already-set env var
over its own hardcoded default, so passing `region=None` does NOT protect
against a bad ambient value. Fixed by pinning
`DEFAULT_REGION_BY_MODEL["openai.gpt-oss-120b-1:0"] = "ap-southeast-2"`
explicitly (matching `facet_rag/run.py`'s own defensive pattern) instead of
`None`/"inherit ambient".

## Model bake-off

All three models run as the MAIN writer (brief/scout/review roles fixed to
the same model per run -- i.e. every role in one bake-off cell shares the
model under test), same 15 topics, same standalone-rubric protocol
(`gpt-5.6-terra` judge):

| Run-id | Model | Topics completed | Standalone overall (0–3) |
|---|---|---:|---:|
| `oss-bakeoff-qwen-exp15` | `qwen.qwen3-next-80b-a3b` | 15/15 | **1.200** |
| `oss-bakeoff-oss120b-exp15-v2` | `openai.gpt-oss-120b-1:0` | 15/15 | 1.200 |
| `oss-bakeoff-kimi-exp15` | `moonshot.kimi-k2-thinking` | 14/15 | 1.071 |

**Reliability, not just score, decided the winner.** `gpt-oss-120b`'s first
attempt (`oss-bakeoff-oss120b-exp15`, `safety_max_rounds=30`, the CLI
default I initially picked without checking `agent_harness`'s own default
of 100) only completed 3/15 topics cleanly -- 9 hit `budget_exhausted`/
`failed` before producing a valid final report. Relaunched at
`safety_max_rounds=100` (`-v2`), which fixed 14/15, plus one retry for a
transient `KeyError: 'tooluse_...'` at `agent_harness/agent.py:1653`
(`result_by_id[call["id"]]` -- a tool-call id the harness's own result
mapping didn't have; a pre-existing shared-harness edge case, not something
this system's own code triggers, and out of scope to fix here). `qwen`
needed none of this: 15/15 clean on the FIRST attempt at
`safety_max_rounds=30`. `kimi-k2-thinking` hit the same `KeyError` pattern
on its first attempt for one topic (`6847465956a0f6376a6053fb`, "social
media impact" -- also the one gpt-oss-120b's first attempt struggled with
most), and a retry at `safety_max_rounds=60` simply never finished within a
generous wait, nor did a further retry at 40 rounds with a 100s hard
timeout -- scored on its 14 completed topics rather than block on one
topic indefinitely.

**Winner: `qwen.qwen3-next-80b-a3b`** -- ties `gpt-oss-120b` exactly on
score, needed zero round-cap tuning or retries, and (per the original
factor-analysis report's own per-topic cost ordering, §7) is the cheaper
of the two. `kimi-k2-thinking` is both worse-scoring and the least
reliable of the three -- not adopted.

## Ablations (qwen, same 15 topics)

| Run-id | Change | Standalone overall | Δ vs. default (1.200) |
|---|---|---:|---:|
| `oss-ablate-qwen-noscout-exp15` | `--no-plan-critic` (S14 off) | 1.200 | 0.000 |
| `oss-ablate-qwen-noadj-exp15` | `--disable-adjacent-pages` (S5 off) | 0.800 | **-0.400** |

**S14 (blind scout) ties on the holistic score but moves the axis it
targets.** `Implicit Criteria` mean (0-2 per-criterion, not the 0-3
holistic score) is 0.694 scout-on vs. 0.571 scout-off (from the two full
per-axis breakdowns, `evaluation-results/factorial/oss-bakeoff-qwen-exp15/`
vs. `.../oss-ablate-qwen-noscout-exp15/`) -- consistent with the original
report's own finding that a real structural effect can move one axis
without clearing the noisy 0-3 holistic score's threshold (§4's own
axis-breakdown methodology, §4.5's citation-axis finding being the
clearest example of an axis-specific signal the holistic score alone
would miss). Kept ON: real, axis-specific effect in the intended
direction, one cheap extra call per topic.

**S5 (adjacent-page augmentation) is decisively confirmed for qwen**, and
by a substantially larger margin than the original report's own
qwen-specific test on `brief_revise_agent` (-0.400 here vs. -0.133 there --
different harness config and topic-scoring run, same direction, larger
effect). Not a close call; kept ON.

Did not additionally re-test the `hybrid`-only engine choice against the
`semantic,keyword` default for qwen specifically (budget allows it, but
per user direction to keep this slim, and the report's own S6 evidence
already replicated on two independent topic sets for `sol` in the same
direction cost-effectiveness favors) -- flagged here as the one adopted
default that is NOT re-verified against an open-weight model's own data,
unlike S5 and S14 above.

## Final configuration and evidence

`qwen.qwen3-next-80b-a3b` in all four roles (main, brief, scout, reviewer),
`hybrid`-only retrieval, adjacent-page augmentation on, blind scout on.
`agent.DEFAULT_MODEL` set to this after the bake-off (was
`openai.gpt-oss-120b-1:0` during scaffolding/smoke-testing). Standalone
overall on the same 15 topics: **1.200/3**. This does not reach
`brief_revise_agent`'s base cell or `aus_agent_v2` (both 2.267) --
generator-model quality was already the report's single largest
standalone-score factor for proprietary models (~10x any structural
lever, §4.2/§7), and every open-weight model tested here scores well below
every `gpt-5.6-*` model tested there (1.2 vs. 1.87-2.27). No structural
lever tested, ported, or considered in this session closes that gap --
consistent with the report's own reading that once the generator-model
effect dominates, remaining levers move an order of magnitude less
(§4.2). What this session demonstrates is the SAME taxonomy-informed
architecture (pre-flight brief + blind scout + hybrid retrieval +
review/revise), built and validated entirely on open-weight Bedrock
models, at a small fraction of even `brief_revise_agent`'s already-cheap
per-topic generation cost.

**Per-axis breakdown against the two proprietary progenitors** (same 15
topics, same judge, `n` = pooled criterion instances per axis, identical
across all three runs since they share the same topics/rubric file):

| Axis (0-2) | `oss_agent` qwen (n) | sol baseline (n) | `aus_agent_v2` (n) | Gap (sol - qwen) |
|---|---:|---:|---:|---:|
| Communication Quality | 0.633 (30) | 0.733 (30) | 0.833 (30) | +0.100 |
| Explicit Criteria | 1.239 (109) | 1.450 (109) | 1.505 (109) | +0.211 |
| **Implicit Criteria** | 0.694 (170) | 0.988 (170) | 1.100 (170) | **+0.294** |
| Instruction Following | 0.875 (16) | 1.000 (16) | 1.188 (16) | +0.125 |
| **Synthesis of Information** | 0.590 (39) | 0.795 (39) | 1.000 (39) | **+0.205** |
| References & Citation Quality | 0.667 (9) | 0.222 (9) | 0.000 (9) | **-0.444** |

**Correction to the reasoning used earlier in this worklog and in
`src/systems/oss_agent/README.md`** to reject LLM-generated snippets:
that rejection cited the original report's §4.5 finding that References
& Citation Quality is the weakest axis in every cell scored — true in
aggregate across the report's 30 proprietary-model cells, but the table
above shows the opposite for `oss_agent` specifically: Citation Quality
is its *best*-scoring axis (n=9 is small, but a gap this large in the
favorable direction is a real signal), beating both proprietary
baselines outright. The real gap is Implicit Criteria (largest, +0.294)
and Synthesis of Information (+0.205). The decision not to adopt
snippets still stands on other grounds (no positive evidence for them,
and the regression risk documented in the "Historical-evidence check"
section below is real on principle), but the
stated rationale was weaker than written, and any future work on this
system should prioritize Implicit Criteria/Synthesis, not citation
mechanisms. Found while assembling
`worklogs/assets/2026-08-09-oss-agent-deep-research-prompt.md`, which
this table is also reproduced in.

## Cost

Generation (`data/outputs/oss_agent/`, every run this session, real
Bedrock token counts, same placeholder blended rate the original report
used for Bedrock cells, `(0.0001545+0.000618)/2` per 1K tokens):

| Run-id | Tokens | Cost (placeholder rate) |
|---|---:|---:|
| `oss-bakeoff-oss120b-exp15` (flawed, `safety_max_rounds=30`) | 11,174,964 | \$4.32 |
| `oss-bakeoff-oss120b-exp15-v2` | 15,235,076 | \$5.89 |
| `oss-bakeoff-qwen-exp15` | 6,151,576 | \$2.38 |
| `oss-bakeoff-kimi-exp15` | 7,116,284 | \$2.75 |
| `oss-ablate-qwen-noscout-exp15` | 3,429,939 | \$1.33 |
| `oss-ablate-qwen-noadj-exp15` | 3,848,885 | \$1.49 |
| **Generation total** | **46,956,724** | **\$18.14** |

Judging: 74 standalone-rubric judge calls (`gpt-5.6-terra`, one per scored
topic across the 5 scored run-ids: 15+15+14+15+15) at the report's own
\$0.15/call flat placeholder = **\$11.10**.

**Total ≈ \$29.24 of the \$200 cap** -- well under budget even after two
failed attempts (the round-cap miss, the kimi topic that never finished)
and a full bake-off plus two ablations. No design-review calls to
`gpt-5.6-sol`/Opus were spent this session; the taxonomy, architecture, and
evidence already in the report and this repo's history were sufficient to
make every design decision without new advisory API spend.

## Historical-evidence check (per user direction, before finalizing)

Checked the repo's existing experiments for anything else worth adopting,
beyond what the factor-analysis report itself already scored:

- **LLM-generated search-result snippets** (`worklogs/2026-08-06-facets-
  agent-two-tier-v2-improvements.md`) -- even the best-tuned variant
  (full-question snippets + citation re-verification) leaves citation
  *support* at roughly half of full-staging's (12.5% vs. 23.6%
  `full_support`) for a 59-67% processed-token reduction. Not adopted:
  References & Citation Quality is the report's own single weakest rubric
  axis across every cell scored (mean 0.167/2, §4.5) -- a mechanism with a
  documented citation-support regression is the wrong trade for an
  open-weight system that is already starting from a lower generator-model
  ceiling on that exact axis. Documented in `src/systems/oss_agent/
  README.md` rather than silently skipped.
- **`judge_relevance_tool` (S11), `commit_release` (S12), positional
  preview (S9), wider `retrieval_engine_set`** -- all null or negative on
  standalone rubric in the report's own factor sweep (§4.2, `@tab-moves`).
  Not re-tested here: two independent negative/null results (this repo's
  own S11/S12/S9 cells plus the two-tier snippet deep-dive above) is
  sufficient evidence not to re-spend slim budget confirming them a third
  time on a different model family.
- **`aus_agent_v2`'s blind obligation scout (`plan_critic.py`)** -- the one
  mechanism from this check that WAS adopted (S14, above): real in the
  repo's strongest system, never previously isolated/A-B'd on its own
  (it runs unconditionally as part of `aus_agent_v2`'s shipped default),
  and this session's own ablation gives it a first isolated result.

## Taxonomy and report updates

- `worklogs/assets/2026-08-07-terra-factor-taxonomy-final.md` -- added
  **S14 `blind_obligation_scout`**, documenting the mechanism, its origin
  in `aus_agent_v2.plan_critic`, and that this session's own ablation is
  the first isolated A/B result for it anywhere in this repo.
- `worklogs/assets/2026-08-07-factor-analysis-report/report.typ` -- added
  a short addendum section (after the existing Appendix) summarizing this
  system and its evidence, so the report's own system-ranking section
  (§10) has a pointer to the one new system built after it was written.

## What's left open

- `hybrid`-only was not independently re-verified for qwen (see Ablations
  section above) -- adopted on the strength of the original report's
  own two-independent-topic-set replication for `sol`, not re-tested here.
- No arena evaluation was run for `oss_agent` at all, per explicit user
  direction (rubric-only, keep the session slim) -- the same report this
  system is built from (§6) shows standalone and arena can rank
  configurations in opposite orders, so `oss_agent`'s arena performance
  specifically remains unknown, not merely untested by oversight.
- The `agent_harness.agent`-level `KeyError` on certain non-Anthropic tool
  responses (hit for both `gpt-oss-120b` and `kimi-k2-thinking` this
  session) is a real, reproducible-enough shared-code issue worth a
  dedicated look in a future session -- out of scope to fix here since it
  lives in `src/agent_harness/agent.py`, shared by every system in the
  repo, not `oss_agent`'s own code.

## Experimental plan (sol + Gemini Deep Research review, 2026-08-09)

Full review transcripts: `worklogs/assets/2026-08-09-oss-agent-sol-plan-review.md`
(gpt-5.6-sol, a 3-turn working dialogue) and the Gemini Deep Research
response pasted into this session directly (not separately saved as a
file; its content is summarized below and this section is its record).
Every proposal from both is listed here with a source tag, so nothing
raised gets silently dropped. Status is updated as each is run.

**Tier 1 -- cheap, high information value, executed this session:**

| ID | Proposal | Source | Status |
|---|---|---|---|
| T1.1 | Model bake-off: `qwen3-235b-a22b-2507`, `glm-5`, `deepseek.v3.2`, `kimi-k2.5` (real Bedrock catalog, not speculative) | sol + Gemini (convergent) | **running**, see below |
| T1.2 | Model bake-off: Llama 3.3 70B | Gemini | **excluded** -- smoke test showed 0 tool calls across 4 rounds under this harness's Converse tool schema; a real, cheap, decisive negative finding, not pursued to a full 15-topic run |
| T1.3 | D1: fixed-evidence replay (qwen writes from `aus_agent_v2`'s frozen committed evidence, no tool loop) | sol (D1) + Gemini (their #2, "Fixed-Evidence Replay") -- near-identical independent design | **running**, `worklogs/assets/2026-08-09-oss-agent-d1-replay.py` |
| T1.4 | Role-decoupling ablation: scout=proprietary luna, main+brief+review=qwen | sol (D2/A5) + Gemini (their #3) | **running** |
| T1.5 | Role-decoupling ablation: brief=proprietary luna, main+scout+review=qwen | sol (D2/A5) + Gemini (their #3) | **running** |

Implementing T1.1/T1.4/T1.5 required two real shared-harness fixes, kept
because they are generally useful, not just for this session:
`agent_harness.agent.make_provider`/`run_agent` gained an optional
`max_tokens` override (Llama 3.3 70B's Bedrock endpoint hard-caps output
at 8192, vs. `BedrockProvider`'s 16000 default -- a `ValidationException`
otherwise, only forwarded when explicitly set so no other system's tests
or behavior changed); `oss_agent.agent._check_model` now takes an
optional `backend` and only enforces the open-weight allowlist for
`backend="bedrock"` calls, so a support role (never the main writer,
which stays hardcoded to `backend="bedrock"`) can explicitly opt into a
proprietary model via `--brief-backend openai` etc. -- a diagnostic-only
escape hatch, never a deployable path, covered by
`tests/systems/test_oss_agent.py::test_brief_backend_openai_bypasses_the_allowlist_for_that_role_only`.

**Tier 2 -- architecture changes, contingent on Tier 1 results, not yet started:**

| ID | Proposal | Source | Target axis | Notes |
|---|---|---|---|---|
| T2.1 | Criterion-partitioned claim union (3 branches: explicit/implicit/synthesis, deterministic union + editor pass) | sol A3 | Implicit, Synthesis | Realizes the oracle union headroom (§3 of the report) via deliberate partition-based diversity, not resampling -- direct answer to the failed best-of-4 |
| T2.2 | Delta-planned two-draft union (Draft A = explicit, Draft B = gap-conditioned on A's own text, then a merge/synthesizer pass) | Gemini | Synthesis, Implicit | Same failed-best-of-4 answer as T2.1, different partition axis (sequential delta vs. parallel role split) -- worth comparing both, not just picking one on priors |
| T2.3 | Evidence-grounded synthesis compiler (structured report blueprint before prose) | sol A1 | Synthesis | |
| T2.4 | Deterministic obligation reconciliation (mechanically union brief+scout output instead of appending two advisory texts) | sol A2 | Implicit | Cheap -- no extra calls if brief/scout output is already structured |
| T2.5 | Two-stage targeted revision (coverage pass, then synthesis pass, orthogonal jobs) | sol A4 | Implicit, Synthesis | |
| T2.6 | Cross-agent critique/revision loop (separate Critic call, restricted from rewriting; separate Editor call, restricted from new search) | Gemini | Synthesis, Implicit | Structurally similar to T2.5, different framing (critic/editor split vs. coverage/synthesis split) |
| T2.7 | Targeted Boolean retrieval policy (`hybrid` default + `lucene_bool`/`ssr` for named-entity/exact-phrase obligations, with a deterministic query sanitizer + hybrid fallback on empty/malformed results) | sol R1 + Gemini ("Boolean-to-Hybrid Syntax Fallback") -- convergent | Implicit | |
| T2.8 | Query compiler (structured search intent -> mechanical Boolean syntax, separating semantic planning from brittle syntax) | sol R2 | Implicit (via retrieval) | Conditional on T1.3/D3-style evidence that qwen's own query-writing, not engine choice, is the bottleneck |
| T2.9 | Open-weight discriminative reranker (small classifier model scores query-doc pairs before staging) | sol R3 + Gemini ("Open-Weight Discriminative Pointwise Reranking") -- convergent | Synthesis (via noise reduction) | Needs a small extra open-weight model hosted for the reranker role specifically -- not yet in `ALLOWED_MODELS` since it is not a text-generation role |
| T2.10 | Hierarchical locate-then-read spatial augmentation (replace blind adjacent-page fetch with an embedding-similarity gate) | Gemini ("VecTree-RAG"-inspired) | Synthesis | Zero extra LLM calls (mechanical similarity check) -- but S5's own -0.400 ablation effect (this session) means ANY change to adjacent-page behavior needs care; don't ship without re-confirming S5's effect survives the gating |
| T2.11 | D3: query transplant + retrieval-behavior instrumentation (log queries/engine/empty-rate/Recall@k, swap in a strong system's own queries) | sol D3 + Gemini ("Target-State Query Audit", "Retrieval behavior instrumentation") -- convergent | diagnostic | Zero/near-zero cost (log analysis); should run before T2.7-T2.9, not after |
| T2.12 | Heterogeneous open-weight role routing (best-performing model per role, not one model everywhere) | sol (4.2) + Gemini ("Heterogeneous Open-Weight Pipeline") | Implicit | Contingent on T1.4/T1.5 identifying which role actually drives the -0.200 gap |

**Explicitly not funded, either source:** blanket round-cap increases or
more same-config resampling ("Blanket extra rounds/same-config
ensembles" -- sol explicitly lists this as a do-not-fund item; both
advisors agree the failed best-of-4 already answers this).

**Claims from Gemini's response treated as unverified pending independent
check, not taken at face value**: specific named methods ("GDP-RAG",
"Caesar", "VecTree-RAG") and specific benchmark figures (DeepSeek-V3.2's
"68.4% on SWE-bench", "$0.14/1M input", a 7-47% tool-calling completion
range attributed to "Live API Bench") -- none could be confirmed real
from this session's own knowledge, and the request explicitly asked for
literature-backed claims to be labeled as such, which they were not. The
underlying MECHANISMS (T2.1/T2.2/T2.9/T2.10) are evaluated on their own
structural merits regardless of whether the cited names are real.

## Tier-1 results: model bake-off, D1 replay, role-decoupling (2026-08-09)

### Extended model bake-off

All 6 confirmed-real open-weight Bedrock models run as the full
architecture's main writer (brief/scout/review = same model), same
15-topic exp15 set, same judge protocol:

| Model | Standalone overall | vs. old default (1.200) |
|---|---:|---:|
| `qwen.qwen3-next-80b-a3b` (old default) | 1.200 | -- |
| `openai.gpt-oss-120b-1:0` | 1.200 | 0.000 |
| `deepseek.v3.2` | 1.200 | 0.000 |
| `moonshot.kimi-k2-thinking` | 1.071 (14/15) | -0.129 |
| `moonshotai.kimi-k2.5` | 1.333 | +0.133 |
| `qwen.qwen3-235b-a22b-2507-v1:0` | **0.867** | **-0.333** |
| **`zai.glm-5`** | **1.467** | **+0.267** |

**`qwen3-235b-a22b-2507` -- a much larger, newer Qwen -- scores WORSE
than the smaller `qwen3-next-80b-a3b` it was meant to supersede**,
confirmed on real data: its first attempt (0.467) was contaminated by an
AWS session-token expiry mid-run (6/15 topics got a degenerate
`ExpiredTokenException` fallback answer, `ExpiredTokenException` also
hit 3/15 of `deepseek.v3.2`'s topics, `0.933` there before the fix);
after refreshing credentials and regenerating exactly the affected
topics (`--skip-existing`, so the 9 already-clean topics were reused,
not regenerated), the clean numbers above are real: `qwen3-235b` still
loses to the small model (0.867 < 1.200) and `deepseek.v3.2` recovers to
an exact tie (1.200). Bigger/newer is not automatically better for this
harness and this task -- a real, useful negative result, not an
artifact.

`llama3-3-70b` was smoke-tested and excluded before a full run: 0 tool
calls across 4 rounds (tries to answer from prior knowledge immediately,
gets bounced twice for citing nothing, never recovers) -- a genuine
tool-calling reliability failure under this harness's native Bedrock
Converse schema, not the brittleness Gemini predicted for a *different*
model (DeepSeek). Real per-model reliability varies in ways neither
advisor's priors fully predicted.

### GLM-5 replicated on an independent topic set -- adopted as the new default

Per both advisors' own adoption standard (never promote on one positive
signal), reran `glm-5` AND a fresh `qwen3-next-80b-a3b` baseline on the
exact independent "new15" 15-topic set the original factor-analysis
report itself used for its own hybrid-engine replication
(`br-replicate-sol-new15`'s own qids, extracted from that run's existing
artifacts -- `worklogs/assets/2026-08-09-oss-agent-new15-topics.tsv`):

| Model | exp15 (tuning set) | new15 (independent set) |
|---|---:|---:|
| `qwen.qwen3-next-80b-a3b` | 1.200 | 0.867 |
| `zai.glm-5` | 1.467 | 1.333 |
| **Δ (glm-5 - qwen)** | **+0.267** | **+0.467** |

Confirmed, and by a LARGER margin on the fresh topics, not a smaller
one -- the opposite of what a regression-to-the-mean artifact would
look like. `agent.DEFAULT_MODEL` changed to `"zai.glm-5"`
(`src/systems/oss_agent/agent.py`); every role now defaults to GLM-5,
matching how the bake-off itself was structured (one model in every
role per cell).

### D1: fixed-evidence replay

`worklogs/assets/2026-08-09-oss-agent-d1-replay.py`, qwen writing with
NO tool loop from a frozen evidence package, same 15 topics:

| Cell | Standalone overall | Implicit Criteria (0-2) | Synthesis (0-2) |
|---|---:|---:|---:|
| E-Q (qwen's own live-committed evidence) | 1.200 | 0.612 | 0.564 |
| E-P (`aus_agent_v2`'s committed evidence) | 1.267 | 0.618 | 0.718 |
| Δ | +0.067 (at the noise floor) | +0.006 | **+0.154** |

Three findings, read against sol's own predeclared interpretation
framework (§ above, "Diagnostic D1"):

1. **The replay-validity control passes cleanly**: E-Q's score (1.200)
   exactly matches qwen's real live run on the same topics -- the replay
   harness itself introduces no measurable bias, so the E-P comparison
   is trustworthy.
2. **Synthesis is evidence-sensitive** (+0.154, clears sol's own +0.15
   threshold for "qwen's synthesis is evidence-sensitive; its live
   evidence is too incomplete or noisy") -- **Implicit Criteria is NOT**
   (+0.006, nowhere close). This is the opposite of what a naive reading
   of the -0.294 Implicit Criteria gap (README's own baseline-gap table)
   would suggest: the Implicit Criteria shortfall is NOT primarily a
   retrieval/curation problem solvable by fetching better evidence --
   qwen already has committed evidence roughly as useful as
   `aus_agent_v2`'s own for that axis specifically, and still doesn't
   turn it into implicit-obligation coverage. This points Tier-2 work
   toward T2.1/T2.2/T2.4 (obligation-plan/synthesis architecture) over
   T2.7-T2.9 (retrieval changes) for closing THAT specific axis.
3. **Even with `aus_agent_v2`'s own evidence, qwen still trails
   `aus_agent_v2`'s own live score by a full point** (1.267 vs. 2.267)
   -- confirms a real writer-capability ceiling exists independent of
   evidence quality, consistent with both advisors' priority ranking
   ("model replacement is the higher-expected-value lever").

### Role-decoupling: the opposite of what both advisors expected

Two cells, main=qwen throughout, ONE support role swapped to
proprietary `gpt-5.6-luna` (diagnostic only, `--brief-backend openai`/
`--scout-backend openai`, never submission-eligible -- see
`agent.py::_check_model`'s own docstring):

| Cell | Standalone overall | Δ vs. all-qwen (1.200) |
|---|---:|---:|
| scout = luna, brief/review = qwen | 1.000 | **-0.200** |
| brief = luna, scout/review = qwen | 1.067 | **-0.133** |

**Swapping in a stronger proprietary model for a support role made the
system WORSE, not better** -- the reverse of the hypothesis both sol and
Gemini built their role-decoupling proposals on (that the earlier
observed -0.200 gap, from comparing `oss_agent`'s all-qwen config
against a *different* system's mixed proprietary-support-role config,
reflected support-role capability specifically). This clean, single-
variable-swap experiment says otherwise: a proprietary brief/scout
writing in its own idiom for a much weaker main writer to act on is a
worse fit than a same-family brief/scout that at least "speaks the same
language" as the writer consuming it. **The original -0.200 estimate
was confounded** -- it compared two different systems'
architectures (this system's own scout stage, `hybrid`-only engine,
etc. vs. `brief_revise_agent`'s), not an isolated role-model swap; this
experiment is the first clean one, and it reverses the conclusion.
`T2.12` (heterogeneous role routing) is downgraded from "promising,
pending localization" to "not supported by the one clean test run so
far" -- worth one more data point (a role swap using an open-weight
model stronger than qwen, e.g. `glm-5` scout with a `qwen` main, not a
proprietary model) before ruling it out entirely, but the proprietary-
swap direction specifically is now evidence-contradicted, not just
untested.

### Cost of this Tier-1 batch

~$41.5 generation (all Bedrock, this session's `oss_agent` runs
combined) + ~$29 judging (194 judge calls, `gpt-5.6-terra`) = **~$70.5**
for the full Tier-1 batch (model bake-off + replication + D1 + role-
decoupling), against the original build's ~$29 and the sol dialogue's
~$0.45 -- **~$100 of the $300 cap** through this point.

## Tier-2 build round: three pilots, all negative, plain baseline confirmed best

Full sol + Claude Opus 4.8 (standing in for Fable, blocked by an
RMIT AWS Organizations SCP -- confirmed unfixable from this account, see
`worklogs/assets/2026-08-09-oss-agent-sol-plan-review.md`'s own
continuation) review transcript in that same file, turns 4-7. Summary
here; that file has the full reasoning chain.

Both reviewers converged on building the **evidence-grounded synthesis
compiler** first (`src/systems/oss_agent/blueprint.py`,
`--synthesis-compiler`) -- a fresh isolated call produces a validated
report blueprint (sections, word budgets, obligation coverage,
evidence-backed claims) before the final prose pass, replacing
`review.hook` as the `pre_final_hook` rather than stacking with it (the
harness fires `pre_final_hook` at most once). Two real implementation
bugs were caught by testing before any pilot spend (a `.format()` break
on the JSON schema example's own literal braces; glm-5 collapsing every
section into one giant paragraph despite an explicit per-sentence rule,
fixed with a worked example built from the model's own claims).

**Pilot 1 (`--synthesis-compiler`, 15 topics): clean, decisive NEGATIVE.**
0.933 vs. 1.467 baseline (-0.534). Both target axes moved the WRONG way
(Implicit Criteria -0.130, Synthesis -0.154), plus Communication Quality
(-0.266) and Citation Quality (-0.445) collapsed.

Both reviewers independently converged again on the same read: the
failure signature (whole-answer collapse, not just missed coverage)
means ANY mechanism that REPLACES the model's own organic synthesis
loses on this model+harness combination -- including the alternative
mechanism (a criterion-partitioned claim union) neither reviewer now
recommends building either, since it shares the same "external step
supplants the writer's own judgment" pattern, just with the fragmentation
dial turned up further. The only pattern either reviewer still trusts:
additive correction layered ON TOP of the model's own organic draft --
what the blind scout (S14) already does successfully.

**Pilot 2 (`--review-scout-obligations`, 15 topics): mixed, net
NEGATIVE.** Widened `review.hook`'s own requirement list to also grade
the scout's additions (reusing the mechanism completely unmodified, the
lowest-risk possible additive follow-up). 1.267 vs. 1.467 baseline
(-0.200). Synthesis improved (+0.205, clears the +0.13 adoption gate) but
Implicit Criteria -- the axis this specifically targeted -- moved the
WRONG way (-0.165), and Citation Quality collapsed again (-0.334) --
the same recurring casualty as pilot 1, this time from a much narrower,
purely additive change.

Both reviewers caught the same real gap in the running interpretation:
every comparison so far measured against a "baseline" that already
carries the always-on `review.hook` pass (S4), never itself ablated
against glm-5 -- so "additional revision hurts glm-5" was a hypothesis
consistent with the evidence, not yet actually isolated from "revision
in general hurts glm-5."

**Pilot 3 (`--no-review`, 15 topics, the subtractive diagnostic both
reviewers asked for): definitive.** Citation Quality does NOT rise with
no review pass at all -- it collapses to **0.000** (vs. 0.556 baseline),
the worst citation result of any variant tested this round. Implicit
Criteria, Explicit Criteria, and Communication Quality are all unchanged
(the always-on brief-only review apparently never touches them either
way); Instruction Following improves (+0.188); Synthesis and overall
both drop (0.564 vs 0.667, 1.267 vs 1.467).

**This resolves the whole round's central question, in the direction
that ships with confidence rather than by default:** the always-on
review pass is PROTECTING citation quality, not costing it. Today's two
additive Tier-2 attempts did not fail because "revision hurts glm-5" in
general -- the review pass's own narrow, unmodified scope (brief
requirements only) is doing real, necessary, measurable work; widening
it (pilot 2) or replacing the whole final-writing step around it
(pilot 1) is what failed, for reasons this round's evidence narrows down
to but does not fully explain.

### Final verdict

**Ship the plain baseline** -- `zai.glm-5` in every role, `hybrid`-only
retrieval, adjacent-page augmentation on, blind scout on, unmodified
`review.hook` grading brief requirements only. Standalone overall:
**1.467/3**, exactly the number the model bake-off already established --
this whole Tier-2 round did not find an improvement, but it DID produce
three real, decisive, well-documented negative results plus one clean
positive-control confirmation (the review pass earns its keep), which is
itself the deliverable: `synthesis_compiler` and
`review_scout_obligations` stay in the codebase, off by default, as
validated negative findings rather than deleted code, per this project's
own convention (S12/S4-closure-critic/etc. in the original factor-
analysis report use the same pattern).

### Cost, full session total

Tier-2 round: three 15-topic generation+judging pilots (~$15-20 each,
same per-pilot cost structure as every other cell in this project) plus
consultation (sol cumulative $0.7902 across 7 turns; Opus's real cost is
not reliably logged due to a placeholder-rate bug in the throwaway
driver script, cosmetic only, roughly the same order of magnitude as
sol's given comparable prompt/response sizes) -- approximately $50-65
for the full three-pilot round.

**Full session total: original build (~$29) + sol design-prompt review
(~$0.45) + Tier-1 bake-off/D1/role-decoupling (~$70.5) + Tier-2 three-
pilot round (~$50-65) ≈ $150-165 of the $300 cap.**
