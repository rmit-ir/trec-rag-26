## Corrections to the draft

Key changes from the draft:

- **Removed `system_prompt_variant` as an available `brief_revise_agent` factor.** The five variants exist in `aus_agent`, but the supplied material does not establish corresponding selectable variants in `brief_revise_agent`; its prompt is documented as a byte-copy of the AUS default plus a static review-pass addition. Treating the AUS variants as current brief-agent levels would overstate availability.
- **Added the reverted requirement-labelled retrieval screener.** It was real implemented code in git history and was measured, so it belongs in the taxonomy even though it is not currently available without restoration.
- **Corrected several “already tested” claims.** A worklog filename alone does not establish a reported result. Where the survey only establishes implementation, sibling-system use, or offline tests, that is stated rather than claiming an A/B quality result.
- **Corrected `judge_relevance_tool` mechanism type to `SCHEMA`.** Its enabling mechanism is advertising an additional tool-call schema; its execution does create a side conversation, but the factor itself is tool exposure.
- **Corrected preview levels.** The only concrete character limit supplied is `20,480`; the levels are therefore full staging versus positional/generated previews with that documented cap, rather than invented alternative numeric caps.
- **Clarified model-role coupling.** Current `brief_revise_agent` creates its main-loop provider, brief analyst, and reviewer from the same backend/model factory. Independent role assignment is a meaningful architectural factor but is not currently exposed by the CLI.

---

# 1. Structural / architectural factors

## S1. `requirements_brief`

- **Definition:** Enables a pre-flight, tool-less LLM call that extracts explicit and inferred requirements from the request. Its parsed checklist is rendered as a per-topic appendix to the main research agent’s system prompt.
- **Levels:**
  - **Off** — bypass `brief.get_requirements`; no Appendix A is appended.
  - **On** — run the analyst and append the validated requirements brief; this is the current behavior.
- **Source:** `src/systems/brief_revise_agent/README.md`; `brief.py`; `prompts.py`; session additions.
- **Already tested?** **Yes, implementation/pilot use.** The session notes say it was on for every brief-revise run in this session. The supplied survey does not provide a clean brief-only score.
- **Mechanism type:** **PROMPT**

## S2. `requirements_brief_schema`

- **Definition:** Selects the JSON/output contract used for the requirements brief, including the permitted number and kind of inferred requirements.
- **Levels:**
  - **`v1` / current:** at most 8 entries; at most 4 `implicit` entries; implicit entries require a lexical/request-quotation anti-hunch check.
  - **`v2` / atomic-expert-completion:** 14 entries; up to 6 expert-completion entries; no lexical anti-hunch check.
- **Source:** `brief.py`; session additions; `worklogs/2026-08-07-brief-revise-agent-phase5-dev30-and-decision.md`; `worklogs/2026-08-07-brief-revise-agent-sol-improvement-analysis.md`.
- **Already tested?** **Yes.** The session material explicitly says v2 **regressed versus v1**; v1 is current. No numerical delta is supplied.
- **Mechanism type:** **SCHEMA**

## S3. `brief_word_budget`

- **Definition:** Controls whether the brief requests a validated overall target answer length and per-requirement word allocations. Invalid or absent values fail open to no budget guidance.
- **Levels:**
  - **Off / no budget guidance** — brief contains requirements only.
  - **On / round-C budget guidance** — asks for `target_total_words` in the documented 500–1000 range plus `target_words` per requirement.
- **Source:** `brief.py`; session additions; `worklogs/2026-08-07-brief-revise-agent-phase5-dev30-and-decision.md`.
- **Already tested?** **Implementation exists, but no isolated quality result is supplied.** It is described as current HEAD “round C”; the survey does not state a measured score or verdict for this factor.
- **Mechanism type:** **PROMPT**

## S4. `review_revise_pass`

- **Definition:** Enables the one-shot `pre_final_hook` after the main loop produces an otherwise-valid report. It scans for uncited sentences, evaluates brief requirements, obtains grounded reviewer feedback, and gives the main agent at most one revision turn.
- **Levels:**
  - **Off** — pass `pre_final_hook=None`.
  - **On** — use the brief-revise review hook; current default behavior.
- **Source:** `src/systems/brief_revise_agent/README.md`; `review.py`; `src/agent_harness/agent.py`; session additions.
- **Already tested?** **Yes, offline behavior tests and pilot use.** Tests cover uncited-sentence detection, malformed/raising reviewer fail-open behavior, and disabling via `None`. No standalone quality score for review-on versus review-off is supplied.
- **Mechanism type:** **CONTROL_FLOW**

## S5. `adjacent_page_augmentation`

