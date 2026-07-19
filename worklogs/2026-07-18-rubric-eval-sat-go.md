# 2026-07-18 — rubric evaluation of the `aus-agent-sat-go` 30-topic batch

Judged all 30 completed runs of the cap-10 batch (`aus-agent-sat-go`, luna
via Azure, `DEFAULT_MAX_COMMITTED_PER_STEP=10`) against
`research-rubrics-dev-rubrics.jsonl` — the official dev rubrics, one row per
qid with `rubrics: [{criterion, weight, axis}]`, 755 criteria total.

### Rubric-citation convention (for re-validation)

Every rubric-specific claim below carries a footnote of the form
**`[<qid> · rubrics[i]]`**, resolving to: the row in
`data/official/trec-rag-2026-data/trec-rag-2026/development-data/researchrubrics-dev-rubrics/research-rubrics-dev-rubrics.jsonl`
whose `qid` matches, then the **0-based** element `i` of that row's
`rubrics` array. Each footnote quotes the criterion **verbatim** with its
`weight` and `axis`. To pull one directly:

```bash
uv run --no-project python -c "import json; \
row=next(json.loads(l) for l in open('data/official/trec-rag-2026-data/trec-rag-2026/development-data/researchrubrics-dev-rubrics/research-rubrics-dev-rubrics.jsonl') if json.loads(l)['qid']=='<qid>'); \
c=row['rubrics'][<i>]; print(c['weight'], c['axis']); print(c['criterion'])"
```

Per-topic machine judgments (one score+note per criterion, same `i`
indexing) are in `worklogs/assets/2026-07-18-rubric-eval/<qid>.json`.

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
   both clear 81% (axis table above). The three weakest axes — Implicit
   Criteria (52.8%), Communication Quality (44%), References & Citation
   Quality (23%) — are all things an *expert* would volunteer but the prompt
   never spells out. This is the same implicit-criteria gap seen in the
   earlier 5-topic dev validation, now confirmed at n=30: attainment is
   gated by expert-volunteered specificity, not by search count or answer
   quality.

