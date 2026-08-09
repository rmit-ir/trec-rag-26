# Factor taxonomy

Scope: factors below are grounded in the supplied repository descriptions, `run_agent` signature/docstring, the `brief_revise_agent` notes, and named worklogs. “Already tested?” means the supplied material reports an actual implementation trial or run; where the excerpt gives no score, that is stated explicitly rather than inferred.

## 1. Structural / architectural factors

### S1. `system_prompt_variant`

- **Definition:** Selects the full system-prompt arm used by the main research/writing loop. The variants are intended to change one prompt-level behavior while preserving the shared harness contract.
- **Levels:**
  - `default` — control
  - `firsthand` — favors first-hand/original sources
  - `paired-lead` — waits for both retrieval engines before judging a lead
  - `done-condition` — uses a lead ledger and marginal-yield termination
  - `evidence-dense` — requires denser sentence-level evidence and figures
- **Source:** `src/systems/aus_agent/prompts/system/README` material; `src/systems/aus_agent/README.md`; `brief_revise_agent/prompts/system/default.md`.
- **Already tested?:** **Yes, structurally; quality result not stated in the supplied material.** The variants are described as existing single-variable arms. The brief agent’s prompt is a byte-copy of the AUS baseline plus its review-pass section.
- **Mechanism type:** **PROMPT**

### S2. `requirements_brief`

- **Definition:** Controls whether a separate, tool-less LLM call first extracts explicit and inferred answer requirements and appends them to the research system prompt.
- **Levels:** On / off. On is the current behavior; off requires bypassing the brief step in code.
- **Source:** `src/systems/brief_revise_agent/README.md`; `brief.py`; `prompts.py`; `worklogs/2026-08-06-brief-revise-agent-architecture-plan.md`; session additions.
- **Already tested?:** **Yes.** The brief was built and used in pilot/dev30 worklogs, but the supplied excerpts do not state a numerical quality result for the brief-only effect. The current implementation is described as always on.
- **Mechanism type:** **PROMPT**

### S3. `requirements_brief_schema`

- **Definition:** Selects the requirements-brief output contract. The schema determines how many requirements may be emitted and how implicit requirements are admitted.
- **Levels:**
  - **v1/current:** maximum 8 entries, at most 4 implicit entries, lexical anti-hunch/request-quotation check.
  - **v2 / “atomic expert-completion”:** 14 entries, at most 6 expert-completion entries, no lexical anti-hunch check.
- **Source:** `brief.py`; session additions; `worklogs/2026-08-07-brief-revise-agent-phase5-dev30-and-decision.md`; `worklogs/2026-08-07-brief-revise-agent-sol-improvement-analysis.md`.
- **Already tested?:** **Yes.** The supplied material explicitly says v2 **regressed versus v1**; v1 is current. No numerical result is supplied here.
- **Mechanism type:** **SCHEMA**

### S4. `brief_word_budget`

- **Definition:** Controls whether the requirements brief also supplies a total target answer length and per-requirement word targets. Invalid values cause the feature to fail open to no budget.
- **Levels:** On / off. The current HEAD includes the “round C” word-budget behavior; disabling would require a prompt-variant or code change.
- **Source:** `brief.py`; session additions; `worklogs/2026-08-07-brief-revise-agent-phase5-dev30-and-decision.md`.
- **Already tested?:** **Yes, as an implemented round/candidate; the supplied material gives no quality verdict or score.**
- **Mechanism type:** **PROMPT**

### S5. `review_revise_pass`

- **Definition:** Controls the one-time pre-final review hook. It scans for uncited sentences and has a reviewer identify brief violations or grounded fixes, after which the main model may revise once.
- **Levels:** On / off. The hook is on by default in `brief_revise_agent`; `pre_final_hook=None` disables it in code.
- **Source:** `src/systems/brief_revise_agent/README.md`; `review.py`; `agent_harness.agent.run_agent` docstring; session additions.
- **Already tested?:** **Yes.** The hook’s exception handling and one-revision behavior are covered by offline tests, and it was used in the brief-revise pilot/dev30 worklogs. The supplied text does not provide a standalone score for the review pass.
- **Mechanism type:** **CONTROL_FLOW**

### S6. `adjacent_page_augmentation`

- **Definition:** Controls whether search results are augmented with the immediately preceding and following paginated document pages around the top five hits before staging.
- **Levels:** On / off. On is the current default; the CLI exposes `--disable-adjacent-pages`.
- **Source:** `adjacent_pages.py`; `agent_harness.agent.run_agent`’s `search_result_augment` parameter; session additions; `worklogs/2026-08-06-brief-revise-agent-two-tier-v2-improvements.md`.
- **Already tested?:** **Yes, as “round B.”** The supplied excerpts establish implementation and toggleability but do not state a quality result.
- **Mechanism type:** **RETRIEVAL**