- **Definition:** Controls whether each search batch is augmented with the immediately preceding and following pages around the top five paginated hits before staging. It requires no additional LLM call.
- **Levels:**
  - **Off** — ordinary search results only; exposed by `--disable-adjacent-pages`.
  - **On** — fetch ±1 page around the top 5 paginated hits; current default.
- **Source:** `adjacent_pages.py`; `search_result_augment` in `src/agent_harness/agent.py`; session additions.
- **Already tested?** **Yes, as brief-revise “round B.”** The supplied material confirms the implementation and CLI toggle but gives no score or outcome verdict.
- **Mechanism type:** **RETRIEVAL**

## S6. `retrieval_engine_set`

- **Definition:** Selects which retrieval engines are advertised to and usable by the main research loop.
- **Levels:**
  - **`semantic,keyword`** — current `brief_revise_agent` / `aus_agent` default.
  - **`semantic,keyword,hybrid`** — documented `facets_agent` default.
  - **`ssr`** — documented shared-harness isolated-engine configuration.
  - **`semantic,keyword,hybrid,ssr,lucene_bool`** — the five engines documented for `facet_rag`; applicability depends on the installed/search-supported configuration.
- **Source:** `src/systems/brief_revise_agent/README.md`; `src/agent_harness/agent.py`; `src/systems/facets_agent/README.md`; `src/systems/facet_rag/README.md`.
- **Already tested?** **Yes, repository-wide.** The survey lists engine-comparison, SSR, keyword, and hybrid worklogs, including `2026-07-21-boolean-vs-keyword-rmit-ir-roster.md`, `2026-07-22-ssr-optimization-and-engine-comparison.md`, and `2026-07-29-test119-semantic-vs-keyword-runs.md`. The supplied excerpts do not state a consolidated brief-revise result.
- **Mechanism type:** **RETRIEVAL**

## S7. `search_k`

- **Definition:** Controls the number of hits requested from a search backend when the model does not explicitly supply `k`.
- **Levels:**
  - **10** — `run_agent` default and documented brief-revise/AUS usage.
  - **15** — `facets_agent`’s documented default for omitted-`k` hybrid calls.
  - **20** — `aus_agent_v2`’s documented number of ranked units returned per search.
- **Source:** `src/agent_harness/agent.py`; `src/systems/brief_revise_agent/README.md`; `src/systems/facets_agent/README.md`; `src/systems/aus_agent_v2/README.md`.
- **Already tested?** **Used in real sibling systems, but no isolated brief-revise `k` comparison is supplied.**
- **Mechanism type:** **RETRIEVAL**

## S8. `search_result_filter`

- **Definition:** Enables a post-search, pre-staging relevance pass. The shared harness invokes it after successful search calls; it may narrow or reorder the returned evidence while preserving validation that it cannot fabricate documents.
- **Levels:**
  - **Off** — current `brief_revise_agent` behavior.
  - **`minimize_filter`** — retain only documents judged `relevant`, while keeping unjudged documents fail-open.
  - **`rank_filter`** — retain all documents but order and annotate them as `relevant`, `adjacent_not_relevant`, and `irrelevant`.
- **Source:** `src/agent_harness/agent.py`; `src/systems/facets_agent/filtering.py`; `worklogs/2026-08-06-facets-agent-phase4cd-ab-and-two-tier.md`.
- **Already tested?** **Implemented and intended for an A/B test in `facets_agent`; no result is supplied for these two exact variants.** The filtering source says the A/B result was pending, not that it was inconclusive.
- **Mechanism type:** **RETRIEVAL**
- **Availability note:** This is a generic shared-harness capability and is **currently unused by `brief_revise_agent`**.

## S9. `search_preview_policy`

- **Definition:** Controls whether normal search hits are staged as ordinary result text, positional previews, or query-relevant generated snippets. In preview modes, `get_documents` remains the deliberate full-document read route.
- **Levels:**
  - **Full staging / no preview** — current behavior.
  - **Positional preview, capped at 20,480 characters** — truncates each search result to the documented harness cap.
  - **Generated query-relevant preview, capped at 20,480 characters** — invokes `search_preview_generator`; the same cap is a safety limit.
- **Source:** `src/agent_harness/agent.py`; `src/systems/aus_agent/README.md`; `worklogs/2026-08-06-facets-agent-two-tier-snippet-diagnosis.md`; `worklogs/2026-08-06-facets-agent-two-tier-v2-improvements.md`.
- **Already tested?** **Yes, in `facets_agent` Phase 4d/two-tier work.** The session summary calls the result **inconclusive**. No different preview character caps are stated in the supplied material.
- **Mechanism type:** **RETRIEVAL**
- **Availability note:** Generic shared-harness capability; **currently unused by `brief_revise_agent`**.

## S10. `stage_search_results`

