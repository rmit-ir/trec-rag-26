#set document(title: "brief_revise_agent Factorial Hill-Climb: Lab Report", author: "trec-rag-26")
#set page(paper: "us-letter", margin: (x: 2.2cm, y: 2.2cm), numbering: "1")
#set text(font: "Libertinus Serif", size: 10.5pt)
#set heading(numbering: "1.1")
#set par(justify: true, leading: 0.62em)
#show raw.where(block: true): set text(font: "DejaVu Sans Mono", size: 8.5pt)

#let accent = rgb("#2a78d6")
#let muted = rgb("#52514e")
#let good = rgb("#008300")
#let bad = rgb("#e34948")

#align(center)[
  #text(size: 18pt, weight: "bold")[brief_revise_agent Factorial Hill-Climb]

  #text(size: 12pt, fill: muted)[LLM and structural factor analysis vs. `aus_agent_v2`]

  #text(size: 9.5pt, fill: muted)[2026-08-07/08 -- 15-topic TREC RAG 2026 dev subset -- 31 scored cells, 2 arena batches -- ≈\$504 of a \$600 cumulative budget]
]

#v(0.4cm)
#line(length: 100%, stroke: 0.5pt + muted)
#v(0.3cm)

= Executive summary

`brief_revise_agent` (a light fork of `aus_agent`: a pre-flight requirements
brief plus one review-and-revise pass on top of the shared `agent_harness`
research loop) was hill-climbed against `aus_agent_v2` (this repo's
strongest, most expensive system) via standalone rubric scoring on a fixed
15-topic development set, with sol (`gpt-5.6-sol`) as design authority and
the current session as orchestrator/implementer.

#box(fill: rgb("#f4f8fd"), inset: 10pt, radius: 4pt, width: 100%)[
  *Ties `aus_agent_v2` on standalone rubric at a fraction of the cost --
  and a standalone-only "improvement" turned out to be arena-worse when
  actually checked, the report's own cautionary case study.* The base
  configuration -- gpt-5.6-sol as main generator, round-B adjacent-page
  fetch on, gpt-5.6-luna as brief-analyst and reviewer, $k=10$,
  iteration-1 structure -- scores *2.267/3* on standalone rubric grading
  (§4), *exactly ties `aus_agent_v2`'s own standalone score* (2.267,
  §4.5 -- a much more expensive system, §7 Cost-effectiveness), but still
  loses to it in a head-to-head arena match (§5.1), *18--12 (60/40)*,
  order_consistency 0.733 (4W--7L clean, 4 non-order-consistent). Of
  fourteen further single-factor moves against the standalone base, one
  -- `hybrid` search engine alone -- scored *higher* (2.333) and
  replicated cleanly on an independent topic set (§4.6), so it was
  provisionally promoted; arena-confirming it (§5.2) reversed that
  promotion outright, *33.3% win rate vs. the base cell's 40%* -- worse
  in the metric that actually matters despite being better on the one
  used to find it. §6 and §8 discuss why, and why the base cell remains
  the recommendation. Every other tested lever (five generic
  `agent_harness` toggles, one factor interaction, three brief-analyst
  model swaps, adjacent-fetch removal, a "closure critic" mechanism, a
  best-of-4 ensemble selector) was null or negative on standalone and was
  never arena-tested at all. $k$ and the reviewer model were held fixed
  throughout. Of the 16 factors in the underlying taxonomy (§3), 8 were
  empirically scored this session. §7 shows generator-model choice is not
  just the largest standalone effect but also the cheapest per point of
  standalone score gained -- though this report's own arena reversal
  above is a reason not to over-trust standalone effect size alone.
]

= Method

== Design

Sol-directed hill-climbing: starting from `brief_revise_agent`'s best known
configuration, one factor was changed at a time, scored, and kept only if it
improved on the current best -- in contrast to the session's earlier
factorial-grid framing, which was superseded once the hill-climb approach was
adopted partway through. The full factor taxonomy that this hill-climb draws
its factors from is developed in §3, with a "coverage this session" column
in each factor table stating whether it was scored this session, scored in a
different session/thread, or never wired in `brief_revise_agent` at all.

== Two evaluation modes

This session used two distinct judge protocols, kept strictly separate in
§4 and §5 below and compared directly in §6:

*Standalone rubric grading (primary, §4).* One judge call (`gpt-5.6-terra`)
per (cell, topic) grades every official TREC RAG 2026 rubric criterion
(\~31 criteria across 6 axes, 0--2 each) plus a holistic 0--3 `overall`
score -- no opponent answer involved. Chosen as the primary tuning signal
because it halves judge calls per cell versus arena and produces a genuinely
ordinal per-criterion signal instead of a categorical win/loss/tie. Drove
every cell comparison and hill-climb move this session (31 cells
total, §4). Answer
text is truncated to 16,000 characters before grading
(`rubric_scorecard_aus_agent_vs_facets_agent.py`); no answer scored this
session was observed to hit that cap, but it is not independently verified
for every cell.

*Pairwise arena (confirmatory, §5).* One head-to-head judge call
(`gpt-5.6-terra`), both presentation orders, comparing two full answers on
the same topic and declaring a win/loss/tie -- run twice this session,
each cell vs. `aus_agent_v2`, as the direct test of the actual
competitive objective rather than a tuning signal.

*Judge/generator overlap.* `gpt-5.6-terra` is both the sole judge for every
score in this report (standalone and arena alike) and one of the five
generator models compared in §4.1 (its own cell scored 1.867). This is a
same-family-model confound that was not controlled for or discussed at the
time; it is disclosed here rather than silently assumed away.

*Noise floor (standalone only).* `overall` is a single integer 0--3 graded
per topic and averaged over 15 topics, so every reported standalone score is
an exact multiple of $1/15 approx 0.0667$ (e.g. $2.267 = 34\/15$,
$2.200=33\/15$, $2.133=32\/15$). The best cell was regenerated once on the
same 15 topics; the rerun's score moved by exactly one topic-grade, i.e.
$1/15 = 0.067$, purely from generation stochasticity. This single-rerun
value ($n=1$) is used throughout §4 as the noise floor -- an effect below it
is not distinguishable from one topic's grade flipping, not a statistically
estimated confidence interval. Concretely, "$-0.134$" means two of fifteen
topics scored one point lower; it is not a smaller-than-it-looks effect once
read this way. Arena results (§5) use a different unit (win/loss/ambiguous
counts) and this noise floor does not apply to them -- see §6 for how the
two are actually compared.

== Constraint discovered mid-session

The full TREC RAG 2026 research-rubrics development topic set is only 30
topics total. Fifteen were already committed to the tuning set, leaving only
15 unused topics for replication -- smaller than originally planned, and
insufficient for a full independent held-out arena confirmation once
`aus_agent_v2`'s own per-topic generation cost (\~\$36.5/topic) is
accounted for. The judging budget cap itself was also raised mid-session,
from an original \$50 (design) + \$50 (evaluation) split to \$400, once the
model-effect result in §4.1 made further hill-climbing look worthwhile (§12
of the narrative worklog).

= Factor taxonomy