### S7. `retrieval_engine_set`

- **Definition:** Selects which search backends are exposed to the main loop. This changes the evidence sources and the engine choices available in each search call.
- **Levels:**
  - `semantic,keyword` — `brief_revise_agent` and `aus_agent` default
  - `semantic,keyword,hybrid` — `facets_agent` default
  - `ssr` — explicitly supported as an isolated engine configuration by the shared harness docstring  
    (`lucene_bool` is also named as an available engine in the repository, so it is another concrete alternative).
- **Source:** `brief_revise_agent/README.md`; `agent_harness.agent.run_agent` docstring; `facets_agent/README.md`; `facet_rag/README.md`; engine-comparison worklogs.
- **Already tested?:** **Yes.** The repository contains engine-comparison and SSR/keyword worklogs. The supplied material does not give one consolidated result for these exact brief-agent levels.
- **Mechanism type:** **RETRIEVAL**

### S8. `search_k`

- **Definition:** Sets the default number of results requested per search when the model omits `k`.
- **Levels:**
  - `10` — `brief_revise_agent` CLI/default usage
  - `15` — `facets_agent`’s `DEFAULT_HYBRID_K`
  - `20` — `aus_agent_v2` retrieval returns 20 ranked units per search
- **Source:** `brief_revise_agent/README.md`; `facets_agent/README.md`; `aus_agent_v2/README.md`; `agent_harness.agent.run_agent` docstring.
- **Already tested?:** **Yes, in sibling systems and retrieval worklogs; no isolated brief-agent result is reported in the supplied material.**
- **Mechanism type:** **RETRIEVAL**

### S9. `search_result_filter`

- **Definition:** Adds a post-search relevance judgment before documents are staged. It can either remove judged-irrelevant documents or preserve all documents while changing their order and annotations.
- **Levels:**
  - Off / no filter
  - `minimize_filter` — retain only documents judged relevant, while retaining unverdicted documents
  - `rank_filter` — retain everything but order `relevant`, `adjacent_not_relevant`, then `irrelevant`
- **Source:** `src/agent_harness/agent.py`; `src/systems/facets_agent/filtering.py`; `worklogs/2026-08-06-facets-agent-phase4cd-ab-and-two-tier.md`; session additions.
- **Already tested?:** **Yes, in `facets_agent`, not in `brief_revise_agent`.** The supplied worklog material says the A/B result was still pending/inconclusive for these shared-hook variants. A different mandatory requirement-based retrieval screener was tested and **performed worse**: 13 clean losses versus 10 wins, then was reverted and deleted.
- **Mechanism type:** **RETRIEVAL**

### S10. `search_preview_policy`

- **Definition:** Controls whether search results enter the model as full staged text, as bounded previews, or as generated query-relevant snippets. Full documents remain available through `get_documents` in the preview modes.
- **Levels:**
  - Off — current full-result staging behavior
  - Positional preview capped at `20,480` characters — the harness’s existing approximate per-result text budget
  - Generated query-relevant preview capped at `20,480` characters — uses `search_preview_generator` plus the same hard cap
- **Source:** `agent_harness.agent.run_agent` docstring; `aus_agent/README.md` (20,480-character implementation of the approximately 4,096-token default); `facets_agent/filtering.py`/two-tier descriptions; `worklogs/2026-08-06-facets-agent-two-tier-snippet-diagnosis.md` and `...two-tier-v2-improvements.md`.
- **Already tested?:** **Yes, in `facets_agent`’s Phase 4d/two-tier experiments.** The supplied session summary characterizes the result as **inconclusive**. The 20,480-character cap is the repository-grounded value; no other numeric character limits are stated in the supplied material.
- **Mechanism type:** **RETRIEVAL**

### S11. `stage_search_results`

- **Definition:** Controls whether ordinary search results are inserted into the context ledger at all. `get_documents` remains available as the explicit full-text read operation when staging is disabled.
- **Levels:** On / off.
- **Source:** `agent_harness.agent.run_agent` docstring; `brief_revise_agent`’s shared-harness configuration.
- **Already tested?:** **No reported live quality test for `brief_revise_agent`.** The hook exists in the shared harness; the supplied material describes it as unused by this system.
- **Mechanism type:** **RETRIEVAL**

### S12. `judge_relevance_tool`

