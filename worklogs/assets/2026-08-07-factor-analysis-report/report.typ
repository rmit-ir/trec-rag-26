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

This section answers a different question than the Budget total in §9.
Budget (§9) is *what this whole analysis session spent* -- generation +
judging + design, summed once. This section is *what the deployed system
would pay per topic, forever, if shipped with a given component turned
on* -- generation only, judging excluded entirely, because judging is a
one-off evaluation cost this workstream pays to find out which
configuration is good, not something the production system pays on every
query. That is the number that should actually drive an
include/exclude call on any one component.

Every \$ figure below is still an *estimate*, not a metered bill, for the
same reason as before: no real rate card exists in this repo for any
`gpt-5.6-*` OpenAI-backend model, so a placeholder \$5/1M blended rate
(input+output combined) is applied to every OpenAI-backend cell; Bedrock
cells (gpt-oss-120b, qwen) use the real metered rate-card file. Treat
every \$/topic figure as a *consistent relative proxy* for comparing
components, not an absolute dollar amount -- it is likely an
*underestimate* since OpenAI output tokens are usually priced several
times higher than input. Per-topic token counts are re-derived from this
session's own captured generation logs (`processed_tokens`,
`agent_harness.agent`'s own summed input+output field), the only
surviving source since these values are never persisted into
`output.json`/`trajectory.json`.

Each row below is one tested component/level, held against the base
cell's own \$1.290/topic and 2.267 score (sol, default `semantic,keyword`
engines, all structural toggles at their default). "Marginal \$/topic" is
that row's cost *minus* the base cell's -- negative means cheaper than
shipping the base config, not cheaper in absolute terms.

#figure(
  image("figures/fig5_cost_effectiveness.pdf", width: 92%),
  caption: [Production running cost (\$/topic, generation only, no judging) vs. standalone score, one point per tested component/level. #link("interactive/fig5_cost_effectiveness.html")[#text(fill: accent)[Interactive version →]] (hover for exact marginal-\$ and Δ-score per point).],
) <fig-cost>

#figure(
  text(size: 7.2pt)[#table(
    columns: (3.1cm, 3.6cm, 1.5cm, 1.6cm, 1.3cm, 1.3cm),
    align: (left, left, right, right, right, right),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 4.2pt,
    table.header([*Component*], [*Level*], [*\$/topic*], [*Marginal \$*], [*Score*], [*Δ score*]),
    [*Generator model*], [*sol (BASE)*], [*1.290*], [*+0.000*], [*2.267*], [*+0.000*],
    [Generator model], [terra], [0.563], [-0.727], [1.867], [-0.400],
    [Generator model], [gpt-oss-120b], [0.393], [-0.897], [1.200], [-1.067],
    [Generator model], [qwen], [0.113], [-1.177], [1.400], [-0.867],
    [Generator model], [luna], [0.552], [-0.739], [1.867], [-0.400],
    [Adjacent-page fetch], [OFF (default ON)], [0.950], [-0.340], [2.200], [-0.067],
    [Search preview chars], [20480-char cap (default: full)], [1.245], [-0.046], [2.133], [-0.133],
    [Stage search results], [OFF (default ON)], [1.287], [-0.003], [2.200], [-0.067],
    [Judge-relevance tool], [ON (default OFF)], [1.064], [-0.226], [2.200], [-0.067],
    [Commit-release], [ON (default OFF)], [1.207], [-0.084], [2.267], [+0.000],
    [Retrieval engine set], [+ssr+lucene\_bool], [0.917], [-0.373], [2.133], [-0.133],
    [Judge-rel. + commit-rel.], [both ON], [1.136], [-0.154], [2.267], [+0.000],
    [Closure critic], [ON (default OFF)], [0.944], [-0.347], [2.267], [+0.000],
    [Brief-analyst model], [terra (default luna)], [1.161], [-0.130], [2.200], [-0.067],
    [Brief-analyst model], [gpt-oss-120b (default luna)], [1.153], [-0.138], [2.200], [-0.067],
    [Brief-analyst model], [qwen (default luna)], [1.279], [-0.011], [2.200], [-0.067],
    [Retrieval engine set], [keyword only], [1.128], [-0.163], [2.267], [+0.000],
    [Retrieval engine set], [semantic only], [1.140], [-0.151], [2.267], [+0.000],
    [*Retrieval engine set*], [*hybrid only*], [*0.978*], [*-0.312*], [*2.333*], [*+0.067*],
    [Retrieval engine set], [hybrid+HyDE only], [0.896], [-0.395], [2.267], [+0.000],
  )],
  caption: [Production running cost per tested component/level, generation only, judging excluded. All rows compare against the base cell's own \$1.290/topic, 2.267 score. Bold rows: base and the one cell that is both cheaper and better.],
) <tab-costeffect>

Four things this table supports that the effect-size table (@tab-moves in
§4.2) alone does not -- an actual per-component include/exclude call:

+ *`hybrid`-alone is the only component in this entire table that is both
  cheaper AND scores higher than the base config on standalone* --
  \$0.978/topic (24% cheaper than base) and +0.067 score, replicated on a
  second topic set (§4.6). On running cost alone this is a clean win to
  ship. *It is not a clean win overall* -- §5.2 arena-confirmed it loses
  to the base cell's own arena result, so cost-effectiveness and
  arena-effectiveness disagree here exactly as badly as standalone and
  arena disagreed for it in the first place. Cost data does not resolve
  that disagreement; it just makes plain that the standalone-only case
  for `hybrid`-alone was already strong before arena reversed it.
