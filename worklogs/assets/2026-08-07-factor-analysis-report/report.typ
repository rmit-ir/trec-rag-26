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

  #text(size: 9.5pt, fill: muted)[2026-08-07 -- 15-topic TREC RAG 2026 dev subset -- 21 scored cells -- \$340 of \$400 budget]
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
  *Result: did not beat `aus_agent_v2`.* The best configuration found --
  gpt-5.6-sol as main generator, round-B adjacent-page fetch on, gpt-5.6-luna
  as brief-analyst and reviewer, $k=10$, iteration-1 structure -- scores
  *2.267/3* on standalone rubric grading (§4, the best of every cell tested)
  but still loses to `aus_agent_v2` in a head-to-head arena match (§5),
  *18--12 (60/40)*, order_consistency 0.733 (4W--7L clean, 4
  non-order-consistent). §6 compares the two evaluation modes directly.
  Eleven further single-factor moves against the standalone base -- five
  generic `agent_harness` toggles, one factor interaction, three
  brief-analyst model swaps, adjacent-fetch removal, and a novel post-draft
  "closure critic" mechanism -- returned zero improvements (§4.2). $k$ and
  the reviewer model were held fixed throughout and were never themselves
  varied as a factor. Of the 16 factors in the underlying taxonomy (§3), 8
  were empirically scored this session; the base cell is a confirmed local
  optimum *on the factors actually tested*, not a claim about the full
  factor space.
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
all 21 cell comparisons and all 11 hill-climb moves this session. Answer
text is truncated to 16,000 characters before grading
(`rubric_scorecard_aus_agent_vs_facets_agent.py`); no answer scored this
session was observed to hit that cap, but it is not independently verified
for every cell.

*Pairwise arena (confirmatory, §5).* One head-to-head judge call
(`gpt-5.6-terra`), both presentation orders, comparing two full answers on
the same topic and declaring a win/loss/tie -- run once this session,
standalone-best cell vs. `aus_agent_v2`, as the direct test of the actual
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
primary tuning signal -- it drove every one of the 21 cell comparisons and
all 11 hill-climb moves below. Arena (pairwise, confirmatory) is a
completely separate protocol, reported on its own in §5.

== All scored cells

@fig-allcells ranks every one of the 21 cells scored this session by
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
  caption: [Standalone rubric overall score, all 21 cells, sorted. Base cell in blue. #link("interactive/fig1_all_cells.html")[#text(fill: accent)[Interactive version →]]],
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
cell scored this session* (mean 0.196/2 across all 21 cells, range
0.00--0.67) -- independent of generator model, structural configuration, or
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

= Pairwise (arena) evaluation

This section is a completely separate protocol from §4: a head-to-head
judge call (`gpt-5.6-terra`), both presentation orders, comparing two full
answers on the same topic and declaring win/loss/tie (§2.2) -- no per-
criterion rubric grades, no 0--3 scale, no shared noise-floor unit with §4.
Exactly one arena batch was run this session: the standalone-best cell
(base, 2.267 from §4.1) against `aus_agent_v2`, on the same 15 topics, as a
confirmatory check on the actual competitive objective rather than a tuning
signal (no other cell was arena-tested).

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
    [Role this session], [Primary -- drove all 21 cells and 11 hill-climb moves], [Confirmatory -- one batch only, base cell vs. `aus_agent_v2`],
    [Base cell's result], [*2.267/3* -- best of 21 cells tested], [*40%* win rate vs. `aus_agent_v2` (18--12 pooled; 4W--7L clean)],
  ),
  caption: [Standalone vs. arena, same base cell, same 15 topics.],
)

The base cell is the best standalone-rubric cell found and beats the fair
(round-B-inclusive) luna comparison cell by 0.4 points (2.267 vs. 1.867,
`br-luna-current-code-exp15`, §4.1), yet loses the majority of arena battles
against `aus_agent_v2` (§5.1). Whatever makes `aus_agent_v2` win head-to-head
-- plausibly completeness, coverage breadth, or claim density -- is not
fully captured by the official rubric's per-criterion grading.

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

Practically: standalone score is necessary-but-not-sufficient evidence for
this system. It is the right tool for cheap, high-resolution hill-climbing
(§4), but a standalone win is not a reliable predictor of an arena win, and
any future claim that a configuration "beats" `aus_agent_v2` should be
checked against arena before being trusted, not inferred from a standalone
delta alone.

= Recommendation

Use the base cell (gpt-5.6-sol, round-B structure, $k=10$, luna
brief-analyst/reviewer) as `brief_revise_agent`'s standing configuration --
it is the best cell found among the 21 scored (§4.1), and the eleven-move
search around it on the tested factor set (§4.2 @tab-moves) is exhausted. It
is not yet competitive with `aus_agent_v2` head-to-head (§5, §6). Untested
factors that remain open questions, not ruled out: S7 (`search_k`, held at
10 throughout), M3 (reviewer model, never varied), S2/S3/S13
(schema/word-budget/screener variants, each tested in a different thread
against a different baseline, not against the current sol base), and S8
(`search_result_filter`, not wired -- would need a `requirement`-carrying
search-tool schema first). Closing the arena gap most likely needs either
(a) a structural change genuinely distinct from anything tried this session
(e.g. a multi-candidate/ensemble mechanism, explicitly out of scope here per
the brief to diverge from `aus_agent_v2`'s own architecture rather than
re-derive it), or (b) treating `brief_revise_agent` as the lighter, cheaper
alternative and reserving `aus_agent_v2` for submissions where its cost is
affordable.

= Budget

The judging/generation budget cap was raised mid-session from an original
\$50+\$50 split to \$400 once §4.1's model-effect result made further
hill-climbing look worthwhile (§2, Constraint discovered mid-session).

#figure(
  table(
    columns: (auto, auto, auto),
    align: (left, right, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 6pt,
    table.header([*Line item*], [*Cost*], [*Basis*]),
    [OpenAI generation (terra/sol/luna, ≈55.6M tokens)], [\$278], [estimate -- placeholder \$5/1M rate, no real metered rate card for gpt-5.6-\*],
    [Bedrock (gpt-oss-120b + qwen)], [\$2.76], [real -- metered rate-card files],
    [Sol design/thinking calls (7 calls)], [\$1.01], [real -- exact printed API cost],
    [Standalone + arena judging (≈390 calls)], [\$58], [estimate],
    table.hline(),
    [*Total*], [*≈\$340*], [of the \$400 cap; ≈\$60 unspent],
  ),
  caption: [Final cost breakdown. The OpenAI generation line is the single largest source of estimate uncertainty in this total.],
)

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
generic-factor CLI flags -- all on branch
`explore/new-agent-framework-system`.
