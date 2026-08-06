# 2026-08-05 — aus_agent vs facets_agent: rubric-grounded arena, judge=gpt-5.6-terra

**Branch:** `facets_agent`. Follow-up to the facets_agent-vs-facet_rag arena
(`worklogs/2026-08-05-facets-agent-vs-facet-rag-arena.md`): this run compares
`aus_agent` against `facets_agent` head-to-head, grounded in the official
ResearchRubrics per-topic criteria instead of the naive preference prompt, and
judged by a **third** model (`gpt-5.6-terra`) that generated neither system's
answers — removing the self-preference confound that limited the previous
comparison's interpretability.

## Branch reconciliation (before any new work)

Asked to "verify everything is committed and pushed" first. `git fetch`
showed `origin/facets_agent` had been rebased from another session/machine
(same author, `oleg.zendel@rmit.edu.au`): a new commit
`4409e94 fix(tests): stop requiring gitignored eval file in umbrela pin test`
was inserted after my prior work, and my three commits were replayed on top
with new hashes. That fix commit is exactly the pre-existing test failure
flagged in the earlier `facets_agent` worklog
(`test_umbrela_template_is_byte_identical_to_the_prior_bedrock_run` needing a
gitignored `evaluation-results/` file) — now fixed with a committed one-row
fixture instead. Verified via `git diff <my-HEAD> <origin-tip> --stat`
(empty except for that one fix) that nothing of mine was lost before
reconciling with `git reset --hard origin/facets_agent` (confirmed with the
user first, since that command is normally off-limits without explicit
confirmation). `bash scripts/test.sh` afterward: **1588 passed**, 0 failed —
confirms the fix actually resolved the previously-flagged failure.

## Running aus_agent on the same 15 topics

Same 15 qids as the facet_rag comparison (facet_rag's `arena_15topic` set —
see the previous worklog for the list and how they were found).

**Model held fixed across systems, deliberately**: aus_agent ran on
`--backend openai` (→ `gpt-5.6-luna`, its `OPENAI_MODEL_ID` default), the
same model facets_agent uses, rather than aus_agent's own Bedrock/Claude
default. The point of this comparison is aus_agent's long, heavily-tuned
prompt vs facets_agent's short, facet_rag-inspired one — holding the
generator model fixed isolates that variable instead of confounding it with a
second one (which model). Everything else used each system's own defaults
(aus_agent: `semantic,keyword`; facets_agent: `semantic,keyword,hybrid`) —
comparing each system "as designed," not forcing an identical engine set.

```bash
export OPENAI_API_KEY="$AZURE_OPENAI_API_KEY"
for q in <the 15 qids>; do
  uv run --group aus-agent python src/systems/aus_agent/run.py \
    --qid "$q" --backend openai --run-id aus-agent-15topic
done
```

**Result: 15/15 completed**, 0 `.violations.json`, references per topic
7–20, word counts 521–1012 — notably closer to facets_agent's range
(364–1024) than facet_rag's was, reducing (not eliminating) the length
confound that limited the previous comparison. Full log:
`worklogs/assets/2026-08-05-aus-agent-15topic-run.log`.

## Rubric-grounded arena

`ragdoll arena compare-all --rubric-file ...` needs the `pi` binary (not
installed here — same blocker as the facet_rag comparison). New script,
extending the established `judge_test119_arena.py`/
`arena_facets_agent_vs_facet_rag.py` pattern with rubric support:
`tasks/task-comparison/scripts/arena_aus_agent_vs_facets_agent_rubric.py`.