+ *Running both `semantic` and `keyword` engines together (the current
  default) is the single most expensive retrieval-engine option and buys
  nothing on standalone over running either one alone.* Every
  single-engine variant (keyword-only, semantic-only, hybrid-only,
  hybrid+HyDE-only) costs \$0.15--0.39/topic less than the two-engine
  default, and three of the four tie or beat its score. Fewer engine
  calls per topic is fewer search-tool round-trips to pay for -- the
  option matters as much as which engine is chosen (`+ssr+lucene_bool`
  actually costs *less* than the default too, likely because a richer
  tool set let the agent close out topics in fewer total steps rather
  than because the tools themselves are free -- worth confirming before
  reading too much into engine-count savings generally).
+ *gpt-oss-120b and qwen cost 70--91% less per topic than sol but lose
  0.87--1.07 points of standalone score* -- a real, quantified
  cost/quality tradeoff, not a wash. Include one of them only under an
  explicit hard budget constraint, and expect the quality hit that comes
  with it; nothing in this table makes that trade free.
+ *Every structural/harness toggle (adjacent-page fetch, search-preview
  capping, staged search results, judge-relevance tool, commit-release,
  closure critic) moves both cost and score by less than \$0.4/topic and
  0.13 points -- inside the noise this 15-topic-per-cell sample can
  resolve.* None of them is a cost lever worth pulling either way; keep
  them at whatever setting other considerations (latency, robustness,
  §4.2's own qualitative read) already favor, since cost is not the
  deciding factor for any of them.

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

== Recommendation: submit 6, hedged across both real evaluation axes

The organizers' own evaluation plan (`rag-task.md`, not this report)
confirms the exact hedge worth making: submitted responses are scored
*both* ways -- "system-by-system battles" (pairwise, blind, randomized
order, matching this report's arena protocol, §5) *and* "individualized
nugget rubric scoring... independently against narrative-specific nugget
criteria" (matching this report's standalone protocol, §4), plus separate
weighted citation precision/recall scoring. §6 already showed these two
protocols can rank the SAME two cells in opposite orders. Since the
organizers are really going to run both, a portfolio that wins on only
one axis is a real hedging gap, not excess caution -- submit the winner
of each:

+ *`aus_agent_v2`* -- the strongest system in the repo by every available
  comparison, at the highest cost (§7, \$1,096.72 documented build cost).
+ *`brief_revise_agent` (base cell)* -- ties `aus_agent_v2` on standalone
  rubric at roughly 1/50th the cost (\$21.61 vs. \$1,096.72, though the
  two costs were measured with different methodologies, §7), and is the
  best-available *arena* performer among the cheaper systems (§5.1, 40%
  vs. `aus_agent_v2`).
+ *`brief_revise_agent` (`hybrid`-alone)* -- the best-scoring cell on the
  *standalone/nugget-rubric* axis in this entire report (2.333, §4.6),
  despite being arena-worse than the base cell (§5.2). Excluding it would
  mean betting the whole `brief_revise_agent` entry on the arena reading
  being the one that matters -- given the organizers score both, submit
  both `brief_revise_agent` variants rather than picking one axis for
  them.
+ *`aus_agent`* -- cheaper than the three above (no brief/review passes),
  beats both systems below it in this repo's own arena history
  (`facets_agent`, `facet_rag`) convincingly. A distinct, simpler
  architecture and a cost/quality floor reference.
+ *`facets_agent`* -- weaker than `aus_agent` on every available
  comparison, but still convincingly beats `facet_rag` and is a third
  genuinely distinct architecture (minimal-prompt continuous-agent vs.
  `aus_agent`'s tuned prompt vs. `brief_revise_agent`'s brief+review
  passes). Real, working, and architecturally distinct -- worth the slot
  under a "we don't know exactly how this will be judged" hedge, even
  though it is not the strongest score in the portfolio.
+ *`facet_rag`* -- the weakest system with real output (loses every
  available comparison, §10.2), but it is a fourth genuinely distinct
  architecture (facet decomposition + separate per-facet curation, unlike
  any of the other four), it already has working generated output at
  zero additional cost to include, and its consistent losses so far are
  all against systems tuned specifically for this repo's own evaluation
  loop -- an unknown official judge/rubric could rate it differently.
  Weakest recommendation of the six, but a real architecture, not a
  guess.

*Do not submit any of the four zero-output systems* (`ali_deepresearch`,
`claude-code-research`, `codex_cli_research`, `o3_deep_research`) --
hedging against evaluation-method uncertainty is not the same as
submitting an unimplemented scaffold with no evidence at all; the former
covers a known unknown (which axis the judge weights), the latter is a
pure guess with zero information behind it. That leaves 4 of the 10
slots open if the organizers' rules reward using fewer, more confident
entries, or as headroom for a genuinely new system built later.

== Submission log: all 6 systems run on the 119-topic official test set

All six recommended systems now have a complete official test-set run and
an exported organizer JSONL, not just the exp15/dev-scale evidence §10.2
ranks them on. `aus_agent`/`aus_agent_v2` were prepared and submitted in an
earlier session (`worklogs/2026-08-07-test119-production-runs.md`,
2026-08-07); the remaining four were prepared the following day
(`worklogs/2026-08-08-test119-*-submission.md`).

#figure(
  text(size: 7.6pt)[#table(
    columns: (2.6cm, 2.6cm, 1.2cm, 1.6cm, 1.5cm, 6.1cm),
    align: (left, left, center, right, right, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 4.5pt,
    table.header([*System*], [*Organizer run tag*], [*Topics*], [*\$/topic*], [*Total*], [*Notes*]),
    [`aus_agent_v2`], [`sol-aus-v2-research-first-test119-20260807`], [119/119], [n/a], [n/a], [Refs/topic 10--40 (mean 27.67); words/topic 731--1024 (mean 936.55); 3,732 searches, 507 commits total. Per-topic token logs from that session are not present on this machine, so no \$ figure can be re-derived here (§7's own logs-only fragility caveat, now realized) -- its README's \$1,096.72 is total tracked BUILD cost across many rounds, not this run's generation cost, and should not be read as one.],
    [`aus_agent`], [`sol-aus-default-test119-20260807`], [119/119], [n/a], [n/a], [Sol default method. Refs/topic 7--51 (mean 27.87); words/topic 497--1022 (mean 882.50); 2,849 searches, 473 commits total. 2 of 119 topics failed once (`400 validation_error`, transient gateway error) and were resumed cleanly. Same token-log gap as `aus_agent_v2`.],
    [`brief_revise_agent` base], [`brief-base-t119`], [119/119], [\$1.638], [\$194.91], [Refs/topic 5--43 (mean 25.8); words/topic 554--1007 (mean 830.2); mean 26.4 searches/topic. 3 launches needed -- see rate-limit note below.],
    [`brief_revise_agent` hybrid], [`brief-hybrid-t119`], [119/119], [\$1.503], [\$178.87], [Refs/topic 8--47 (mean 24.7); words/topic 609--1001 (mean 834.3); mean 22.6 searches/topic -- fewer than the base cell's 26.4, confirming §7's per-topic finding at test-set scale too. 8% cheaper than base.],
    [`facets_agent`], [`facets-t119`], [119/119], [\$0.724], [\$86.18], [Refs/topic 4--25 (mean 13.6); words/topic 178--1018 (mean 613.0); mean 11.7 searches/topic. Single clean pass, no rate-limit issues (finished before the other two OpenAI jobs it ran alongside hit sustained 429s).],
    [`facet_rag`], [`facetrag-t119`], [119/119], [\$0.178], [\$21.21], [Refs/topic 7--21 (mean 13.9); words/topic 142--802 (mean 388.9, shortest of all six -- consistent with §10.2's own prior finding). Real Bedrock rate (not the OpenAI placeholder) -- an order of magnitude cheaper than any OpenAI-backed system despite the highest search count (mean 33.7/topic).],
  )],
  caption: [All six recommended systems' official 119-topic test runs. \$ figures use the same placeholder OpenAI rate and real Bedrock rate-card as §7 (generation only, no judging). Total across the four systems with a computable figure: *≈\$481.17*.],
) <tab-submissions>

*Two new, real findings from running at test-set scale, not exp15 scale:*

+ *The shared OpenAI gateway quota cannot sustain 3 systems' concurrency-6
  traffic at once.* Launching `brief_revise_agent` base, `brief_revise_agent`
  hybrid, and `facets_agent` simultaneously (all `gpt-5.6-*` models sharing
  one `westus` Azure OpenAI quota) produced sustained `429` rate-limit
  errors that exhausted the client's own retry budget on a growing fraction
  of topics per pass -- 76 of 119 failed on the first combined launch. Two
  resume passes at falling concurrency (6 → 3 → 2, the last one run alone)
  were needed before both `brief_revise_agent` variants reached 119/119.
  `facet_rag` (Bedrock) was unaffected throughout, confirming the
  bottleneck was the shared OpenAI quota specifically, not a per-system
  problem. Future multi-system test-set batches on this gateway should
  serialize OpenAI-backed systems, or hold combined concurrency near what
  one system alone was already shown safe at (6), not multiply it.
+ *A real submission-format gap survived this report's own validator.* The
  third-party `autojudge_base` tool's `rag26` spec check (independent of
  this repo's `validate_rag_output`) caught `run_id_max_len=20` (a NIST
  run-tag convention) -- every one of this report's own internal run_ids is
  intentionally longer and more descriptive for bookkeeping across dozens
  of experiment cells (`brief-revise-hybrid-test119-20260808` = 37 chars).
  `scripts/export-rag-submission.py` gained `--output-run-id` to rewrite
  only the organizer-facing tag, leaving internal artifacts untouched; all
  four new submissions now validate 119/119 against `rag26`. *The two
  already-submitted `aus_agent`/`aus_agent_v2` files were not re-checked or
  re-tagged against this rule* (`sol-aus-v2-research-first-test119-20260807`
  is 43 characters, `sol-aus-default-test119-20260807` is 33 -- both over
  the limit if it applies) -- open, not yet resolved.

== Organizer-baseline arena: `aus_agent`/`aus_agent_v2` beat the official baseline

Separately from this report's own arena work (§5, always against
`aus_agent_v2` as the opponent), a native RAGDoll arena run
(`worklogs/2026-08-07-ragdoll-arena-sol-runs-vs-organizer-baseline.md`,
2026-08-07) compared both already-submitted test119 files against the
organizer's own *Sol agentic-search BM25* baseline
(`gpt-5.6-sol_medium_agentic-search_bm25_output-mode-answer.jsonl`, shipped
in the official data submodule) -- the first evidence in this repo of how
these systems perform against a baseline the organizers themselves built,
not just against each other.

#figure(
  table(
    columns: (5.4cm, 2.6cm, 2.6cm, 2.6cm),
    align: (left, center, center, center),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 5.5pt,
    table.header([*Matchup*], [*Result (A/B/tie)*], [*Preference*], [*Robust to position?*]),
    [organizer baseline vs `aus_agent_v2`], [10 / 108 / 1], [*91.2%* ours], [Yes],
    [organizer baseline vs `aus_agent`], [11 / 107 / 1], [*90.3%* ours], [Yes],
    [`aus_agent_v2` vs `aus_agent`], [67 / 51 / 1], [56.7% v2], [*No* -- 0.38 as A, 0.77 as B],
  ),
  caption: [RAGDoll native `arena compare-all`, 357 judgments (119 topics × 3 pairs), `mantle/openai.gpt-5.6-luna` judge, seed 13, `PAIRWISE_ANSWER_COMPARISON_NAIVE`. Ties count half in preference. Arena-rank leaderboard: `aus_agent_v2` 1154, `aus_agent` 1111, organizer baseline 735.],
) <tab-organizer-arena>

Both submitted systems beat the organizer's own baseline decisively and
*robustly to display position* -- the position audit
(`worklogs/assets/2026-08-07-ragdoll-arena-position-audit.py`) shows the
preference holds regardless of which side of the pair each system is shown
on. The `aus_agent_v2`-vs-`aus_agent` result is the opposite case: it swings
from 0.38 to 0.77 preference depending on display position, so the 56.7%
aggregate should *not* be read as evidence `aus_agent_v2` is really the
stronger of the two -- exactly the kind of judge artifact this report's own
§6 already warns about, now demonstrated on a third, independent judge
pass. Judging cost: 357 raw Pi events, ≈\$2.23 total (real Bedrock `us-east-1`
Luna rates, \$1.10/M input + cache-write, \$6.60/M output).

This section's own cost-effectiveness data feeds §10.6, which extends the
same organizer-baseline comparison to the other 4 submitted systems.

== Organizer-baseline arena, extended: two of the four hedge picks lose to it

Extending §10.5's comparison to the four systems prepared 2026-08-08
(`brief_revise_agent` base, `brief_revise_agent` hybrid, `facets_agent`,
`facet_rag`) --
`worklogs/2026-08-09-ragdoll-arena-5way-organizer-baseline.md`, full
reproduction detail (exact commands, environment setup, two new Pi
config gotchas not documented before) in that worklog and §12.

*Scope constraint:* `aus_agent`/`aus_agent_v2`'s test119 submission files
are not present on this machine (a data-sync gap, not a re-run decision --
confirmed absent from both `data/outputs/submissions/` and the internal
per-topic artifacts). This is therefore a *5-way* comparison (organizer
baseline + the 4 new systems, $binom(5,2)=10$ pairs), not the 7-way
comparison §10.5 priced -- `aus_agent`/`aus_agent_v2`'s own
organizer-baseline numbers remain §10.5's separate 3-pair result, not
re-merged into one leaderboard here.

Same 119 official test topics, same judge (`mantle/gpt-5.6-luna`, thinking
`medium`), same seed (13), same native RAGDoll `arena compare-all` --
methodology identical to §10.5 (§12 gives the exact prompt and
every hyperparameter). 1,190/1,190 judgments completed (10 pairs × 119
topics), 0 errors, 0 duplicate task ids.

#figure(
  text(size: 7.6pt)[#table(
    columns: (3.6cm, 3.6cm, 2.6cm, 2.6cm),
    align: (left, left, center, center),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 5pt,
    table.header([*Run A*], [*Run B*], [*A / B / tie*], [*Preference*]),
    [organizer baseline], [`brief-base-t119`], [19 / 99 / 1], [*83.6%* B],
    [organizer baseline], [`brief-hybrid-t119`], [18 / 101 / 0], [*84.9%* B],
    [organizer baseline], [`facets-t119`], [105 / 13 / 1], [*88.7%* A -- baseline wins],
    [organizer baseline], [`facetrag-t119`], [119 / 0 / 0], [*100%* A -- baseline wins],
    [`brief-base-t119`], [`brief-hybrid-t119`], [57 / 58 / 4], [50.4% B -- not robust, see below],
    [`brief-base-t119`], [`facets-t119`], [114 / 4 / 1], [96.2% A],
    [`brief-base-t119`], [`facetrag-t119`], [119 / 0 / 0], [100% A],
    [`brief-hybrid-t119`], [`facets-t119`], [116 / 2 / 1], [97.9% A],
    [`brief-hybrid-t119`], [`facetrag-t119`], [119 / 0 / 0], [100% A],
    [`facets-t119`], [`facetrag-t119`], [118 / 1 / 0], [99.2% A],
  )],
  caption: [All 10 pairs, 119 topics each, native RAGDoll `arena compare-all`, seed 13. Arena-rank leaderboard: `brief-hybrid-t119` 1487, `brief-base-t119` 1477, organizer baseline 1196, `facets-t119` 849, `facetrag-t119` -10.],
) <tab-5way-arena>

*Both `brief_revise_agent` variants clearly beat the organizer baseline
(83.6%/84.9%). `facets_agent` LOSES to it (88.7% baseline preference).
`facet_rag` loses to everything it was compared against, including the
baseline, 100% of the time.* This is real, new evidence that two of this
report's six recommended submissions -- exactly the two included as
architectural-diversity/evaluation-method hedges (§10.3), not on strength
of score -- would likely lose against the organizers' own reference system
specifically, not just against this repo's other systems. It does not
change the §10.3 recommendation (the hedging rationale was never "these
will win"), but it is the clearest evidence yet of how large that gap
really is.

The position audit (same script as §10.5,
`worklogs/assets/2026-08-07-ragdoll-arena-position-audit.py`) shows every
organizer-baseline pairing is *robust to display position* -- e.g.
`brief-base-t119` beats the baseline 77.6% as A and 87.9% as B, same
winner both ways. The one pair whose winner *flips* with position is
`brief-base-t119` vs `brief-hybrid-t119` (34.5% as A, 63.9% as B) -- the
near-tie 49.6%/50.4% aggregate should not be read as evidence either
variant beats the other, the same caution §6 and §10.5 already raise for
close pairs on other judge passes.

*Cost: 1,190 judgments, \$5.91 total* -- read directly from RAGDoll's own
per-judgment `cost_usd` (real committed Luna rates were configured this
time, unlike §10.5's zero-valued placeholder that needed manual
recomputation) -- cheaper than the \$7.43 estimate in an earlier revision
of this section, because `facets_agent`/`facet_rag`'s shorter answers
(§10.4) reduced average judgment cost below the rate that estimate was
based on, exactly as predicted.

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

*Submission log* (§10.4): organizer-ready files under
`data/outputs/submissions/<tag>/rag_output_trec_rag_2026.jsonl` for all six
recommended systems. Full per-system detail (exact commands, checksums,
validation output, the rate-limit and `run_id_max_len` incidents):
`worklogs/2026-08-07-test119-production-runs.md` (`aus_agent`/
`aus_agent_v2`), `worklogs/2026-08-08-test119-brief-revise-base-submission.md`,
`worklogs/2026-08-08-test119-brief-revise-hybrid-submission.md`,
`worklogs/2026-08-08-test119-facets-agent-submission.md`,
`worklogs/2026-08-08-test119-facet-rag-submission.md`.

*Organizer-baseline arena* (§10.5, §10.6): Kun Ran,
`worklogs/2026-08-07-ragdoll-arena-sol-runs-vs-organizer-baseline.md`
(`aus_agent`/`aus_agent_v2`, 2-system); this session,
`worklogs/2026-08-09-ragdoll-arena-5way-organizer-baseline.md` (the other
4 systems, 5-way, including the exact reproduction gotchas -- also see
§12). Raw RAGDoll artifacts (`tasks.jsonl`, `judgments.jsonl`,
`pairwise.csv`, `coverage.csv`, `leaderboard.csv`, `raw-events/`) under
`data/outputs/ragdoll-arena/sol-test119-vs-organizer-sol-agentic-bm25-20260807/`
and `data/outputs/ragdoll-arena/test119-5way-vs-organizer-baseline-20260809/`
respectively, on the machines that generated them -- not present on every
synced copy of `data/outputs/` (see `CLAUDE.md`'s data-sync notes).

= Appendix: organizer-baseline arena reproducibility <app-reproduce>

Full detail to reproduce §10.5/§10.6 independently -- topics, exact judge
prompt, and every hyperparameter. §4--§9's own standalone/arena evaluation
(`gpt-5.6-terra` judge, `evaluation-results/factorial/`) uses different
topics (the 15-topic `exp15` set, §4.5) and a different prompt/harness
entirely -- this appendix covers *only* the organizer-baseline arena work
in §10.5/§10.6, not the rest of the report.

== Topics

All organizer-baseline arena judgments (§10.5, §10.6) use the *official
119-topic TREC RAG 2026 test set*, not `exp15`:

```
data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv
```

119 rows, ids `rag2026-0` through `rag2026-118`, SHA-256
`72dc2fd358d3eeda973397ccd7a8775545b19a6deaefc67709167eee6a9f8a2c`. Every
pair in both §10.5 and §10.6 was judged on all 119 shared topics -- no
sampling, no per-pair topic subsetting.

== Judge prompt (verbatim)

Native RAGDoll `PAIRWISE_ANSWER_COMPARISON_NAIVE`
(`evaluation/ragdoll/src/ragdoll/arena/prompts.py`, pinned commit
`1f0671908ab6dc581a61648463e3566ba413b480`), system prompt empty. Not the
rubric-guided variant (`PAIRWISE_ANSWER_COMPARISON_W_RUBRICS`) -- test
topics carry no organizer rubrics, so the rubric-guided prompt does not
apply here.

#block(
  fill: rgb("#f7f6f2"), inset: 10pt, radius: 3pt, width: 100%,
  text(size: 8pt, font: "DejaVu Sans Mono")[
You are judging two assistant answers to the same user question. Read the user's question and both answers carefully, infer what the user is trying to accomplish, and choose the answer the user would rather receive.

This is a preference judgment, not a checklist. Judge each answer by the qualities that matter for this specific request. Prefer the answer that is more useful, better matched to the user's intent, more complete where completeness matters, and more trustworthy.

Do not apply a generic preference for short answers, long answers, polished wording, or rigid formatting. A longer answer can be better when the added content is relevant and useful. A shorter answer can be better when it answers the user's need directly without omitting important information.

Consider the following dimensions when relevant: intent and style match, directness, usefulness, completeness, specificity, accuracy and plausibility, calibration, explanation quality, recommendation quality, organization, noise control.

Prefer the answer with greater useful substance for the user's actual need. Do not reward brevity, fluency, confidence, or formatting by itself.

Choose A or B only when one answer's advantage is meaningful to the user, not merely detectable on close inspection. If the differences are minor or unlikely to affect which answer the user would prefer, choose [[Tie]]. Choose [[Tie (Both Bad)]] when both answers substantially fail the user's core need, even if one is marginally less bad.

Output your final verdict by strictly following this format:
"[[A]]" if Assistant A is better,
"[[B]]" if Assistant B is better,
"[[Tie]]" if they are effectively tied and both are at least acceptable,
"[[Tie (Both Bad)]]" if they are effectively tied because both are bad.

Do not include any explanation, reasoning, or additional text outside the verdict.

[The Start of User's Question] \{query\} [The End of User's Question]

[The Start of Assistant A's Answer] \{answer\_a\} [The End of Assistant A's Answer]

[The Start of Assistant B's Answer] \{answer\_b\} [The End of Assistant B's Answer]
  ]
)

The full 11-dimension bulleted list (intent/style match, directness,
usefulness, completeness, specificity, accuracy/plausibility, calibration,
explanation quality, recommendation quality, organization, noise control --
each with its own one-sentence definition) is condensed above for space;
the verbatim, unabridged prompt lives at
`evaluation/ragdoll/src/ragdoll/arena/prompts.py`. `{query}`, `{answer_a}`,
`{answer_b}` are substituted per-battle; `answer_a`/`answer_b` are each
system's `answer[].text` sentences concatenated, with no citation markers
(both harnesses already emit citation-free `answer[].text` in the
organizer schema) and no references block rendered into the prompt.

== Hyperparameters

#figure(
  table(
    columns: (5cm, 10cm),
    align: (left, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 5.5pt,
    table.header([*Parameter*], [*Value*]),
    [Judge model], [`mantle/gpt-5.6-luna` (Azure OpenAI-compatible gateway, `openai-responses` API, same credential/endpoint as every other `gpt-5.6-*` call in this report)],
    [Thinking level], [`medium`],
    [Temperature], [not set (provider default)],
    [Context window], [272,000 tokens (configured; not necessarily exercised per-call)],
    [Max output tokens], [8,000],
    [Cost rates (§10.6 only)], [\$1.10/M input, \$6.60/M output, \$1.10/M cache-read, \$1.10/M cache-write -- real committed `us-east-1` Luna rates, not a placeholder],
    [Sampling / battle order], [One deterministic randomized A/B order per `(pair, qid)`, seed 13 -- native `compare-all` semantics, not the older custom wrapper's duplicate reverse-order calls],
    [Topics per pair], [All 119 (no `--sample-topics-per-pair`, no `--sample-battles-*` flags on the full runs -- those flags were used only for the 1-topic-per-pair preflight, seed 13)],
    [Max concurrency], [8],
    [Timeout], [300s per judgment],
    [RAGDoll commit], [`1f0671908ab6dc581a61648463e3566ba413b480` (`github.com/castorini/RAGDoll`, `main`, confirmed current as of both run dates)],
    [Pi CLI version], [0.84.0 (§10.5, Kun's run) / 0.83.0 (§10.6, this session's run) -- see `worklogs/2026-08-09-ragdoll-arena-5way-organizer-baseline.md` for why this difference is not expected to matter],
    [Tie handling], [`Tie` and `Tie (Both Bad)` both count as 0.5 preference to each side in aggregate preference-rate figures, matching RAGDoll's own convention],
  ),
  caption: [Every hyperparameter governing the organizer-baseline arena judgments in §10.5 and §10.6.],
)

= Addendum: `open_weight_agent`, an open-weight-only system (2026-08-09)

#text(style: "italic")[Renamed post-hoc (2026-08-10) from `oss_agent` to `open_weight_agent`, to avoid a naming collision with the `gpt-oss-120b` model -- not even this system's default model. Worklog filenames below (e.g. `2026-08-09-oss-agent-open-weight-system.md`) are historical and were not renamed.]

Added after this report's original session (§1-§11 above), on a separate
\$200 budget, per an explicit constraint the earlier sessions never
applied: every model in the pipeline must be open-weight (no
`gpt-5.6-*`, no proprietary Bedrock model). Full narrative and raw
run-ids in `worklogs/2026-08-09-oss-agent-open-weight-system.md`; only
the headline evidence is reproduced here, matching this report's own
figures for direct comparison.

Built from the two systems this report itself ranks highest (§10.2-10.3):
`brief_revise_agent`'s architecture (pre-flight requirements brief +
review/revise pass over the shared `agent_harness` loop, ties
`aus_agent_v2` on standalone rubric at ~1/50th the cost) as the base,
plus one structural idea ported from `aus_agent_v2` (this report's best
arena performer): its blind obligation-scout stage
(`plan_critic.py`), newly isolated as taxonomy factor *S14* -- it had
never been A/B'd on its own before, since `aus_agent_v2` ships it
unconditionally. S5 (adjacent-page augmentation) and S6 (`hybrid`-only
retrieval) are adopted as defaults from this report's own §4.2/§4.6
findings.

Three open-weight Bedrock models confirmed usable under this account
(`openai.gpt-oss-120b-1:0`, `qwen.qwen3-next-80b-a3b`,
`moonshot.kimi-k2-thinking`) were bake-off'd as the main writer model on
the SAME 15-topic dev subset this report's own hill-climb tuned on (the
qids of `br-model-main-sol-exp15-b1`), scored with the identical
standalone-rubric protocol (§2.2, `gpt-5.6-terra` judge):

#figure(
  table(
    columns: (auto, auto, auto, auto),
    align: (left, left, right, right),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 6pt,
    table.header([*Model (main writer)*], [*Topics*], [*Standalone overall*], [*Reliability*]),
    [*`qwen.qwen3-next-80b-a3b` (winner)*], [15/15], [*1.200*], [clean on first attempt, default round cap],
    [`openai.gpt-oss-120b-1:0`], [15/15], [1.200], [needed round cap raised 30\->100, plus one retry for a transient harness `KeyError`],
    [`moonshot.kimi-k2-thinking`], [14/15], [1.071], [one topic reproducibly failed/hung across three attempts],
  ),
  caption: [`open_weight_agent` open-weight model bake-off, same 15 topics and judge protocol as §4.],
)

Two ablations against the qwen-based default (same 15 topics): the new
S14 blind-scout stage ties on the holistic score (1.200 either way) but
moves `Implicit Criteria` specifically (0.694 with it on vs. 0.571 off,
the report's own axis-breakdown methodology from §4.5 applied to a new
factor) -- kept on. S5 (adjacent-page augmentation) is decisively
confirmed for qwen, dropping the score to 0.800 when disabled (-0.400,
far past this report's own $plus.minus 0.067$ noise floor) -- a larger
effect than this report's own qwen-specific S5 result on
`brief_revise_agent` (-0.133, §4.2), same direction.

*Reading the result against §4.2/§7's own claim that generator-model
choice is the dominant standalone-score factor*: `open_weight_agent`'s best
open-weight configuration (1.200) does not close the gap to any
`gpt-5.6-*` main model tested in this report (1.867-2.267) -- consistent
with, not a contradiction of, this report's own finding that once a
weaker generator model is fixed, structural levers move an order of
magnitude less. `open_weight_agent` is not a competitive submission candidate
against `aus_agent_v2`/`brief_revise_agent` on this evidence; it is a
demonstration that this report's own taxonomy-informed architecture
transfers to an all-open-weight pipeline, at roughly \$0.16/topic
generation cost (the qwen bake-off cell's own token count, same
placeholder Bedrock rate §7 uses) -- an order of magnitude below even
`brief_revise_agent`'s own \$1.29/topic base-cell figure.

*Correction to a claim made when this addendum was first drafted, caught
while preparing a follow-up deep-research prompt and worth recording
here rather than silently fixing*: the LLM-generated-snippet rejection
above (and in `open_weight_agent`'s own README/worklog) leaned on §4.5's
project-wide finding that References \& Citation Quality is the weakest
rubric axis in every cell scored -- true in aggregate across this
report's 30 proprietary-model cells, but pulling `open_weight_agent`'s own
per-axis numbers (same 15 topics, same judge) against its two
proprietary progenitors shows the opposite for THIS system specifically:

#figure(
  table(
    columns: (auto, auto, auto, auto),
    align: (left, right, right, right),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 6pt,
    table.header([*Axis (0--2)*], [*`open_weight_agent` qwen*], [*sol baseline*], [*`aus_agent_v2`*]),
    [Communication Quality], [0.633], [0.733], [0.833],
    [Explicit Criteria], [1.239], [1.450], [1.505],
    [*Implicit Criteria*], [*0.694*], [*0.988*], [*1.100*],
    [Instruction Following], [0.875], [1.000], [1.188],
    [*Synthesis of Information*], [*0.590*], [*0.795*], [*1.000*],
    [References \& Citation Quality], [*0.667*], [0.222], [0.000],
  ),
  caption: [`open_weight_agent` (qwen) vs. its two proprietary progenitors, same 15 topics, same judge, `n` per axis identical across all three (30/109/170/16/39/9 -- same topics, same rubric file).],
)

Citation Quality is `open_weight_agent`'s single BEST-scoring axis, beating both
proprietary baselines outright (n=9 is small, but a gap this size in the
favorable direction is a specific signal, not noise) -- the opposite of
what the project-wide aggregate would suggest applies here. The two axes
carrying the real gap are Implicit Criteria (largest, +0.294) and
Synthesis of Information (+0.205). The decision not to adopt LLM-
generated snippets still stands (no positive evidence exists either way,
and the documented citation-support regression elsewhere in this report
remains a real risk on principle), but the STATED REASON for it should
be read as weaker than originally written, and future work on this
system should prioritize Implicit Criteria and Synthesis, not citation
mechanisms, per this corrected reading. Full context:
`worklogs/assets/2026-08-09-oss-agent-deep-research-prompt.md`.

== Round 2: extended model bake-off -- `zai.glm-5` wins, adopted as default

A deep-research request (`worklogs/assets/2026-08-09-oss-agent-deep-
research-prompt.md`) sent to `gpt-5.6-sol` and Gemini Deep Research,
reviewed against a REAL Bedrock model-catalog check (`boto3
bedrock.list_foundation_models`, not a guess), surfaced several more
open-weight models already enabled on this account. Same 15-topic set,
same judge protocol:

#figure(
  table(
    columns: (auto, auto, auto),
    align: (left, right, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 6pt,
    table.header([*Model*], [*Standalone overall*], [*Notes*]),
    [`qwen.qwen3-next-80b-a3b` (round-1 winner)], [1.200], [],
    [`openai.gpt-oss-120b-1:0`], [1.200], [],
    [`deepseek.v3.2`], [1.200], [tied, after fixing an AWS-token-expiry contamination],
    [`moonshotai.kimi-k2.5`], [1.333], [],
    [`qwen.qwen3-235b-a22b-2507-v1:0`], [0.867], [WORSE than the smaller round-1 model, confirmed on clean data],
    [`us.meta.llama3-3-70b-instruct-v1:0`], [excluded], [0 tool calls across 4 rounds under this harness's Converse schema],
    [*`zai.glm-5`*], [*1.467*], [*winner, replicated at 1.333 on an independent 15-topic set (+0.467 there, larger than +0.267 on the tuning set)*],
  ),
  caption: [Round-2 open-weight model bake-off, same 15 topics and judge protocol as the round-1 table above.],
)

`agent.DEFAULT_MODEL` changed to `zai.glm-5`. A bigger, newer model
(`qwen3-235b`) scoring worse than a smaller one it should supersede is a
real, useful negative result in its own right, not just noise --
parameter count is not a reliable proxy for this task/harness
combination.

== Tier-2 build round: two architecture attempts, both rejected

Full 7-turn review transcript (`gpt-5.6-sol` plus Claude Opus 4.8,
standing in for Claude Fable 5 which turned out to be blocked by an
RMIT AWS Organizations Service Control Policy -- confirmed unfixable
from this account, no permission even to read the policy) in
`worklogs/assets/2026-08-09-oss-agent-sol-plan-review.md`. Both
reviewers converged on building an evidence-grounded synthesis compiler
first (a validated report blueprint before the final prose pass,
replacing the review pass rather than stacking with it): a 15-topic
pilot scored *0.933 vs. 1.467* for the plain baseline -- both target
axes (Implicit Criteria, Synthesis) moved the WRONG direction, plus a
sharp Communication Quality and Citation Quality collapse.

Both reviewers independently converged again, reading that failure
signature as "any mechanism that REPLACES the model's own organic
synthesis loses" -- the only pattern either still trusted was additive
correction layered on the model's own draft. A second, narrower
mechanism (widen the existing review pass to also grade the blind
scout's obligations, reusing it completely unmodified) scored *1.267
vs. 1.467* -- Synthesis improved (+0.205) but Implicit Criteria, the
axis this specifically targeted, moved the WRONG way (-0.165), and
Citation Quality collapsed again (-0.334).

Both reviewers then caught the same gap in the running interpretation:
every comparison so far measured against a baseline that ALREADY
carries an always-on review pass, never itself ablated. A third,
subtractive pilot (`--no-review`, review pass off entirely) resolved
this definitively: Citation Quality does not rise with no review at
all -- it collapses to *0.000* (vs. 0.556 baseline), the worst
citation result of any variant tested. The always-on review pass was
PROTECTING citation quality the whole session, not costing it; neither
Tier-2 attempt failed because "revision hurts this model" in general.

*Final verdict: ship the plain baseline unchanged* -- `zai.glm-5` in
every role, `hybrid`-only retrieval, adjacent-page augmentation on,
blind scout on, unmodified review pass grading brief requirements only.
Standalone overall: *1.467/3*, the same number round 2's bake-off
already established. Both new mechanisms are kept in the codebase, off
by default, as validated negative results -- this round's own
deliverable is three decisive negative findings plus one clean
positive-control confirmation, not a score improvement. Total
additional spend this round (bake-off + three 15-topic pilots +
consultation): roughly \$120-150, against a separately-raised \$300
cumulative budget for this whole open-weight workstream.

== Test119 submission prepared

The plain baseline (`zai.glm-5`, no non-default flags) was run on the
full official 119-topic test set and exported for submission --
`worklogs/2026-08-09-test119-oss-agent-submission.md` has the complete
account. 119/119 completed (one resume pass needed for 2 topics that hit
the same transient shared-harness `KeyError` seen during dev-set work),
0 `validate_rag_output` violations, organizer-facing run tag
`owa-glm5-t119` (renamed post-hoc from `oss-glm5-t119`, see the worklog's
"Update (2026-08-10)" section). Real metered Bedrock cost: *\$0.163/topic, \$19.35 total*
-- roughly 1/10th `brief_revise_agent`'s own test119 figure (§10.4,
\$1.638/topic).
