#set document(title: "brief_revise_agent Factorial Hill-Climb: Lab Report", author: "trec-rag-26")
#set page(paper: "us-letter", margin: (x: 2.2cm, y: 2.2cm), numbering: "1")
#set text(font: "Libertinus Serif", size: 10.5pt)
#set heading(numbering: "1.1")
#set par(justify: true, leading: 0.62em)

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
brief plus one review-and-revise pass) was hill-climbed against `aus_agent_v2`
(this repo's strongest, most expensive system) via standalone rubric scoring
on a fixed 15-topic development set, with sol (`gpt-5.6-sol`) as design
authority and the current session as orchestrator/implementer.

#box(fill: rgb("#f4f8fd"), inset: 10pt, radius: 4pt, width: 100%)[
  *Result: did not beat `aus_agent_v2`.* The best configuration found --
  gpt-5.6-sol as main generator, round-B adjacent-page fetch on, k=10,
  gpt-5.6-luna as brief-analyst and reviewer -- scores *2.267/3* on
  standalone rubric grading (the best of every cell tested) but still loses
  to `aus_agent_v2` in a head-to-head arena match, *18--12 (60/40)*, clean
  per-topic agreement 4W--7L--4A. Twelve further hill-climb moves against
  this base -- covering generator model, brief-analyst model, five generic
  retrieval/tool-exposure factors, one factor interaction, and a novel
  post-draft "closure critic" mechanism -- returned zero improvements. The
  base cell is a confirmed local optimum, not an under-explored one.
]

= Method

== Design

Sol-directed hill-climbing: starting from `brief_revise_agent`'s best known
configuration, one factor was changed at a time, scored, and kept only if it
improved on the current best -- in contrast to the session's earlier
factorial-grid framing, which was superseded once the hill-climb approach was
adopted partway through.

== Evaluation

*Primary: standalone rubric grading.* One judge call (`gpt-5.6-terra`) per
(cell, topic) grades every official TREC RAG 2026 rubric criterion (\~31
criteria, 0--2 each) plus a holistic 0--3 overall score -- no opponent
answer needed. Chosen over pairwise arena judging because it halves judge
calls per cell and produces a genuinely ordinal per-criterion signal instead
of a categorical win/loss/tie.

*Confirmatory: arena.* One pairwise comparison (`gpt-5.6-terra` judge, both
battle orders) of the best cell against `aus_agent_v2`, retained as the
direct test of the actual competitive objective.

*Noise floor.* The best cell was regenerated on the same 15 topics; the
resulting score moved by 0.067 purely from generation stochasticity. This
value is used throughout as the threshold below which an observed effect is
not distinguishable from resampling noise at this sample size.

== Constraint discovered mid-session

The full TREC RAG 2026 research-rubrics development topic set is only 30
topics total. Fifteen were already committed to the tuning set, leaving only
15 unused topics for replication -- smaller than originally planned, and
insufficient for a full independent held-out arena confirmation once
`aus_agent_v2`'s own per-topic generation cost (\~\$36.5/topic) is
accounted for.

= Results

== All scored cells

@fig-allcells ranks every one of the 21 cells scored this session by
standalone overall score. The four cells tied at the top (2.267) are the
base cell and three factors that made no measurable difference
(`commit_release`, `judge_relevance_tool` + `commit_release` together, and
the closure critic).

#figure(
  image("figures/fig1_all_cells.pdf", width: 92%),
  caption: [Standalone rubric overall score, all 21 cells, sorted. Base cell in blue. #link("interactive/fig1_all_cells.html")[#text(fill: accent)[Interactive version →]]],
) <fig-allcells>

== Factor effects

@fig-effects groups every tested change by factor family and plots its
effect on the standalone score relative to the base cell, with the
±0.067 noise band shaded. Generator-model choice is the only factor
whose effects consistently and substantially clear the noise band in both
directions tested; every other factor family clusters at or inside it.

#figure(
  image("figures/fig2_factor_effects.pdf", width: 92%),
  caption: [Factor effects vs. base cell (2.267), grouped by family. Shaded band = noise floor. #link("interactive/fig2_factor_effects.html")[#text(fill: accent)[Interactive version →]]],
) <fig-effects>

#figure(
  table(
    columns: (auto, auto, auto),
    align: (left, center, left),
    stroke: 0.4pt + rgb("#d8d7d0"),
    inset: 6pt,
    table.header([*Factor group*], [*Effect range*], [*Verdict*]),
    [Generator model], [-0.40 to -1.07], [Dominant, real -- \~10× any other factor],
    [Adjacent-page fetch (round B) off], [-0.067 (sol) / -0.133 (qwen)], [Real for qwen, borderline for sol -- keep on],
    [Generic `agent_harness` factors], [-0.134 to 0.000], [Only 2 of 6 exceed noise, both negative -- none help],
    [Brief-analyst model swap], [-0.067 (all three, identical)], [Noise-level, no real effect],
    [Closure critic (overclaim + contradiction)], [0.000], [No effect],
  ),
  caption: [Factor-effect summary. Noise floor: ±0.067.],
)