2. **Citation quality is the single biggest lever (23%).** Rubrics reward
   *named* authorities — specific studies, laws (HIPAA[^hipaa]), named
   scholars (Segal's 'safety valve'[^segal] and Richlin's 'slave
   theater'[^richlin] theories on Plautus), fund and ETF tickers[^tickers],
   and per-quantitative-claim inline sourcing[^ubi-cite]. ClimbMix is a
   web-crawl corpus of educational prose; it rarely surfaces
   citable-by-name scholarly sources, so the agent answers correctly but
   generically. Two of the three lowest scorers (investing 35%, UBI compare
   43%) are pure "named-entity" misses — 401k[^401k]/IRA[^ira]/Roth[^roth],
   index names[^indexes], brokers[^brokers], fund/ETF tickers[^tickers], and
   post-2015 fiscal-cost figures[^ubi-fiscal] / macro projections[^ubi-macro]
   — exactly the failure mode logged in dev1/dev4.

3. **The floor is a corpus/format problem, not a reasoning one.** Bottom
   five: investing blog series (35%), olympiad-math blog series (39%), self-
   improving-AI proof (40% — but a rigorous, *correct* definitive "no",
   scoring the computability core[^sai-comp] yet penalised only for skipping
   breadth items it never reached: the IRL method[^sai-irl] and formal
   equations[^sai-eqn]), UBI comparison (43%), predictive-policing analysis
   (47%). None is wrong; each misses named specifics the corpus doesn't hand
   over. The self-AI topic (259 words) also shows the sizing floor working
   *against* rubric breadth — a tight, correct answer forfeits breadth
   points.

4. **Penalties are rare and mostly minor** — 11 of 97 negative-weight
   criteria triggered across 30 topics, 9 of them at 0.5. The only clean 1.0
   hits: the pre-school plan proposing to duplicate popular toys (an
   explicitly penalised move)[^toys], the EHR topic making no reference to
   Asian-subgroup prevalence studies[^asian], and the U-Net proposal
   omitting an ablation study[^ablation] and post-processing code[^postproc].
   No safety/quality penalties fired. (Full trigger list with per-topic
   scores in the "penalties triggered" block of the aggregation script
   output — reproduced in the assets judgments.)

5. **Cap-10 breadth shows up but doesn't lift attainment much.** The
   top-refs runs (i_m_trying_to_outline 19 refs → 89%, business/scope runs
   15–17 refs → 66–77%) are broadly the higher scorers, but refs correlate
   weakly with att% — the biological-model topic hits 70% on 10 refs, while
   i_am_planning_to_implement gets 62% on 17. More committed docs buy
   coverage of *stated* facets; they don't manufacture the *unstated* named
   entities the corpus lacks.

[^hipaa]: `[683a58c9a7e7fe4e7695848b · rubrics[12]]` — weight **-5.0**, axis
    *Implicit Criteria* (penalty): "The response fails to address that any
    analysis must comply with HIPAA to prohibit any disclosure of protected
    health information in order to ensure patient privacy." Triggered at 0.5
    (answer discusses de-identification generally but never names HIPAA).
[^segal]: `[684397d188c1deceb49af31d · rubrics[9]]` — weight **3.0**, axis
    *Implicit Criteria*: "The response explains Segal's 'safety valve' theory
    (i.e., that Roman comedy provides audiences with a temporary release from
    social tensions and frustrations by allowing them to laugh at the
    subversion of authority and social norms, before ultimately restoring
    order)." Scored 0 (Plautus answer, 57.2%).
[^richlin]: `[684397d188c1deceb49af31d · rubrics[10]]` — weight **2.0**, axis
    *Implicit Criteria*: "The response explains Richlin's \"slave theater\"
    theory which posits an audience composed of a lower status population."
    Scored 0.
[^401k]: `[683a58c9a7e7fe4e76958498 · rubrics[14]]` — weight **4.0**, axis
    *Implicit Criteria*: "The response defines 401k accounts as an
    employer-sponsored account with tax benefits." Investing blog series
    (35.1%).
[^ira]: `[683a58c9a7e7fe4e76958498 · rubrics[15]]` — weight **4.0**, axis
    *Implicit Criteria*: "The response defines IRA accounts as an account
    with tax benefits that any individual can use."
[^roth]: `[683a58c9a7e7fe4e76958498 · rubrics[23]]` — weight **4.0**, axis
    *Implicit Criteria*: "The response compares traditional and Roth savings
    accounts for the 401k and IRA."
[^indexes]: `[683a58c9a7e7fe4e76958498 · rubrics[24]]` — weight **4.0**, axis
    *Implicit Criteria*: "The response names the major US stock market
    indexes (e.g., S&P 500, Dow Jones Industrial Average, Nasdaq, Russell
    2000)."
[^brokers]: `[683a58c9a7e7fe4e76958498 · rubrics[26]]` — weight **3.0**, axis
    *Implicit Criteria*: "The response names at least 3 different brokers
    available to the public (e.g., Fidelity, Vanguard, Charles Schwab,
    Robinhood)."
[^tickers]: `[683a58c9a7e7fe4e76958498 · rubrics[27] and rubrics[28]]` —
    both weight **3.0**, axis *Implicit Criteria*: rubrics[27] "The response
    names at least 3 commonly traded mutual funds (e.g., FXAIX, VTSAX,
    Fidelity Freedom 2050, Dodge & Cox Income Fund (DODIX))."; rubrics[28]
    "The response names at least 3 commonly traded ETFs (e.g., SPY, QQQ, AGG,
    VEA)."
[^ubi-cite]: `[6847465956a0f6376a6054a7 · rubrics[13]]` — weight **4.0**,
    axis *References & Citation Quality*: "The response uses inline citations
    or footnotes so that every quantitative claim can be traced to a
    specific, credible post-2015 source (e.g. peer-reviewed article,
    government evaluation, think tank report, expert commentary)." UBI
    comparison (43.1%).
[^ubi-fiscal]: `[6847465956a0f6376a6054a7 · rubrics[4]]` — weight **3.0**,
    axis *Implicit Criteria*: "The response provides at least one numerical
    estimate of the annual national fiscal cost of a full Universal Basic
    Income program in a developed country from a post-2015 source, with a
    description of the country, benefit level, coverage assumption and
    expression as dollars or percentage of the country's GDP."