- **Definition:** Controls whether ordinary `search` results are inserted into the staged-context ledger. With staging disabled, `get_documents` remains available for explicit full-text reading.
- **Levels:**
  - **On** — normal staged/committed protocol; current behavior.
  - **Off** — searches return results without staging them.
- **Source:** `src/agent_harness/agent.py`.
- **Already tested?** **No reported live quality measurement in the supplied material.**
- **Mechanism type:** **RETRIEVAL**
- **Availability note:** Generic shared-harness capability; **currently unused by `brief_revise_agent`**.

## S11. `judge_relevance_tool`

- **Definition:** Controls whether a fourth tool, `judge_relevance`, is advertised to the main model. When called, it opens a separate single-turn model conversation to assess whether evidence supports a named requirement rather than merely being topically adjacent.
- **Levels:**
  - **Off** — current behavior.
  - **On** — advertise and dispatch `judge_relevance`.
- **Source:** `src/agent_harness/agent.py`; session additions; `worklogs/2026-08-06-facets-agent-phase4b-judge-relevance-tool.md`.
- **Already tested?** **Implemented and tested in sibling-system work, but no quality result for brief-revise enablement is supplied.**
- **Mechanism type:** **SCHEMA**
- **Availability note:** Generic shared-harness capability; **currently unused by `brief_revise_agent`**.

## S12. `commit_release`

- **Definition:** Controls whether `commit_context` advertises a `release` field, allowing the agent to retroactively remove an earlier committed document when a better source supersedes it. The harness recomputes that earlier tool-result compaction so the released document’s text leaves the provider history.
- **Levels:**
  - **Off** — ordinary monotonic evidence commitment; current brief-revise behavior.
  - **On** — expose `release` in a system-specific `commit_context` schema.
- **Source:** `src/systems/facets_agent/README.md`; `agent_harness.context.ContextLedger.release_committed`; `agent_harness.tools.commit_context`; `src/agent_harness/agent.py`.
- **Already tested?** **Yes, functionally in `facets_agent` tests.** The tests verify commit → supersede → release and that superseded text is removed from history. The survey also says `release_committed` was never invoked in 15 real runs, so no live quality result is reported.
- **Mechanism type:** **SCHEMA**
- **Availability note:** Generic shared-harness capability; **currently unused by `brief_revise_agent`**.

## S13. `requirement_labelled_retrieval_screener` — historical/reverted

- **Definition:** A historical brief-revise retrieval mechanism that made `requirement` mandatory on each search call and sent results through a one-shot document screener assigning `DIRECT`, `LEAD`, or `OFF_TOPIC`. It used a retention floor of `min(n, max(4, ceil(n/2)))`.
- **Levels:**
  - **Off** — current working-tree behavior.
  - **On / historical screener** — mandatory requirement-labelled search plus relevance screening and retention floor.
- **Source:** session additions; historical `retrieval_filter.py` at git commit `61c13c0`; `worklogs/2026-08-06-brief-revise-agent-phase4cd-ab-and-two-tier.md`.
- **Already tested?** **Yes.** It was measured as worse than baseline: **13 clean losses versus 10** and was therefore reverted/deleted from the working tree.
- **Mechanism type:** **RETRIEVAL**
- **Availability note:** This is a real prior mechanism, but **not currently available without restoring historical code**.

## S14. `blind_obligation_scout` — added 2026-08-09, ported from `aus_agent_v2`

- **Definition:** A second, independent pre-flight LLM call, blind to the requirements brief's own output (sees only the original request): recalls up to 8 additional atomic checks a demanding reader would expect, rendered as extra bullet entries appended after the brief's own appendix. This is not a new mechanism invented for the taxonomy — it is `aus_agent_v2`'s own `plan_critic.py` (`PLAN_CRITIC_SYSTEM`, `plan_critic_request`, `normalize_plan_critique`), reused directly rather than re-derived, with only the rendering adapted to `brief_revise_agent`'s bullet-appendix format instead of `aus_agent_v2`'s numbered-plan format. S1 (`requirements_brief`) is a single analyst call; S14 is a second, independently-recalled one layered on top of it, closer in spirit to `aus_agent_v2`'s own two-stage coverage-plan-then-critic design than to brief_revise_agent's original single-brief design.
- **Levels:**
  - **Off** — brief-only appendix, current `brief_revise_agent`/pre-S14 behavior.
  - **On** — brief appendix plus up to 8 scout-recalled additions.
