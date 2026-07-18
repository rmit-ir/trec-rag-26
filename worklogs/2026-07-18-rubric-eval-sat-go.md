# 2026-07-18 — rubric evaluation of the `aus-agent-sat-go` 30-topic batch

Judged all 30 completed runs of the cap-10 batch (`aus-agent-sat-go`, luna
via Azure, `DEFAULT_MAX_COMMITTED_PER_STEP=10`) against
`research-rubrics-dev-rubrics.jsonl` — the official dev rubrics, one row per
qid with `rubrics: [{criterion, weight, axis}]`, 755 criteria total.

## Method

- Six parallel judge sub-agents, 5 topics each. Each read the rubric row and
  the full answer text (every sentence of `output.json.answer`), scored
  **every** criterion against the **answer text only** (not the trajectory):
  1.0 met / 0.5 partial / 0.0 unmet, strict — a criterion naming specific
  items/examples needs the answer to actually contain them.
- **Attainment** per topic = `Σ(weight·score over ALL criteria) / Σ(positive
  weight)`. Negative-weight criteria are penalties for bad behaviour or
  omission ("fails to address HIPAA", "omits post-processing code",
  "suggests punitive measures"); a positive score on one subtracts from the
  numerator without enlarging the denominator, so attainment is bounded at
  100% and penalties genuinely cost. (The sub-agents' own reported
  `sum(w·s)/sum(w)` figures exceeded 100% on some topics because untriggered
  penalties shrank their denominator — those raw numbers are discarded here;
  the per-criterion judgments they wrote are what these aggregates use.)
- Format-impossible flag available (images/diagrams/media); **no criterion
  was judged impossible** — all 755 were prose-expressible, so no criterion
  was excused.
- Raw per-topic judgment files preserved:
  `worklogs/assets/2026-07-18-rubric-eval/<qid>.json` (30 files, one
  judgment per criterion with axis/weight/score/note). These are the only
  surviving evidence — the sub-agent transcripts are gone.

### Two hand-corrections to the sub-agent output

1. Judge for `683a58c9a7e7fe4e76958488` (biological model) skipped criterion
   21 (implicit, w=3, "how diverse engrams form at initialization"). Judged
   directly by grepping the answer: mechanisms present (excitability, STDP,
   synaptic tagging) but not tied to initialization diversity → **0.5**.
2. Same topic c5 (explicit, w=-4, penalty for *claiming* global backprop is
   biologically implausible): judge scored 0.5, but the answer never makes
   that claim → penalty not triggered → corrected to **0.0**.

## Per-topic attainment (all 30, corrected)

| topic | domain | expl | att% | #crit | refs | words |
|---|---|---|---|---|---|---|
| i_m_trying_to_outline | Historical Analysis | Low | 89.1 | 28 | 19 | 965 |
| write_an_introduction_on_markov | STEM | Low | 87.7 | 20 | 12 | 842 |
| write_me_a_complete_overview | Other | Medium | 81.7 | 27 | 15 | 924 |
| create_a_simple_agentic_ai | Technical Documentation | Medium | 79.2 | 24 | 6 | 1016 |
| write_a_comprehensive_analysis_for | Business Planning & Research | Medium | 77.4 | 22 | 15 | 967 |
| design_a_modified_u_net | AI & ML | Low | 76.4 | 23 | 12 | 845 |
| write_about_the_politics_of | Creative Writing | Medium | 71.9 | 22 | 13 | 958 |
| write_a_strategic_business_report | Business Planning & Research | Medium | 70.6 | 25 | 17 | 918 |
| act_as_a_creative_technical | Business Planning & Research | High | 70.6 | 28 | 6 | 968 |
| propose_a_biologically_plausible_model | AI & ML | Low | 70.3 | 22 | 10 | 653 |
| i_m_trying_to_scope | Technical Documentation | Medium | 66.5 | 31 | 17 | 992 |
| i_m_trying_to_block | Hypotheticals & Philosophy | Low | 66.1 | 21 | 16 | 866 |
| design_a_framework_for_regulating | AI & ML | Medium | 64.8 | 25 | 15 | 837 |
| i_am_planning_to_implement | Technical Documentation | Medium | 62.2 | 29 | 17 | 986 |
| write_a_blog_post_contrasting | STEM | Medium | 61.7 | 20 | 12 | 977 |
| you_are_writing_a_feature | Historical Analysis | Low | 60.9 | 31 | 11 | 820 |
| conduct_a_comprehensive_evidence_based | Historical Analysis | Medium | 59.8 | 26 | 11 | 964 |
| i_am_a_pre_school | Hypotheticals & Philosophy | High | 59.6 | 26 | 12 | 910 |
| i_am_a_software_engineer | Technical Documentation | Medium | 59.0 | 27 | 12 | 979 |
| imagine_the_following_alternate_history | Hypotheticals & Philosophy | High | 59.0 | 30 | 6 | 907 |
| write_a_technical_proposal_for | Technical Documentation | Medium | 58.4 | 21 | 10 | 949 |
| write_an_analysis_of_the (Plautus) | Historical Analysis | Medium | 57.2 | 32 | 12 | 958 |
| help_create_a_detailed_outline | Creative Writing | Medium | 55.5 | 24 | 5 | 816 |
| compose_a_concise_technical_report | AI & ML | Low | 51.0 | 21 | 7 | 441 |
| i_m_currently_working_on | AI & ML | High | 50.9 | 20 | 11 | 986 |
| conduct_an_analysis_to_determine | Current Events | High | 46.5 | 28 | 15 | 865 |
| compare_the_effectiveness_and_potential | Other | Medium | 43.1 | 28 | 11 | 804 |
| prove_definitely_whether_a_self | Hypotheticals & Philosophy | Medium | 39.5 | 23 | 8 | 259 |
| write_a_series_of_blog (olympiad math) | STEM | Low | 38.9 | 20 | 6 | 836 |
| write_a_series_of_blog (investing) | General Consumer Research | Low | 35.1 | 31 | 6 | 874 |