`brief_revise_agent` and its shared `agent_harness` layer expose 16 distinct
factors that can plausibly change answer quality: 13 structural/architectural
factors (S1--S13) and 3 model-role factors (M1--M3, which model runs which
role). This taxonomy was produced by an independent draft-then-review pass
(gpt-5.6-luna drafted from every system's README and 16 `aus_agent_v2` module
docstrings, gpt-5.6-terra reviewed against the same source material and
corrected three items) and is reproduced in full at
`worklogs/assets/2026-08-07-terra-factor-taxonomy-final.md`. Each table's
"Coverage this session" column states which of these 16 were actually
scored this session (all such scoring is standalone-rubric, §4 -- none of
these per-factor moves were separately arena-tested).

== Structural factors (S1--S13)

#figure(
  text(size: 8.3pt)[#table(
    columns: (3.75cm, 1.6cm, 5.4cm, 5.45cm),
    align: (left, center, left, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 5pt,
    table.header([*ID*], [*Mech.*], [*What it is*], [*Coverage this session*]),
    [S1 `requirements_brief`], [PROMPT], [Pre-flight tool-less call that extracts explicit/inferred requirements; rendered as an Appendix A block in the main system prompt.], [Always ON; never toggled],
    [S2 `requirements_brief_schema`], [SCHEMA], [Output contract for the brief: v1 (≤8 entries, ≤4 implicit, lexical anti-hunch check) vs. v2 (14 entries, ≤6 expert-completion entries, no anti-hunch check).], [Tested pre-session (v2 regressed vs. v1); v1 is current, not retested here],
    [S3 `brief_word_budget`], [PROMPT], [Whether the brief also requests `target_total_words` (500--1000) and per-requirement `target_words`; invalid values fail open to no guidance.], [Tested in the rounds-B/C/D thread as round C: 0W/13L/2A vs. baseline, worst of all rounds -- not retested in this factorial thread],
    [S4 `review_revise_pass`], [CONTROL_FLOW], [One-shot `pre_final_hook` after a valid draft: scans uncited sentences, grades brief requirements, gets reviewer feedback, allows exactly one revision turn.], [Always ON (defines `brief_revise_agent`); its *content* was widened this session (see closure critic below), never toggled off],
    [S5 `adjacent_page_augmentation`], [RETRIEVAL], [Fetches the page immediately before/after the top-5 paginated hits of each search batch, zero LLM calls (ported from `aus_agent_v2/search.py`).], [#text(fill: good)[TESTED] -- off vs. on, sol \& qwen],
    [S6 `retrieval_engine_set`], [RETRIEVAL], [Which retrieval backends (`semantic`, `keyword`, `hybrid`, `ssr`, `lucene_bool`) the search tool may use.], [#text(fill: good)[TESTED] -- default `semantic,keyword` vs. widened +ssr+lucene_bool],
    [S7 `search_k`], [RETRIEVAL], [Hits requested per search call when the model omits `k`.], [Held fixed at 10; never varied],
    [S8 `search_result_filter`], [RETRIEVAL], [Post-search relevance pass (`minimize_filter`/`rank_filter`) that narrows or annotates returned evidence.], [#text(fill: bad)[NOT WIRED] -- both filters key off a per-call `requirement` field that `brief_revise_agent`'s search tool schema does not collect; running it as-is would silently degenerate, not test the factor],
    [S9 `search_preview_policy`], [RETRIEVAL], [Whether staged search text is full, or truncated to a positional preview (no generator model) at a fixed 20,480-char cap.], [#text(fill: good)[TESTED] -- full staging vs. 20,480-char positional cap],
    [S10 `stage_search_results`], [RETRIEVAL], [Whether ordinary search results are inserted into the staged-context ledger at all (`get_documents` stays available either way).], [#text(fill: good)[TESTED] -- staged (default) vs. unstaged],
    [S11 `judge_relevance_tool`], [SCHEMA], [A 4th advertised tool; when called it opens a separate single-turn conversation asking whether evidence supports a *named* requirement.], [#text(fill: good)[TESTED] -- off vs. on, alone and in combination with S12],
    [S12 `commit_release`], [SCHEMA], [Adds a `release` array to the `commit_context` schema so the model can retroactively drop an earlier committed document a new one supersedes.], [#text(fill: good)[TESTED] -- off vs. on, alone and in combination with S11],
    [S13 historical requirement-screener], [RETRIEVAL], [Reverted mechanism: mandatory `requirement` field on every search call + one-shot DIRECT/LEAD/OFF_TOPIC screener with a retention floor.], [Tested pre-session (iteration 3): 13 clean losses vs. 10 for baseline -- reverted, not restorable without new code],
  )],
  caption: [Structural/architectural factor taxonomy. Coverage color: #text(fill: good)[green] = scored this factorial session, #text(fill: bad)[red] = not wired / not testable as-is, black = tested in a different session/thread or never varied.],
) <tab-structural>

== Model-role factors (M1--M3)

Current `brief_revise_agent` constructs the main agent, brief analyst, and
reviewer from the *same* backend/model factory call by default; `--model`,
`--brief-model`/`--brief-backend`, and `--review-model`/`--review-backend`
decouple them (added this session to support M2/M3 testing). Five model IDs
are confirmed usable: `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`
(OpenAI backend), `openai.gpt-oss-120b-1:0`, `qwen.qwen3-next-80b-a3b`
(Bedrock, `ap-southeast-2` and `us-east-1`/`us-west-2` respectively).

#figure(
  text(size: 8.8pt)[#table(
    columns: (5.3cm, 5.5cm, 5.6cm),
    align: (left, left, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 5pt,
    table.header([*ID*], [*Role*], [*Coverage this session*]),
    [M1 `main_research_writer_model`], [Runs the continuous research/writing loop: decomposition, search, context commitment, gap follow-up, final cited report.], [#text(fill: good)[TESTED] -- all 5 models, §4.1],
    [M2 `requirements_brief_analyst_model`], [Produces the requirements brief (S1) and word-budget guidance (S3) if enabled.], [#text(fill: good)[TESTED] -- terra/gpt-oss-120b/qwen vs. luna, main=sol fixed],
    [M3 `reviewer_model`], [Grades the candidate against the brief and evidence, emits the one bounded revision.], [Not tested -- explicitly skipped for budget (worklog §14): same role-swap pattern as M2, which showed zero effect],
  )],
  caption: [Model-role factor taxonomy.],
) <tab-modelrole>

== Mechanism examples

Four representative factors, showing exactly what "the factor" is at the
code/prompt level:

*S5 `adjacent_page_augmentation` (RETRIEVAL, zero LLM calls) --*
`adjacent_pages.py`'s core routine, ported from `aus_agent_v2/search.py`:

```python
def adjacent_page_ids(unit_ids: list[str], *,
                      max_seed_hits: int = DEFAULT_MAX_SEED_HITS) -> list[str]:
    """Stable, deduplicated +/-1 page ids for the top `max_seed_hits`
    paginated hits, excluding ids already present in `unit_ids`."""
```
Wired as `search_result_augment` on the shared harness; `--disable-adjacent-pages`
turns it off (default: on).

*S12 `commit_release` (SCHEMA) --* `commit_release_tool.py` adds exactly one
property to the shared `commit_context` schema, deliberately *not* importing
`facets_agent`'s bundled variant (which couples `release` to an unrelated
`coverage`/`ready_to_report` ledger -- a different factor):

```python
_RELEASE_PROPERTY: dict[str, Any] = {
    "release": {
        "type": "array",
        "description": (
            "Previously committed ids to drop because a document you are "
            "committing in THIS SAME call supersedes them ..."
        ),
        "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["id", "reason"]},
    },
}
```
Enabled by `--commit-release`; the harness's own `apply_commit` already
handles a `release` argument whenever present, so this module only needs to
*advertise* the field.

*S4 review pass, closure-critic extension (PROMPT, this session's only new
mechanism) --* `pre_final_hook` fires at most once by harness design, so
this extends the existing single review pass' issue taxonomy rather than
adding a second stage. Base issue types
(`review.py`): `ISSUE_TYPES = frozenset({"UNCITED_CLAIM", "WEAK_SENTENCE"})`.
With `--closure-critic`, two more are unioned in --
`CLOSURE_ISSUE_TYPES = frozenset({"UNSUPPORTED_CLAIM", "CONTRADICTION"})` --
and the reviewer prompt gains these two bullets (`prompts.py`,
`REVIEW_PROMPT_WITH_CLOSURE`):

```
- UNSUPPORTED_CLAIM: a cited sentence that claims MORE than its cited
evidence actually states (a number, scope, or causal claim the evidence
text does not contain) -- an overclaim, not a missing citation.
- CONTRADICTION: two sentences in the draft that cannot both be true, or a
sentence that contradicts its own cited evidence text.
```
Default `closure_check=False` is byte-identical to pre-session behavior.

*S9 `search_preview_policy` (RETRIEVAL, no generator model, this session's
tested level) --* `--search-preview-chars 20480` caps each staged search
result to 20,480 characters before it enters the ledger; `get_documents`
remains the full-text read route regardless. This is a positional
truncation only -- the taxonomy's other preview level (an LLM-generated
query-relevant snippet, tested inconclusively in `facets_agent`'s Phase 4d)
was not exercised here.

= Standalone rubric evaluation

Every result in this section is `overall`, the holistic 0--3 score from
`gpt-5.6-terra`'s standalone grading protocol (§2.2), averaged over 15
topics per cell, with no opponent answer involved. This was the session's
primary tuning signal -- it drove every one of the 30 cell comparisons
scored this session (§4.1--§4.7). Arena (pairwise, confirmatory) is a
completely separate protocol, reported on its own in §5.

== All scored cells

@fig-allcells ranks the 26 `brief_revise_agent` cells scored this session
(the 3 external-system baselines of §4.5 are compared separately in
@tab-baselines, not shown here) by
standalone overall score. The four cells tied at the top (2.267) are the
base cell and three factors that made no measurable difference
(`commit_release`, `judge_relevance_tool` + `commit_release` together, and
the closure critic). Two caveats on comparability across this ranking: the
two `*-new15` cells (sol/luna replication, §4.4) are scored on a *different*
15-topic set than the other 19, so their rank position is not a like-for-like
factor comparison; and the historical `brief-revise-iter1-exp15` reference
(2.067) predates round B's commit and therefore lacks S5, conflating a model
question with a structural one if read as a pure luna-vs-sol comparison (the
apples-to-apples luna comparison is `br-luna-current-code-exp15`, 1.867,
discussed in §6).

#figure(
  image("figures/fig1_all_cells.pdf", width: 92%),
  caption: [Standalone rubric overall score, 26 `brief_revise_agent` cells, sorted. Base cell in blue. #link("interactive/fig1_all_cells.html")[#text(fill: accent)[Interactive version →]]],
) <fig-allcells>

== Hill-climb moves and factor effects

@tab-moves lists every single-factor move scored against the base cell
(2.267), i.e. the moves underlying the "eleven further moves" claim in the
executive summary -- the narrative worklog's own running tallies of "6",
"11", then "12" moves (its §11, §15, §16) reflect moves being added
mid-session and one double-count of the interaction cell; this table is the
reconciled, deduplicated count of distinct scored comparisons.

#figure(
  text(size: 8.8pt)[#table(
    columns: (6.2cm, 1.6cm, 1.7cm, 6.6cm),
    align: (left, left, right, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 5pt,
    table.header([*Factor*], [*Taxonomy ID*], [*Δ vs. base*], [*Verdict*]),
    [Adjacent-fetch OFF (sol)], [S5], [$-0.067$], [reject],
    [`stage_search_results=False`], [S10], [$-0.067$], [reject],
    [`judge_relevance_tool=True`], [S11], [$-0.067$], [reject],
    [`search_preview_chars=20480`], [S9], [$-0.134$], [reject],
    [wider `retrieval_engine_set`], [S6], [$-0.134$], [reject],
    [`commit_release=True`], [S12], [$0.000$], [reject (tie)],
    [`judge_relevance` + `commit_release`], [S11+S12], [$0.000$], [reject (tie); no interaction rescue of either factor's own null/negative result],
    [brief-analyst = terra], [M2], [$-0.067$], [reject],
    [brief-analyst = gpt-oss-120b], [M2], [$-0.067$], [reject, identical to terra],
    [brief-analyst = qwen], [M2], [$-0.067$], [reject, identical to the other two],
    [closure critic (S4 + UNSUPPORTED_CLAIM/CONTRADICTION)], [S4], [$0.000$], [reject (tie)],
  )],
  caption: [Eleven distinct hill-climb moves against the base cell (2.267). Noise floor: $plus.minus 0.067$ (one topic-grade, $n=1$).],
) <tab-moves>

@fig-effects groups the same moves (plus the generator-model comparison that
established the base cell in the first place) by factor family. Generator
model is the only family whose effects consistently and substantially clear
the noise band; every other family in @tab-moves clusters at or inside it.
One caption note: the "adjacent-fetch OFF, qwen" point is computed against
the *qwen* base cell (1.400), not the sol base cell (2.267) plotted
elsewhere in the same figure -- it isolates S5's effect for qwen specifically,
not a comparison to the session's overall best cell.

#figure(
  image("figures/fig2_factor_effects.pdf", width: 92%),
  caption: [Factor effects vs. base cell (sol, 2.267; qwen points vs. qwen's own base, 1.400 -- see note above). Shaded band = noise floor. #link("interactive/fig2_factor_effects.html")[#text(fill: accent)[Interactive version →]]],
) <fig-effects>

#figure(
  table(
    columns: (auto, auto, auto),
    align: (left, center, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 6pt,
    table.header([*Factor group*], [*Effect range*], [*Verdict*]),
    [Generator model (M1)], [-0.40 to -1.07 vs. sol], [Dominant, real -- \~10× any other factor],
    [Adjacent-page fetch off (S5)], [-0.067 (sol) / -0.133 (qwen)], [Real for qwen, borderline for sol -- keep on],
    [Generic `agent_harness` factors (S6, S9--S12)], [-0.134 to 0.000], [Only 2 of 6 scored moves exceed the 1-topic noise floor (preview, wider-engines), both negative -- none help],
    [Brief-analyst model swap (M2)], [-0.067 (all three, identical)], [Noise-level, no real effect],
    [Closure critic (S4 extension)], [0.000], [No effect],
  ),
  caption: [Factor-effect summary by family. Noise floor: ±0.067 (1 topic-grade of 15, $n=1$ rerun).],
)

Once the generator model is already optimized (sol), the remaining
structural and harness-level levers tested have an order of magnitude less
headroom to move the standalone score: ten of eleven post-model-selection
moves in @tab-moves landed at or below the 0.067 (one-topic) noise floor --
not because they were poorly chosen, but because the model-choice effect had
already consumed most of the available variance at this topic-set size and
rubric. This is a claim about the *tested* factor set (§3): S1,
S4-as-a-toggle, S7, S8, S13, and M3 were never varied this session, so
"local optimum" should be read as scoped to the eight factors actually
scored, not the full 16-factor taxonomy.

== Rubric axis breakdown

The official rubric groups its \~31 criteria into six axes: Communication
Quality, Explicit Criteria, Implicit Criteria, Instruction Following,
References \& Citation Quality, and Synthesis of Information. @fig-heatmap
breaks the standalone score down by axis for a representative subset of
cells. *References \& Citation Quality is the weakest axis in every single
cell scored this session* (mean 0.167/2 across all 30 cells scored,
including the baselines of §4.5 and the extended-workstream cells of
§4.6--§4.7, range 0.00--0.67) -- independent of generator model, structural configuration, or
harness toggle. The number of criterion instances contributing to this axis
varies by cell and topic (the original validation run against
`brief-revise-iter1-exp15` pooled $n=9$ instances across 15 topics for this
axis specifically); no factor tested this session meaningfully moves it.
This reads as a systemic issue in how `brief_revise_agent` constructs or
formats citations and reference lists -- a different investigation
(citation format, reference-list construction logic) than anything this
session's factor sweep targeted, and plausibly higher-value than further
generator or harness tuning given how flat the rest of the tested factor
space turned out to be (§4.2).

#figure(
  image("figures/fig3_axis_heatmap.pdf", width: 92%),
  caption: [Rubric axis means (0--2) by cell, all 6 axes. References & Citation Quality stays pale throughout. #link("interactive/fig3_axis_heatmap.html")[#text(fill: accent)[Interactive version →]]],
) <fig-heatmap>

== Model-choice replication

Sol beats luna on a completely independent 15-topic set (2.133 vs. 1.933,
$+0.2$), the same direction as the original comparison ($+0.4$ on the tuning
topics, §4.1), while the same-config, same-topic rerun of sol alone moved by
$0.067$ purely from stochasticity. The honest summary is that sol beats luna
by *roughly $0.2$ to $0.4$ points* depending on topic sample -- the
direction replicates, the magnitude does not pin down to a single number at
this sample size.

== Baseline standalone comparison

Every baseline comparison up to this point had been arena-only (§5).
Standalone-scored `aus_agent_v2`, `aus_agent`, and `facets_agent` on the
same 15 topics for the first time, reusing their existing generations at
zero marginal generation cost (only the judge calls are new). `aus_agent`
and `facets_agent`'s available runs covered 30 topics, not just this
session's 15, so `standalone_rubric_score.py` gained a `--topics` filter to
score the matched subset rather than the full run.

#figure(
  table(
    columns: (auto, auto, auto),
    align: (left, left, right),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 6pt,
    table.header([*System*], [*Run ID*], [*Standalone overall*]),
    [*`brief_revise_agent` (base cell)*], [`br-model-main-sol-exp15-b1`], [*2.267*],
    [*`aus_agent_v2`*], [`aus-agent-v2-exp15-luna`], [*2.267*],
    [`aus_agent`], [`aus-agent-dev30-luna-e2708ab`], [2.000],
    [`facets_agent`], [`facets-agent-dev30-e2708ab`], [1.800],
  ),
  caption: [Standalone rubric, same 15 topics, `gpt-5.6-terra` judge throughout.],
) <tab-baselines>

`brief_revise_agent`'s base cell *exactly ties* `aus_agent_v2` on standalone
rubric grading and beats both other baselines. This sharpens the
standalone-vs-arena tension already documented in §6: arena says
`aus_agent_v2` wins 60/40; standalone rubric says the two systems are
equal. Given §7 shows `aus_agent_v2` costs roughly an order of magnitude
more per topic to generate (its own tracked build cost is \$1,097 across a
much larger effort), this tie is a materially different headline than "did
not beat `aus_agent_v2`" -- see §8 Recommendation.

== Search-engine sweep

No cell up to this point had tested an individual search engine in
isolation -- every cell used the default `semantic,keyword` pair except one
combined 4-engine cell (S6 in @tab-moves, all four engines together,
$-0.134$, rejected). `hybrid` (dense+sparse Reciprocal Rank Fusion, a real
third engine per `src/tools/search_tool.py::ENGINE_INFO`) had never been
exercised at all. "HyDE" is not a selectable engine -- it is a
query-*writing style* `facets_agent`'s own prompt teaches specifically for
the `hybrid` engine (write the query as a short hypothetical passage
rather than a bare phrase); ported as an opt-in system-prompt addendum,
`--hyde-hybrid` (off by default, byte-identical when unset).

#figure(
  table(
    columns: (auto, auto, auto),
    align: (left, right, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 6pt,
    table.header([*Engine (sol, otherwise base config)*], [*Overall*], [*Δ vs. base (2.267)*]),
    [`hybrid` alone (tuning topics)], [*2.333*], [*+0.067* (at the noise floor)],
    [`hybrid` alone (independent replication, new topics)], [*2.333*], [*+0.200* vs. sol's own default-engine result on the same fresh topics],
    [`keyword` alone], [2.267], [tie],
    [`semantic` alone], [2.267], [tie],
    [`hybrid` + HyDE-style query], [2.267], [tie, no gain over plain `hybrid`],
  ),
  caption: [Individual search engines, sol base config, same 15 topics.],
)

Two findings: (1) *no single engine underperforms the default pair* -- both
`keyword` alone and `semantic` alone plateau at exactly the base score, so
the pair is not adding anything a single engine doesn't already provide on
this topic/judge combination; (2) *`hybrid` alone is the only cell in the
entire session at or above the noise floor in the positive direction*
($+0.067$, exactly the threshold used throughout §4 to call an effect
real) -- the single most promising lead found across the full hill-climb
plus this sweep. HyDE-style query framing adds nothing over plain `hybrid`
on this topic set.

=== Replication: confirmed, not noise

Reran sol + `hybrid` (otherwise the base config unchanged) on the same
independent 15-topic set used for §4.4's replication (`br-hybrid-
replicate-new15`). Result: *2.333 -- the identical score to the original
tuning-topic result*, and a *larger* margin over sol's own default-engine
result measured on that same fresh set ($+0.200$: 2.333 vs. 2.133,
@tab-replication-hybrid). Two independent 15-topic measurements landing on
the exact same value is real signal, not resampling luck -- this is now a
*confirmed* effect, not a marginal one at the noise floor.

#figure(
  table(
    columns: (auto, auto),
    align: (left, right),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 6pt,
    table.header([*Cell, independent (new15) topics*], [*Overall*]),
    [sol, default engines (semantic+keyword)], [2.133],
    [luna, default engines], [1.933],
    [*sol, `hybrid` engine only*], [*2.333*],
  ),
  caption: [Hybrid-alone replication, same fresh topics as §4.4.],
) <tab-replication-hybrid>

*This is the concrete answer to "match `aus_agent_v2` at lower cost using
the best search engine and cheapest confirmed components" (§8): sol +
`hybrid` engine alone, dropping the default `semantic,keyword` pair, is
the new recommended `brief_revise_agent` configuration* -- it ties or
beats the previous base cell's standalone score (which itself already
tied `aus_agent_v2`, §4.5) on two independent topic samples, at lower
generation cost than that base cell (§7).

== Best-of-4 ensemble probe

Sol's own recommendation once the hill-climb plateaued (§4.2): the
remaining arena gap (§6) most likely needs a structural mechanism
genuinely distinct from anything tested, rather than another harness
toggle. Sol picked a *best-of-4 winner-take-all selector* over
`aus_agent_v2`'s own heavier `candidate_union` mechanism (item-level
extractive union, up to 8 candidates, anchor-floor accounting -- explicitly
rejected by sol as too much new-code risk for this budget). Mechanism:
reuse the existing base-cell answer as Candidate A, generate 3 fresh
independent reruns of the identical base-cell config as B/C/D (sampling
variance only, no config change), one `gpt-5.6-sol` selector call per
topic picks a single winner *verbatim* -- no rewriting, merging, or
citation repair. Promotion bar: standalone $gt.eq 2.400$ ($+0.133$) *and*
beating the predeclared raw fresh-candidate diagnostic row, or an observed
gain can't be attributed to selection rather than lucky resampling.

#figure(
  table(
    columns: (auto, auto),
    align: (left, right),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 6pt,
    table.header([*Cell*], [*Standalone overall*]),
    [Base cell (Candidate A)], [2.267],
    [Fresh unselected rerun (Candidate B, diagnostic)], [2.267],
    [Best-of-4 selected output], [2.267],
  ),
  caption: [Ensemble probe: all three rows tie exactly.],
)

*Clean null result*: the selected output ties the base cell exactly, and
critically *also ties a single unselected fresh rerun* -- the diagnostic
row sol's own design specified precisely to distinguish "selection adds
value" from "the candidate pool has no real diversity to select from."
Since even one fresh candidate alone matches the base with no selection
step at all, there is no candidate-pool headroom for a selector to
exploit. Per sol's own predeclared diagnostic framework, this specifically
argues *against* spending further budget on the heavier `candidate_union`
mechanism too, not just against this lighter selector.

One implementation issue surfaced and fixed en route, kept here because it
is a reusable lesson: the selector's requested JSON shape
(`{"assessments": {...}, "winner": "X"}`) failed to parse on \~80% of
calls, always with the same error type. Direct reproduction (`repr()` on
the raw text) showed the model consistently omits the `}` that closes
`assessments` before adding `"winner"`, nesting `winner` *inside*
`assessments` and leaving the outer object unclosed -- a deterministic
model formatting mistake, not the escaped-quote issue a first fix
attempt guessed (an API repair-retry using that guess barely moved the
failure rate). A local regex repair
(`re.sub(r'(?<!\})\s*,\s*"winner"', '},"winner"', raw, count=1)`, applied
before falling back to a repair-retry API call) brought the fallback rate
from \~80% to *0%* at zero additional API cost.

= Pairwise (arena) evaluation

This section is a completely separate protocol from §4: a head-to-head
judge call (`gpt-5.6-terra`), both presentation orders, comparing two full
answers on the same topic and declaring win/loss/tie (§2.2) -- no per-
criterion rubric grades, no 0--3 scale, no shared noise-floor unit with §4.
Two arena batches were run this session, both against `aus_agent_v2` on
the same 15 topics: the original base cell (§5.1, 2.267 standalone), and
-- after §4.6's replication made `hybrid`-alone look like a promotion
candidate -- `hybrid`-alone itself (§5.2, 2.333 standalone). The second
batch's result reverses that promotion; see §6 and §8.

== Arena outcome

@fig-arena shows the per-topic outcome of the base cell against
`aus_agent_v2` on the same 15 topics, both battle orders. Of 15 topics, 11
are order-consistent ("clean": both orders agree, order_consistency $=
11/15 = 0.733$) -- 4 clean wins, 7 clean losses -- and 4 are not
order-consistent (ambiguous: the judge's verdict flips or ties depending on
presentation order). The pooled win rate across all 30 individual battle
judgments (both orders, not just the clean subset) is `aus_agent_v2` 60% /
`brief_revise_agent` 40% (18--12), by either the clean or the pooled
reading `aus_agent_v2` wins the majority of battles.

#figure(
  image("figures/fig4_arena.pdf", width: 78%),
  caption: [Arena outcome, base cell vs. `aus_agent_v2`, 15 topics, both battle orders. #link("interactive/fig4_arena.html")[#text(fill: accent)[Interactive version →]]],
) <fig-arena>

== Arena confirmation of `hybrid`-alone -- reverses the §4.6 promotion

§4.6 replicated `hybrid`-alone's standalone lead over the base cell
(2.333 vs. 2.267) on an independent topic set and, on that basis,
promoted it to a candidate new standing configuration. Arena-confirming
that candidate against `aus_agent_v2` (same 15 topics, both orders,
reusing the existing `br-enginesweep-hybrid-exp15` generation --
judging-only cost) reverses the promotion:

#figure(
  table(
    columns: (auto, auto, auto, auto, auto),
    align: (left, right, right, left, right),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 6pt,
    table.header([*Cell*], [*Standalone*], [*Arena win rate*], [*Clean W-L-A*], [*order\_consistency*]),
    [Base cell (default engines)], [2.267], [40% (18--12)], [4W--7L--4A], [0.733],
    [*`hybrid`-alone*], [*2.333*], [*33.3% (20--10)*], [*2W--7L--6A*], [*0.600*],
  ),
  caption: [Arena, both cells vs. `aus_agent_v2`, same 15 topics.],
) <tab-arena-hybrid>

#figure(
  image("figures/fig6_arena_hybrid.pdf", width: 78%),
  caption: [Arena outcome, `hybrid`-alone cell vs. `aus_agent_v2`, 15 topics, both battle orders. #link("interactive/fig6_arena_hybrid.html")[#text(fill: accent)[Interactive version →]]],
) <fig-arena-hybrid>

*`hybrid`-alone scores higher on standalone rubric but performs worse in
arena than the base cell it was meant to replace* -- fewer clean wins (2
vs. 4), more ambiguous outcomes (6 vs. 4), lower order-consistency (0.600
vs. 0.733), lower overall win rate (33.3% vs. 40%). This is the sharpest
and most consequential instance of the standalone-vs-arena divergence in
this report (§6) -- sharp enough to directly reverse a recommendation
made on standalone evidence alone. See §8 for the corrected
recommendation.

= Comparing the two evaluations

§4 and §5 measure different things on the same base cell, and disagree about
whether it is good enough:

#figure(
  table(
    columns: (auto, 1fr, 1fr),
    align: (left, left, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 6pt,
    table.header([*Aspect*], [*Standalone rubric (§4)*], [*Arena (§5)*]),
    [Judge calls per configuration], [15 (1 per topic)], [30 (2 presentation orders × 15 topics)],
    [What is judged], [One answer, read alone, against \~31 rubric criteria], [Two answers, read together, relative preference],
    [Unit], [0--3 holistic score, $1\/15$ resolution], [win / loss / ambiguous count],
    [Role this session], [Primary -- drove all 31 scored cells (§4.1--§4.7)], [Confirmatory -- 2 batches, base cell and `hybrid`-alone vs. `aus_agent_v2`],
    [Base cell's result], [*2.267/3* -- ties `aus_agent_v2` exactly (§4.5, @tab-baselines)], [*40%* win rate vs. `aus_agent_v2` (18--12 pooled; 4W--7L clean)],
    [`hybrid`-alone's result], [*2.333/3* -- best standalone score in the report (§4.6)], [*33.3%* win rate (20--10 pooled; 2W--7L clean) -- WORSE than the base cell, §5.2],
  ),
  caption: [Standalone vs. arena, same base cell, same 15 topics.],
)

The base cell is the best standalone-rubric cell found, beats the fair
(round-B-inclusive) luna comparison cell by 0.4 points (2.267 vs. 1.867,
`br-luna-current-code-exp15`, §4.1), and *exactly ties `aus_agent_v2`'s own
standalone score* (§4.5) -- yet loses the majority of arena battles against
it (§5.1). This is not a contradiction so much as two different
questions getting two different answers: on rubric-criterion adherence,
the systems are equal; on direct reader preference, `aus_agent_v2` wins.
Whatever makes `aus_agent_v2` win head-to-head -- plausibly completeness,
coverage breadth, or claim density -- is not fully captured by the official
rubric's per-criterion grading.

A parallel, unresolved finding from this session sharpens this: S5
(adjacent-page fetch) helped `luna`'s arena result (round B beat no-round-B
3W/9L/3A vs. 3W/10L/2A in the earlier rounds-B/C/D thread) but *hurt* its
standalone score (1.867 vs. the pre-round-B reference 2.067, §4.1), while
helping *both* metrics for `sol` and `qwen` (§4.2 @tab-moves). This is a
real disagreement between the two evaluation modes on at least one factor,
for one model specifically -- the two protocols do not just differ in
overall level (as the table above shows), they can disagree in *direction*
on the same structural change, and this session did not resolve which
reading to trust for that factor.

A third, sharper case makes the same point at higher stakes: §4.6
replicated `hybrid`-alone's standalone lead over the base cell on an
independent topic set and promoted it as a candidate new standing
configuration on that basis -- arena-confirming it (§5.2) reversed the
promotion outright. `hybrid`-alone is confirmed *better* on standalone
(2.333 vs. 2.267) and confirmed *worse* in arena (33.3% vs. 40% win rate)
than the cell it was meant to replace, in the same session, on the same
15 topics. This is not a marginal-effect ambiguity like the S5 case above
-- it is a real reversal of which cell is "better," entirely dependent on
which evaluation mode is asked.

Practically: standalone score is necessary-but-not-sufficient evidence for
this system, and this session found a concrete case where it was actively
*misleading* as a promotion signal. It is the right tool for cheap,
high-resolution hill-climbing (§4) -- generating and ranking dozens of
candidates would not have been affordable at arena's 2x judge-call cost
-- but a standalone win is not a reliable predictor of an arena win, and
any claim that a configuration "beats" or "matches" `aus_agent_v2` MUST be
checked against arena before being trusted or acted on, never inferred
from a standalone delta alone. §8's recommendation reflects this directly:
the arena-confirmed base cell is recommended over the standalone-only-
confirmed `hybrid`-alone cell, even though the latter scores higher on
the primary tuning signal.

= Cost-effectiveness

Every \$ figure in this section is an *estimate*, not a metered bill: this
repo has no real rate card for any `gpt-5.6-*` OpenAI-backend model, so a
placeholder \$5/1M blended rate (input+output combined -- confirmed by
reading `agent_harness.agent`'s own trajectory summary field,
`processed_tokens`, which already sums uncached-input + cache-write +
output into one number) is applied throughout. This likely
*underestimates* true OpenAI-backend cost, since output tokens are usually
priced several times higher than input. Bedrock cells (gpt-oss-120b, qwen)
use the real metered rate-card file where one exists. Treat every \$ figure
below as a *consistent relative proxy* for comparing factors against each
other, not an absolute dollar amount. Real per-topic token counts were
re-derived from this session's own captured generation logs (never
persisted into `output.json`/`trajectory.json`); reused baseline/Block-0
cells (§4.5, and the five pre-session luna structural cells) are costed at
*\$0 generation* -- their generation was already paid for in an earlier,
separately-reported thread -- but their newly-run standalone judging cost
*does* count here.

#figure(
  image("figures/fig5_cost_effectiveness.pdf", width: 94%),
  caption: [Average cost vs. average standalone score, by factor group (n=1-6 cells per group). #link("interactive/fig5_cost_effectiveness.html")[#text(fill: accent)[Interactive version →]]],
) <fig-cost>

#figure(
  text(size: 8.6pt)[#table(
    columns: (4.2cm, 1.5cm, 2.2cm, 2.3cm, 5.3cm),
    align: (left, center, right, right, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 5pt,
    table.header([*Factor group*], [*n cells*], [*Avg cost*], [*Avg score*], [*Reading*]),
    [Generator model (M1)], [4], [\$8.20], [1.583], [Cheapest AND worst on average -- dominated by gpt-oss-120b/qwen, which are individually cheap but score poorly (§4.1)],
    [*Generator model (BASE, sol)*], [1], [*\$21.61*], [*2.267*], [*Best score in the report, mid-pack cost -- the actual efficient point, not the group average*],
    [Adjacent-page fetch off (S5)], [2], [\$9.94], [1.733], [Cheap because dominated by the low-cost qwen cell; real per-model effect is negative regardless of cost (§4.2)],
    [Search engine, single (S6)], [3], [\$18.06], [2.267], [Keyword/semantic alone: same cost tier as harness toggles, no gain],
    [*Search engine, `hybrid` alone*], [1], [*\$16.93*], [*2.333*], [*Cheapest-and-best-scoring non-model cell in the entire report -- the one lead worth replicating (§4.6)*],
    [Generic `agent_harness` toggles (S9--S12)], [6], [\$19.39], [2.200], [Consistently costs as much as the model factor for a fraction of the effect],
    [Brief-analyst model swap (M2)], [3], [\$20.22], [2.200], [Same cost tier as generic toggles, same null result],
    [Closure critic (S4 ext.)], [1], [\$16.41], [2.267], [No effect, ordinary cost -- a genuinely new mechanism bought nothing here],
    [Ensemble (3 fresh candidates)], [3], [\$19.13], [2.267], [Generation-only cost; the selector call itself is a separate, cheap line below],
    [Ensemble selector (best-of-4)], [1], [\$6.75], [2.267], [Cheap (one selector call/topic + judging) but ties the ensemble candidates' own average -- no selection value added (§4.7)],
    [Replication (3 cells)], [3], [\$20.95], [2.089], [Confirms model direction; costs as much as a fresh factor test],
    [Baselines, reused (aus\_agent\_v2/aus\_agent/facets\_agent)], [3], [\$2.25], [2.022], [\$0 generation (reused); judging-only cost is the cheapest line in the table by construction],
  )],
  caption: [Cost-effectiveness by factor group. "Avg cost" = mean of (generation + judging) per cell in the group, all 15-topic cells unless noted. Bold rows are the two standout points in @fig-cost.],
) <tab-costeffect>

Three things this table shows that the effect-size table (@tab-moves in
§4.2) alone does not:

+ *Every non-model factor costs roughly the same to test* (\$16--21/cell,
  regardless of what the factor actually is) *while moving the score by an
  order of magnitude less* than the model factor. The generic-harness row,
  the brief-analyst row, and the replication row are all within \$2 of the
  base cell's own generation cost -- none of them was cheap to rule out.
+ *The base cell (sol) is not the cheapest generator-model option, but it
  is the only one that is both cheap enough to run at this scale and the
  best-scoring.* The `generator_model` group AVERAGE looks cheap (\$8.20)
  only because gpt-oss-120b and qwen are individually far cheaper *and*
  far worse (§4.1) -- averaging them with sol's own \$21.61 obscures that
  sol is the actual efficient point on the frontier, not a below-average
  one.
+ *`hybrid` alone (§4.6) is the standout: cheaper than the base cell's own
  generation cost AND the only cell to nominally beat it.* Independently REPLICATED on a fresh 15-topic set at the identical score
  (2.333, §4.6) -- not noise. It is the one lead in this entire
  cost-effectiveness table that is simultaneously *cheaper and better*
  than the status quo, which none of the eleven rejected hill-climb moves
  were, and it is now confirmed rather than marginal.

= Recommendation

*Use the original base cell -- gpt-5.6-sol, default `semantic,keyword`
engines, round-B structure, $k=10$, luna brief-analyst/reviewer -- as
`brief_revise_agent`'s standing configuration.* `hybrid`-alone (§4.6)
looked like a strict improvement on standalone evidence (higher score,
lower cost, replicated on two topic sets) and was provisionally promoted
on that basis -- arena-confirming it (§5.2) reversed that: `hybrid`-alone
is confirmed *worse* in head-to-head competition (33.3% vs. 40% win rate,
2W--7L--6A vs. 4W--7L--4A) despite its standalone edge. Since arena is
the actual competitive objective (§2.2) and this session's own evidence
(§6) shows standalone score can be actively misleading as a promotion
signal, the arena-confirmed base cell is the correct recommendation, not
the standalone-only-confirmed `hybrid`-alone cell. Neither cell is
competitive with `aus_agent_v2` head-to-head (§5): both lose the majority
of arena battles, `hybrid`-alone by a wider margin.

+ *Do not switch to `hybrid`-alone* despite its standalone lead -- §5.2's
  arena result is the direct, higher-priority signal, and it points the
  other way.
+ *`hybrid`-alone remains worth understanding, not adopting*: the
  standalone-arena split it produced is now the report's most concrete
  case study in why arena confirmation is mandatory before any promotion
  (§6) -- a plausible follow-up (out of scope for this round's budget) is
  reading the actual failed `hybrid`-alone arena transcripts to see what
  `aus_agent_v2` does that the official rubric under-weights.
+ *Do not spend further budget on generic `agent_harness` toggles, brief-
  analyst swaps, or ensemble/selection mechanisms* -- §7 shows all three
  cost as much to test as the model factor while returning an order of
  magnitude less effect (or, for the ensemble probe specifically, zero
  candidate-pool headroom to exploit at all, §4.7), and none of them was
  arena-tested at all, so even their standalone-null verdicts carry the
  same caveat as `hybrid`-alone's standalone-positive one.

Untested factors that remain open questions, not ruled out: S7
(`search_k`, held at 10 throughout), M3 (reviewer model, never varied),
S2/S3/S13 (schema/word-budget/screener variants, each tested in a
different thread against a different baseline, not against the current
sol base), and S8 (`search_result_filter`, not wired -- would need a
`requirement`-carrying search-tool schema first). Closing the *arena* gap
specifically most likely needs a structural change genuinely distinct from
anything tried this session -- the ensemble probe (§4.7) was that attempt
and returned a clean null, which per sol's own diagnostic framework argues
against `aus_agent_v2`'s heavier `candidate_union` mechanism too, not just
against the lighter selector tried here. The realistic remaining paths are
(a) treating `brief_revise_agent` as the lighter, cheaper, standalone-
equal alternative and reserving `aus_agent_v2` for submissions where its
roughly order-of-magnitude-higher cost (§7) is affordable and arena
performance specifically matters, or (b) a genuinely new structural
mechanism beyond what §4.7 already ruled out as low-value.

= Budget

The judging/generation budget cap was raised twice this session: from an
original \$50+\$50 split to \$400 once §4.1's model-effect result made
further hill-climbing look worthwhile (§2, Constraint discovered
mid-session), then by \$100 to fund the ensemble probe (§4.7), then by a
further \$100 to fund the search-engine sweep (§4.6) once the ensemble
probe's own generation cost left too little headroom for both -- \$600
cumulative.

#figure(
  table(
    columns: (auto, auto, auto),
    align: (left, right, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 6pt,
    table.header([*Line item*], [*Cost*], [*Basis*]),
    [OpenAI + Bedrock generation, this workstream only (≈31 newly-generated cells)], [\$428.42], [estimate for OpenAI cells (placeholder \$5/1M, §7); real for Bedrock cells (metered rate-card files)],
    [Standalone + arena judging (≈495 calls, incl. §4.5 baselines + §4.6 engine sweep \& replication + §4.7 ensemble + §5.2's 2nd arena batch)], [\$74.25], [estimate, \$0.15/call flat],
    [Sol design/thinking calls (7 calls)], [\$0.81], [real -- exact printed API cost],
    [Taxonomy calls (luna draft + terra review)], [\$0.33], [real -- exact printed API cost],
    table.hline(),
    [*Total*], [*≈\$503.81*], [of the \$600 cumulative cap; ≈\$96 unspent],
  ),
  caption: [Final cost breakdown, this workstream. Excludes the earlier, separately-reported round B/C/D improvement-loop thread and other systems' own historical generation cost -- both reused here at \$0 marginal cost (§4.5, §7).],
)

= System ranking and submission recommendation

The organizers allow up to 10 submitted systems/runs. This repository
contains 9 distinct system implementations under `src/systems/`; this
section ranks every one of them on whatever real evidence exists (not
just the `brief_revise_agent` cells this report otherwise focuses on) and
recommends which to submit.

== Implementation status

Four of the nine have *zero generated output anywhere in this repo* --
`ali_deepresearch`, `claude-code-research`, `codex_cli_research`,
`o3_deep_research` (checked directly: `find data/outputs/<system> -name
"*.output.json"` returns nothing for all four). They are scaffolded code,
not evaluated systems -- there is no evidence basis to rank or recommend
them, and doing either would mean guessing. The remaining five all have
real generated answers and at least some comparative evidence:
`aus_agent`, `aus_agent_v2`, `brief_revise_agent`, `facet_rag`,
`facets_agent`.

== Ranking evidence

Evidence quality varies by pair -- this table states exactly what each
number is and is not, since it mixes this report's own measurements
(§4--§5, 0--3 standalone scale, `gpt-5.6-terra` judge, 15-topic exp15 set)
with earlier, separately-reported evaluation runs elsewhere in this repo
(different judge models, different topic counts, a different 0--1
internal rubric scale for `aus_agent_v2`'s own README figures). Nothing
here was re-measured for this section; all figures are read directly from
existing `evaluation-results/` artifacts.

#figure(
  text(size: 8.4pt)[#table(
    columns: (3.3cm, 2.6cm, 5.7cm, 3.4cm),
    align: (left, left, left, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 5pt,
    table.header([*System*], [*This report's standalone (0--3)*], [*Other evidence (this repo, elsewhere)*], [*Cost signal*]),
    [`aus_agent_v2`], [*2.267* (ties row below, §4.5)], [Own README: 0.7042 vs. 0.6508 prior baseline (internal 0--1 rubric, 30 topics, not directly comparable scale). Beats every `brief_revise_agent` iteration/round in arena this repo has run against it (§5, and the earlier rounds-B/C/D thread).], [\$1,096.72 tracked build cost per its own README -- the most expensive system in the repo by a wide margin],
    [`brief_revise_agent` (base cell)], [*2.267* -- ties `aus_agent_v2`], [Loses to `aus_agent_v2` in arena, 40% win rate (§5.1). No direct comparison run against plain `aus_agent` exists.], [\$21.61/15-topic batch, this report's own §7],
    [`aus_agent`], [*2.000* (§4.5, @tab-baselines)], [Beats `facets_agent` 66.7% arena (`aus_agent-vs-facets_agent-dev30-rubric-20260806`, 30 shared topics, `gpt-5.6-terra`). Beats `facet_rag` 15--0 (100%) arena (`aus_agent-vs-facet_rag-15topic`).], [Not measured this workstream],
    [`facets_agent`], [*1.800* (§4.5, @tab-baselines)], [Loses to `aus_agent` 33.3% arena (above). Beats `facet_rag` 30--0 (100%) arena (`facets_agent-vs-facet_rag-15topic`, `gpt-5.6-luna` judge).], [Not measured this workstream],
    [`facet_rag`], [Not measured], [Loses to BOTH `aus_agent` (0--15) and `facets_agent` (0--30) -- the clear weakest system with real output in this repo, by every available comparison.], [Not measured this workstream],
    [`ali_deepresearch`, `claude-code-research`, `codex_cli_research`, `o3_deep_research`], [No output exists], [No output exists -- never run.], [N/A],
  )],
  caption: [Every system in the repo, ranked by available evidence. All four zero-output systems are unranked, not last-ranked -- there is no basis to place them at all.],
) <tab-system-ranking>

Transitive ordering from the table (each arrow is a direct, real
comparison; not every pair has been run head-to-head): `aus_agent_v2` $gt.eq$
`brief_revise_agent` (arena) > `aus_agent` (no direct run, but
`aus_agent` standalone-trails both) > `facets_agent` (arena, 66.7%) >
`facet_rag` (arena, 100% both ways). `aus_agent_v2` and the
`brief_revise_agent` base cell are statistically tied on standalone but
`aus_agent_v2` wins their one direct arena comparison, so it ranks first.

== Recommendation: submit 4, not 10

*Do not fill all 10 slots.* Four of the nine systems have never produced
a single output and would need real implementation and generation work,
not just a submission-format wrapper, before they could be evaluated at
all -- submitting an untested scaffold on the strength of an unfilled
slot count is worse than not submitting it. Of the five systems with real
evidence, `facet_rag` loses every available head-to-head comparison
(100% loss rate against both other baselines that beat it) and is not
worth a submission slot either. That leaves four credible candidates:

+ *`aus_agent_v2`* -- the strongest system in the repo by every available
  comparison, at the highest cost (§7, \$1,096.72 documented build cost).
  Submit if that cost is affordable for the final run.
+ *`brief_revise_agent` (base cell, NOT `hybrid`-alone -- §8)* -- ties
  `aus_agent_v2` on standalone rubric at roughly 1/50th the cost (\$21.61
  vs. \$1,096.72 per this report's and `aus_agent_v2`'s own figures,
  though the two costs were measured with different methodologies, §7),
  and is the second-best system in the ranking. A genuinely distinct,
  much cheaper alternative to `aus_agent_v2`, not a near-duplicate of it.
+ *`aus_agent`* -- cheaper than both of the above (no brief/review
  passes), beats both other mid-tier systems in this repo's own arena
  history (`facets_agent`, `facet_rag`) convincingly. Worth a slot as a
  distinct, simpler architecture and a cost/quality floor reference.
+ *`facets_agent`* -- weaker than `aus_agent` on every available
  comparison, but still convincingly beats `facet_rag` and represents a
  third genuinely distinct architecture (minimal-prompt continuous-agent
  design vs. `aus_agent`'s tuned prompt vs. `brief_revise_agent`'s
  brief+review passes). Marginal case for inclusion -- include only if
  submission-portfolio diversity (distinct architectures, not just
  distinct scores) is itself valued by the organizers' evaluation design;
  omit if the goal is strictly "the 4 best scores," where `facet_rag`
  would not displace it but a second `aus_agent_v2`/`brief_revise_agent`
  variant might.

Do not submit `facet_rag` (loses every available comparison) or any of
the four zero-output systems (no evidence, real implementation work
required first). Do not submit `hybrid`-alone as a `brief_revise_agent`
variant distinct from the base cell -- §8 already recommends against
using it at all, submitting it as a "second `brief_revise_agent` entry"
would just spend a slot on the arena-confirmed-worse configuration.

= Data and code

*Interactive figures* (hover tooltips, self-contained HTML, open directly in
a browser, no server or network needed): `interactive/*.html`, alongside
this PDF, generated by `make_interactive.py`. Every figure above links to
its interactive counterpart.

All generated answers: `data/outputs/brief_revise_agent/` (by `run_id`).
Standalone scores: `evaluation-results/factorial/<run_id>/` (each
`scores.jsonl`/`summary.json`, per-topic grades truncated at 16,000
input characters, §2.2). Arena judgments:
`evaluation-results/factorial/arena-sol-vs-aus-agent-v2-exp15/`.

*Sub-system manifests* (named, reusable JSON configs under
`src/systems/brief_revise_agent/subsystems/*.json`): only *5* of the 21
scored cells were materialized this way -- the original 4 Block-1 model
cells plus the 1 divergent-anchor cell (§5 of the narrative worklog). The
11 hill-climb moves in @tab-moves and the 3 replication cells exist only as
`run_id`s in the execution index below, not as named, reusable manifests.

Execution index (sub-system name → `run_id`, append-only):
`evaluation-results/factorial/executions.jsonl`. Full narrative log with
every intermediate decision, including the running move-count discrepancies
reconciled in @tab-moves: `worklogs/2026-08-07-brief-revise-agent-llm-factorial-design.md`.
Full factor taxonomy (source for §3):
`worklogs/assets/2026-08-07-terra-factor-taxonomy-final.md`. New code this
session: `commit_release_tool.py`, `REVIEW_PROMPT_WITH_CLOSURE` +
`closure_check` (`prompts.py`/`review.py`/`agent.py`/`run.py`), five
generic-factor CLI flags, `--hyde-hybrid` (§4.6),
`ensemble_best_of_4.py` (§4.7, including the local JSON-repair fix), a
`--topics` filter on `standalone_rubric_score.py` (§4.5) -- all on branch
`explore/new-agent-framework-system`.

*Cost-effectiveness data* (§7): `cost_analysis.py` re-derives real
per-topic token usage from this session's captured generation logs and
writes `cost_by_run.json` (per-cell and per-factor-group cost, feeding
@fig-cost and @tab-costeffect); `make_figures.py`/`make_interactive.py`
read it directly, no numbers hand-copied between the analysis and the
report.