- **Source:** `systems/aus_agent_v2/plan_critic.py` (original mechanism, this repo's best arena performer per §10.2/§10.3 of this report); `systems/oss_agent/scout.py` (the port, reusing the original prompt/parser unmodified); `worklogs/2026-08-09-oss-agent-open-weight-system.md`.
- **Already tested?** As part of `aus_agent_v2`'s own promoted default pipeline, `plan_critic` runs unconditionally (`plan_critic=True` is the shipped default, not a toggle this repo's factor sweeps ever isolated) — so no prior A/B result for the scout stage ALONE exists anywhere in this repo before `oss_agent`'s own bake-off (see the report body for that result, run against open-weight models specifically, not against the `gpt-5.6-*` models the original mechanism was designed for).
- **Mechanism type:** **PROMPT**
- **Availability note:** Available in both `aus_agent_v2` (unconditional) and `oss_agent` (toggleable via `--no-plan-critic`, open-weight models only).

---

# 2. Model-choice factors

The confirmed usable IDs in the supplied survey are:

- Azure/OpenAI backend:
  - `gpt-5.6-luna`
  - `gpt-5.6-terra`
  - `gpt-5.6-sol`
- Bedrock backend:
  - `openai.gpt-oss-120b-1:0`
  - `qwen.qwen3-next-80b-a3b`

For Qwen, the survey specifically notes `us-east-1` or `us-west-2`, rather than the default Bedrock region.

## M1. `main_research_writer_model`

- **Definition:** Selects the model that runs the continuous research/writing loop: decomposition, search calls, context commitments, gap-follow-up, and final cited report.
- **Levels:**
  - `gpt-5.6-luna`
  - `gpt-5.6-terra`
  - `gpt-5.6-sol`
  - `openai.gpt-oss-120b-1:0`
  - `qwen.qwen3-next-80b-a3b`
- **Source:** session confirmed-model list; `src/systems/brief_revise_agent/README.md`; `src/systems/facet_rag/README.md`; `agent_harness` provider architecture.
- **Already tested?** **Yes, models are used across repository systems, but no controlled brief-revise five-model comparison is supplied.** The survey identifies Luna as this session’s generator and Sol as a reasoning/design model; it does not provide a clean main-model factorial result.
- **Mechanism type:** **MODEL**

## M2. `requirements_brief_analyst_model`

- **Definition:** Selects the model that produces the pre-flight requirements brief and optional word-budget guidance.
- **Levels:**
  - `gpt-5.6-luna`
  - `gpt-5.6-terra`
  - `gpt-5.6-sol`
  - `openai.gpt-oss-120b-1:0`
  - `qwen.qwen3-next-80b-a3b`
- **Source:** `src/systems/brief_revise_agent/README.md`; `brief.py`; session confirmed-model list.
- **Already tested?** **No controlled analyst-model comparison is supplied.** The current implementation uses the same backend/model factory as the main run, so analyst choice is currently coupled to main-model choice.
- **Mechanism type:** **MODEL**

## M3. `reviewer_model`

- **Definition:** Selects the model that assesses the candidate answer against the brief and evidence inventory and emits bounded PATCH/substitution feedback for the one permitted revision.
- **Levels:**
  - `gpt-5.6-luna`
  - `gpt-5.6-terra`
  - `gpt-5.6-sol`
  - `openai.gpt-oss-120b-1:0`
  - `qwen.qwen3-next-80b-a3b`
- **Source:** `src/systems/brief_revise_agent/README.md`; `review.py`; session confirmed-model list.
- **Already tested?** **No controlled reviewer-model comparison is supplied.** The review behavior itself is tested, but the survey does not report a model-by-model reviewer comparison.
- **Mechanism type:** **MODEL**

### Model-coupling note

Current `brief_revise_agent` constructs the main agent, brief analyst, and reviewer from the **same backend/model factory**. Therefore:

- the three roles are architecturally distinct;
- independent role assignment would require configuration/code support;
- the three-factor model cross is a valid taxonomy-level possibility, but not a current CLI-level full cross.

---

# Rough naive full-factorial scale

Using the 13 structural factors above:

| Factor | Levels |
|---|---:|
| Requirements brief | 2 |
| Brief schema | 2 |
| Brief word budget | 2 |
| Review/revise pass | 2 |
| Adjacent-page augmentation | 2 |
| Retrieval engine set | 4 |
| Search `k` | 3 |
| Search-result filter | 3 |
| Search preview policy | 3 |
| Stage search results | 2 |
| Judge-relevance tool | 2 |
| Commit release | 2 |
| Historical requirement-labelled screener | 2 |

Structural cells:

\[
2^9 \times 4 \times 3^3 = 55{,}296
\]

Model-role cells:

\[
5^3 = 125
\]

Naive full cross:

\[
55{,}296 \times 125 = \mathbf{6{,}912{,}000\ cells}
\]

This is deliberately an upper-bound bookkeeping count, not a recommended experiment. It includes incompatible or currently unavailable combinations, including:

- brief schema or word-budget settings while the brief is disabled;
- review behavior while no brief is available;
- historical screener restoration;
- independently assigning different models to the three roles;
- shared-harness mechanisms that `brief_revise_agent` does not currently wire in.