**mean 62.4 · median 61.3 · min 35.1 · max 89.1 · stdev 13.7**

## By axis (positive-weight criteria, all topics pooled)

| axis | attainment | total weight |
|---|---|---|
| Explicit Criteria | 81.6% | 781 |
| Instruction Following | 81.5% | 84 |
| Synthesis of Information | 53.6% | 250 |
| Implicit Criteria | 52.8% | 794 |
| Communication Quality | 44.0% | 116 |
| References & Citation Quality | 23.0% | 50 |

## By domain / exploration

- **Domain (mean att%):** Business Planning 72.8 · Historical 66.8 ·
  Technical Docs 65.1 · Creative Writing 63.7 · STEM 62.8 · AI & ML 62.7 ·
  Other 62.4 · Hypotheticals & Philosophy 56.1 · Current Events 46.5 ·
  General Consumer Research 35.1 (n=1 each for the last two).
- **Exploration:** Low 64.0 · Medium 63.0 · High 57.3. High-exploration
  topics score lowest — the breadth the rubric rewards is where the agent
  still under-delivers.

## Findings

1. **The system does what it's told and misses what it isn't.** Explicit
   Criteria (things the prompt literally asks for) and Instruction Following
   both clear 81%. The three weakest axes — Implicit Criteria (52.8%),
   Communication Quality (44%), References & Citation Quality (23%) — are all
   things an *expert* would volunteer but the prompt never spells out. This
   is the same implicit-criteria gap seen in the earlier 5-topic dev
   validation, now confirmed at n=30: attainment is gated by expert-
   volunteered specificity, not by search count or answer quality.

2. **Citation quality is the single biggest lever (23%).** Rubrics reward
   *named* authorities — specific studies, laws (HIPAA), named scholars
   (Segal/Richlin on Plautus), fund/ETF tickers, dated events. ClimbMix is a
   web-crawl corpus of educational prose; it rarely surfaces
   citable-by-name scholarly sources, so the agent answers correctly but
   generically. Two of the three lowest scorers (investing 35%, UBI compare
   43%) are pure "named-entity" misses — 401k/IRA/Roth/tickers,
   fiscal-projection numbers — exactly the failure mode logged in dev1/dev4.

3. **The floor is a corpus/format problem, not a reasoning one.** Bottom
   five: investing blog series (35%), olympiad-math blog series (39%), self-
   improving-AI proof (40% — but a rigorous, *correct* definitive "no",
   penalised only for skipping breadth items), UBI comparison (43%),
   predictive-policing analysis (47%). None is wrong; each misses named
   specifics the corpus doesn't hand over. The self-AI topic (259 words) also
   shows the sizing floor working *against* rubric breadth — a tight, correct
   answer forfeits breadth points.

4. **Penalties are rare and mostly minor** — 11 of 97 negative-weight
   criteria triggered across 30 topics, 9 of them at 0.5. The only clean 1.0
   hits: the pre-school plan proposing to duplicate popular toys (an
   explicitly penalised move), the EHR topic making no reference to Asian-
   subgroup prevalence studies, and the U-Net proposal omitting ablation
   study + post-processing code. No safety/quality penalties fired.

5. **Cap-10 breadth shows up but doesn't lift attainment much.** The
   top-refs runs (i_m_trying_to_outline 19 refs → 89%, business/scope runs
   15–17 refs → 66–77%) are broadly the higher scorers, but refs correlate
   weakly with att% — the biological-model topic hits 70% on 10 refs, while
   i_am_planning_to_implement gets 62% on 17. More committed docs buy
   coverage of *stated* facets; they don't manufacture the *unstated* named
   entities the corpus lacks.

## Takeaway for the batch

Quality-per-token and instruction-following are solid (mean 62%, explicit
criteria 82%). The gap to a higher rubric score is not model reasoning or
retrieval depth — it's (a) named-citation density, capped by what ClimbMix
contains, and (b) expert-volunteered implicit facets. Neither is a
commit-cap or search-count problem, which the cap-10 batch confirms:
breadth rose, attainment mean sits where the 5-topic dev sample predicted.
The next real lever is prompt guidance to volunteer domain-standard
specifics (named frameworks, standards, quantitative anchors) where the
corpus supports them — not more searching.

Artifacts: runs `data/outputs/aus_agent/20260718T2141*`–`T2159*`
(run-id `aus-agent-sat-go`); raw judgments
`worklogs/assets/2026-07-18-rubric-eval/*.json`.