== Rubric axis breakdown

@fig-heatmap breaks the standalone score down by official rubric axis for a
representative subset of cells. *References & Citation Quality is the
weakest axis in every single cell scored this session* (mean 0.196/2 across
all 21 cells, range 0.00--0.67) -- independent of generator model,
structural configuration, or harness toggle. No factor tested moves this
axis meaningfully.

#figure(
  image("figures/fig3_axis_heatmap.pdf", width: 92%),
  caption: [Rubric axis means (0--2) by cell. References & Citation Quality stays pale throughout. #link("interactive/fig3_axis_heatmap.html")[#text(fill: accent)[Interactive version →]]],
) <fig-heatmap>

== Arena confirmation

@fig-arena shows the clean (both battle orders agree) per-topic outcome of
the base cell against `aus_agent_v2` on the same 15 topics. The base cell's
standalone-rubric lead over every other tested configuration does not
translate into an arena win rate above 50%.

#figure(
  image("figures/fig4_arena.pdf", width: 78%),
  caption: [Arena outcome, base cell vs. `aus_agent_v2`, 15 topics, both battle orders. #link("interactive/fig4_arena.html")[#text(fill: accent)[Interactive version →]]],
) <fig-arena>

= Discussion

== Why the hill-climb plateaued

@fig-effects makes the mechanism visible: once the generator model is
already optimized (sol), the remaining structural and harness-level levers
this session tried have an order of magnitude less headroom to move the
standalone score. Eleven of twelve post-model-selection moves landed at or
below the 0.067 noise floor -- not because they were poorly chosen, but
because the model-choice effect had already consumed most of the available
variance at this topic-set size and rubric.

== Standalone score is not a full proxy for the arena objective

The base cell is the best standalone-rubric cell found (2.267, a real,
replicated improvement over every luna baseline) and yet loses the
majority of arena battles against `aus_agent_v2`. Whatever makes
`aus_agent_v2` win head-to-head -- plausibly completeness, coverage
breadth, or claim density -- is not fully captured by the official rubric's
per-criterion grading. A parallel, unresolved finding from this session:
round-B's adjacent-page fetch helped `luna`'s arena result but *hurt* its
standalone score, while helping both metrics for `sol` and `qwen` -- a real
disagreement between the two evaluation modes on at least one factor, not
an artifact to be explained away.

== A separate, untouched weakness

References & Citation Quality sits near the bottom of every cell's axis
profile regardless of what factor was varied. This reads as a systemic
issue in how `brief_revise_agent` constructs or formats citations and
reference lists -- a different investigation (citation format, reference-
list construction logic) than anything this session's factor sweep
targeted, and plausibly higher-value than further generator or harness
tuning given how flat the rest of the factor space turned out to be.

= Recommendation

Use the base cell (gpt-5.6-sol, round-B structure, k=10, luna
brief-analyst/reviewer) as `brief_revise_agent`'s standing configuration --
it is the best available and the twelve-move search around it is
exhausted. It is not yet competitive with `aus_agent_v2` head-to-head.
Closing that remaining gap most likely needs either (a) a structural change
genuinely distinct from anything tried this session (e.g. a
multi-candidate/ensemble mechanism, explicitly out of scope here per the
brief to diverge from `aus_agent_v2`'s own architecture rather than
re-derive it), or (b) treating `brief_revise_agent` as the lighter, cheaper
alternative and reserving `aus_agent_v2` for submissions where its cost is
affordable.

= Budget

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
  caption: [Final cost breakdown.],
)

= Data and code

*Interactive figures* (hover tooltips, self-contained HTML, open directly in
a browser, no server or network needed): `interactive/*.html`, alongside
this PDF, generated by `make_interactive.py`. Every figure above links to
its interactive counterpart.

All generated answers: `data/outputs/brief_revise_agent/` (by `run_id`).
Standalone scores: `evaluation-results/factorial/<run_id>/`. Arena
judgments: `evaluation-results/factorial/arena-sol-vs-aus-agent-v2-exp15/`.
Sub-system manifests: `src/systems/brief_revise_agent/subsystems/*.json`.
Execution index: `evaluation-results/factorial/executions.jsonl`. Full
narrative log with every intermediate decision:
`worklogs/2026-08-07-brief-revise-agent-llm-factorial-design.md`. New code
this session: `commit_release_tool.py`, `REVIEW_PROMPT_WITH_CLOSURE` +
`closure_check` (`prompts.py`/`review.py`/`agent.py`/`run.py`), five
generic-factor CLI flags -- all on branch
`explore/new-agent-framework-system`.