- **Definition:** Controls whether the model can call a fourth tool that launches a separate, single-turn model conversation to judge whether staged or committed documents support a named requirement.
- **Levels:** Off / on.
- **Source:** `agent_harness.agent.run_agent` docstring; `agent_harness.tools`; `worklogs/2026-08-06-facets-agent-phase4b-judge-relevance-tool.md`; session additions.
- **Already tested?:** **Yes, in `facets_agent` Phase 4b.** The supplied material establishes the implementation and sibling-system use, but gives no standalone quality number for enabling it in `brief_revise_agent`. It is currently unused by that system.
- **Mechanism type:** **CONTROL_FLOW**

### S13. `commit_release`

- **Definition:** Controls whether the commit-context schema exposes the ability to release previously committed documents when a better document supersedes them. This changes what evidence remains in the provider history.
- **Levels:** Off / on.
- **Source:** `facets_agent/README.md`; `agent_harness.context.ContextLedger.release_committed`; `agent_harness.tools.commit_context`; `agent_harness.agent.run_agent`’s `commit_context_tool` parameter.
- **Already tested?:** **Yes, in `facets_agent`.** Its commit–supersede–release test verifies that the superseded text leaves history. The supplied worklog material says `release_committed` was never invoked in 15 real runs, so there is no reported live quality result. It is unused by `brief_revise_agent`.
- **Mechanism type:** **SCHEMA**

### Historical item not counted as a current factor

The requirement-labelled retrieval screener—mandatory `requirement` on search calls plus DIRECT/LEAD/OFF_TOPIC screening—is documented as **reverted/deleted**. It should not be treated as an available current level without restoring historical code. Its measured result was worse than baseline: **13 clean losses versus 10**.

---

## 2. Model-choice factors

The repository explicitly confirms five usable model IDs. These are model factors by role, not architectural mechanisms.

### M1. `main_research_writer_model`

- **Definition:** Selects the LLM running the continuous research, search/commit, and final writing loop.
- **Levels:**
  - `gpt-5.6-luna` — OpenAI/Azure
  - `gpt-5.6-terra` — OpenAI/Azure
  - `gpt-5.6-sol` — OpenAI/Azure
  - `openai.gpt-oss-120b-1:0` — Bedrock
  - `qwen.qwen3-next-80b-a3b` — Bedrock
- **Source:** Session’s confirmed-model list; `brief_revise_agent/README.md`; `facet_rag/README.md`; `agent_harness` provider configuration.
- **Already tested?:** **Yes, as model usage across repository systems and worklogs.** The supplied material identifies Luna as this session’s generator, Terra as the judge, and Sol as the reasoning/design model, but does not provide a controlled brief-agent quality comparison across these five models.
- **Mechanism type:** **MODEL**

### M2. `requirements_brief_analyst_model`

- **Definition:** Selects the LLM making the pre-flight requirements brief.
- **Levels:** The same five confirmed IDs above.
- **Source:** `brief_revise_agent/README.md` and session’s confirmed-model list. The current implementation uses the same backend/model factory as the run.
- **Already tested?:** **Yes, in the brief-revise implementation and pilot worklogs.** The supplied material does not report a controlled analyst-model comparison.
- **Mechanism type:** **MODEL**

### M3. `reviewer_model`

- **Definition:** Selects the LLM performing the one grounded review of the candidate answer and generating revision feedback.
- **Levels:** The same five confirmed IDs above.
- **Source:** `review.py`; `brief_revise_agent/README.md`; session’s confirmed-model list.
- **Already tested?:** **Yes, as part of the implemented review pass and its tests/pilots.** No controlled reviewer-model comparison or standalone score is supplied.
- **Mechanism type:** **MODEL**

**Coupling note:** Current `brief_revise_agent` construction obtains the main loop, brief analyst, and reviewer from the same backend/model factory, so the three model factors are not independently selectable through the current CLI. They are nevertheless distinct role factors in the architecture; independent assignment would require a small configuration change.

---

# Rough scale of a naive full factorial

Using the structural factors above:

- 13 structural factors
- Level counts:  
  `5 × 2 × 2 × 2 × 2 × 2 × 3 × 3 × 3 × 3 × 2 × 2 × 2`
- Structural cells: **34,560**

Using the three role-specific model factors:

- 3 model factors
- 5 levels each
- Model cells: **125**

A naive full cross-factor factorial over all listed factors would therefore be:

**34,560 × 125 = 4,320,000 cells**

That count is intentionally naive. It includes combinations that the current implementation does not expose cleanly—for example, independently assigning different models to the three roles—and combinations that are technically supported by the shared harness but currently unused by `brief_revise_agent`.