[^ubi-macro]: `[6847465956a0f6376a6054a7 · rubrics[11]]` — weight **3.0**,
    axis *Implicit Criteria*: "The response provides at least one
    quantitative general-equilibrium or macro-model projection for a
    developed-country Universal Basic Income program (e.g. GDP, aggregate
    labor-supply change, projected change in poverty gap, impact on the
    national inflation rate) from a credible post-2015 source and states the
    financing assumption …"
[^sai-comp]: `[6847465956a0f6376a605440 · rubrics[6]]` — weight **2.0**, axis
    *Implicit Criteria*: "The response includes important computability
    theory arguments, specifically Gödel's Incompleteness Theorems, Rice's
    Theorem, and the Halting Problem, as the main barriers to a mathematical
    guarantee of AI alignment …" **Scored 1.0** — this is the core the
    self-AI answer nailed.
[^sai-irl]: `[6847465956a0f6376a605440 · rubrics[8]]` — weight **3.0**, axis
    *Implicit Criteria*: "The response discusses Inverse Reinforcement
    Learning (IRL) as one potential method for an AI to learn human values
    and behavior …" Scored 0 (self-AI proof, 39.5%).
[^sai-eqn]: `[6847465956a0f6376a605440 · rubrics[19]]` — weight **4.0**, axis
    *Implicit Criteria*: "The response includes mathematical equations or
    proofs (e.g., self-replication equation, reward function equation, weight
    updating equation, convergence equation)." Scored 0.
[^toys]: `[684397d188c1deceb49af32d · rubrics[6]]` — weight **-4.0**, axis
    *Implicit Criteria* (penalty): "The response proposes avoiding conflict
    by eliminating scarcity, such as by adding additional toys." **Triggered
    at 1.0** — pre-school plan (59.6%) proposes duplicating popular materials.
[^asian]: `[683a58c9a7e7fe4e7695848b · rubrics[18]]` — weight **-5.0**, axis
    *Synthesis of Information* (penalty): "The response makes no reference to
    previous studies/data about the prevalence rate of autoimmune diseases in
    Asian subgroups (e.g., (1) the paper titled \"High Disease Severity Among
    Asians in a US Multiethnic Cohort of Individuals with Systemic Lupus
    Erythematosus\", …)." **Triggered at 1.0** — EHR/NLP topic (50.9%).
[^ablation]: `[6847465956a0f6376a6053ca · rubrics[18]]` — weight **-3.0**,
    axis *Implicit Criteria* (penalty): "Does not propose an ablation study.
    For example, the report presents results for the final model only and
    does not compare performance with or without key components such as
    attention gates, boundary loss, or postprocessing steps." **Triggered at
    1.0** — U-Net proposal (76.4%).
[^postproc]: `[6847465956a0f6376a6053ca · rubrics[19]]` — weight **-3.0**,
    axis *Implicit Criteria* (penalty): "Omits implementation code for the
    post-processing pipeline." **Triggered at 1.0** — U-Net proposal.

## Takeaway for the batch

Quality-per-token and instruction-following are solid (mean 62%, explicit
criteria 82%). The gap to a higher rubric score is not model reasoning or
retrieval depth — it's (a) named-citation density, capped by what ClimbMix
contains, and (b) expert-volunteered implicit facets. Neither is a
commit-cap or search-count problem, which the cap-10 batch confirms:
breadth rose, attainment mean sits where the 5-topic dev sample predicted.
The next real lever is prompt guidance to volunteer domain-standard
specifics (named frameworks, standards, quantitative anchors) where the
corpus supports them — not more searching. Communication Quality (44%) is a
partly separate, cheaper lever: several misses are format/definitional
asks the corpus does support, e.g. defining financial jargon for a general
audience.[^commq]

[^commq]: Representative Communication Quality penalty:
    `[683a58c9a7e7fe4e76958498 · rubrics[3]]` — weight **-3.0**, axis
    *Communication Quality*: "The response mentions a financial term or
    acronym (e.g. liquidity, yield, Roth IRA, bull market) without defining
    it for a general audience." Triggered at 0.5 on the investing series.
    The axis also covers structural asks like the required comparison
    table `[683a58c9a7e7fe4e76958498 · rubrics[4]]` (weight 3.0) — prose-
    expressible, so *not* format-impossible, but unmet.

Artifacts: runs `data/outputs/aus_agent/20260718T2141*`–`T2159*`
(run-id `aus-agent-sat-go`); raw judgments
`worklogs/assets/2026-07-18-rubric-eval/*.json`.