- **Rubric source**: the official
  `data/official/.../researchrubrics-dev-rubrics/research-rubrics-dev-rubrics.jsonl`
  (~31 weighted criteria per topic, e.g. "mentions a financial term without
  defining it for a general audience" at weight −3.0, "includes a geometric
  diagram for each theorem" at weight 4.0). Field names (`criterion`, `axis`)
  differ from RAGDoll's own rubric schema (`text`, `type`); mapped in
  `load_research_rubrics` rather than writing an intermediate file, but still
  rendered with RAGDoll's own `format_rubric_for_prompt` for output-shape
  consistency with the documented contract. This selects
  `PAIRWISE_ANSWER_COMPARISON_W_RUBRICS` instead of the naive prompt.
- **Both answer sets from `ragrun.save_run` artifacts** this time (unlike the
  facet_rag comparison, where facet_rag's side was a fixed external
  snapshot) — one generic loader (`load_answers_from_outputs`) works for
  both systems since the organizer output schema is shared.
- Both orders judged and pooled, same as before.

```bash
export OPENAI_API_KEY="$AZURE_OPENAI_API_KEY"
uv run --group aus-agent python \
  tasks/task-comparison/scripts/arena_aus_agent_vs_facets_agent_rubric.py \
  --workers 6 --model gpt-5.6-terra
```

## Result: aus_agent 19–11 (63.3%), NOT a clean sweep

| | aus_agent | facets_agent |
|---|---|---|
| Wins (of 30 battles, both orders pooled) | 19 | 11 |
| Overall preference rate | 0.6333 | 0.3667 |
| `order_consistency` | 0.667 (5 of 15 topics flip preferred system by orientation) |

Per-topic (which system won in orientation 0 / orientation 1):

| qid | o0 | o1 | |
|---|---|---|---|
| 683a58c9a7e7fe4e76958498 | aus_agent | aus_agent | consistent |
| 684397d188c1deceb49af325 | aus_agent | aus_agent | consistent |
| 684397d188c1deceb49af32d | facets_agent | facets_agent | consistent |
| 6847465956a0f6376a60535d | facets_agent | aus_agent | **flipped** |
| 6847465956a0f6376a605367 | facets_agent | aus_agent | **flipped** |
| 6847465956a0f6376a605387 | facets_agent | facets_agent | consistent |
| 6847465956a0f6376a605391 | aus_agent | aus_agent | consistent |
| 6847465956a0f6376a605404 | facets_agent | aus_agent | **flipped** |
| 6847465956a0f6376a60542a | facets_agent | aus_agent | **flipped** |
| 6847465956a0f6376a605476 | aus_agent | aus_agent | consistent |
| 6847465956a0f6376a60547e | aus_agent | aus_agent | consistent |
| 6847465956a0f6376a60547f | aus_agent | aus_agent | consistent |
| 6847465956a0f6376a605492 | aus_agent | aus_agent | consistent |
| 6847465956a0f6376a605493 | facets_agent | facets_agent | consistent |
| 6847465956a0f6376a6054a7 | facets_agent | aus_agent | **flipped** |

So: **7 topics aus_agent wins outright** (both orientations), **3 topics
facets_agent wins outright**, **5 topics are position-bias noise** (see
below), not a genuine preference either way.

Full per-battle verdicts:
`evaluation-results/arena/aus_agent-vs-facets_agent-15topic-rubric/judgments.jsonl`
(gitignored, local only). Console log:
`worklogs/assets/2026-08-05-arena-aus-agent-vs-facets-agent-rubric.log`.

## A real, notable position bias in this judge run

All 5 flipped topics show the SAME pattern: the judge picked whichever system
was shown as **Assistant B** (the second answer in the prompt), not
Assistant A, in both orientations of every flip. Checked directly against the
raw `[[A]]`/`[[B]]` verdicts (not just which system won): **B was preferred
20/30 times (66.7%), A only 10/30 (33.3%)** — a strong, systematic
"prefer the second answer" bias from `gpt-5.6-terra` on this rubric prompt,
not random noise. This is exactly why judging both orientations and pooling
is load-bearing here, not a nice-to-have: a single-orientation run of this
same 15 topics would have overstated whichever system happened to land more
often as B. Because task construction always balances A/B assignment (each
system is A in exactly half its battles), pooling mostly cancels this out in
the aggregate 19-11 figure — but it is the entire explanation for the 5
"flipped" topics and for `order_consistency` landing well under 1.0.

## Reading the result

Unlike the facet_rag comparison (30-0-0, judge shared aus_agent's ancestor
model with one side), this result has no obvious single confound explaining
it away, and is far more consistent with a genuine, moderate difference:

- The generator model was HELD FIXED across both systems (both `gpt-5.6-luna`)
  and the judge (`gpt-5.6-terra`) generated neither answer set — no
  self-preference risk.
- Answer lengths were comparable (521-1012 vs 364-1024 words), not the
  systematic 2-3x gap seen against facet_rag.
- The rubric grounds the judgment in ~31 concrete per-topic criteria rather
  than an open preference call.
- The remaining position-bias noise is measured and reported, not hidden —
  5 of 15 topics should be read as "no clear preference," not counted as
  confident wins for whichever side the aggregate happened to credit them to.

Plausible mechanism for aus_agent's edge on the 7 clean-win topics: its
system prompt explicitly instructs many of the things ResearchRubrics
criteria check for and penalize the absence of (e.g. "expand every acronym
on first use," structural/formatting requirements) — facets_agent's
minimal prompt states the research PROCESS in similar depth but says much
less about instruction-following mechanics like this, and a rubric grading
scheme is exactly where that gap would show up. This is a plausible reading
of the pattern, not a verified causal claim from this one run.

## Follow-ups (not done this session)

- Would be worth checking whether the 7 aus_agent-favored topics share
  identifiable rubric-criteria categories (e.g. "Communication Quality" /
  "Instruction Following" axes) that facets_agent's answers are
  systematically missing, vs. the 3 facets_agent-favored topics being ones
  where the rubric rewards facets_agent's decompose-into-facets breadth.
- A second judge model (or the reverse pairing: gpt-5.6-luna judging with
  gpt-5.6-terra as one of the generators) would further separate genuine
  quality difference from residual model-specific judge quirks.
