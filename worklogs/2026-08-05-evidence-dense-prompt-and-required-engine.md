# 2026-08-05 — `evidence-dense` prompt variant + `search_engine` required on every call

Two changes, plus the optimization backlog they came out of. Both changes are
**untested against a real run** — nothing here has been A/B'd yet; the numbers
quoted are from `worklogs/2026-08-04-test119-vs-official-baselines.md`.

## 1. `search_engine` is required on every search call

Previously `build_search_tool` marked `search_engine` required only when more
than one engine was enabled, advertised a JSON-Schema `default`, and
`execute_full_text_search` had a three-level fallback (model's choice → the
run's `engines[0]` → the shared tool's built-in `semantic`).

Now:

- `tools/search_tool.py::build_search_tool` — `required = ["query",
  "search_engine"]` unconditionally, and the `default` key is gone from the
  property. A `default` on a required field reads as "you may omit this", which
  is the exact omission the rule exists to prevent.
- `aus_agent/tools/search.py::execute_full_text_search` — an omitted
  `search_engine` returns an error envelope naming the run's enabled set, and
  reaches no backend. The `default_engine` parameter is deleted; the parameter
  it was replaced by (`engines`) exists only to name the options in that error.
- `aus_agent/agent.py` — `_execute_tool_calls` takes `engines` instead of
  `default_engine`; `DEFAULT_ENGINES` is unchanged (`["semantic", "keyword"]`
  — dense + sparse, already the default).
- `aus_agent/agent.py:594` — the default `run_desc` now records
  `engines=semantic+keyword`. Result 8 flagged that the two single-engine
  test-119 runs carry byte-identical `run_desc` strings that name only
  `prompt=default`, so the submission artifact does not say which retriever
  produced it.

Why: the retrieval fine-tuning consumes per-search labels from these
trajectories. A hit filed under an engine the model never selected is label
noise, and a single-engine effectiveness run that silently answered from
`semantic` would be measuring the harness's default instead of its experiment.

Result 8 measured the pre-change behaviour and found it already compliant —
1,073/1,073 and 1,070/1,070 search calls carried an explicit `search_engine` —
so this is closing a hole rather than fixing an active bug. The value is that
it stays closed under the dual-engine runs Result 9 argues for, where the
choice is live on every call rather than forced by a single-engine config.

**Blast radius: aus_agent only.** No other system uses `build_search_tool`.
`facet_rag/loop.py:251` passes `search_engine=engine` from its own planner
schema; `ali_deepresearch` and `claude-code-research` call
`run_search_backend(..., engine=...)`. `run_search_tool`'s Python-level
`search_engine="semantic"` default is retained — it is a library default with
its own tests, and the model-facing path no longer relies on it.

Tests updated: `tests/shared/test_search_tool.py` (single-engine build now
requires it; new test that no `default` is advertised),
`tests/aus_agent_context/test_budget_and_prompt.py` (the three-level-fallback
test becomes a "only the model's choice routes" test + a new omitted-engine
error test), `tests/systems/test_aus_agent.py` (single-engine run names its
engine; new test that an engineless call is recoverable and retrieves nothing),
`tests/aus_agent_context/fakes.py` (the `call()` helper defaults
`search_engine="semantic"` for `search`). 1537 passed, 0 skipped.

### Bundled correction

`aus_agent/tools/search.py::CONTEXT_PROTOCOL` — the tool-result footer told the
model "commit_context must be exactly the first action on that turn". The loop
does not enforce that and never has (`test_the_commits_position_within_the_turn_does_not_matter`),
and `prompts/system/default.md:132` says the opposite. The footer and the
README now match the behaviour: call it on that turn, position irrelevant.

## 2. `prompts/system/evidence-dense.md`

A new full variant (`--prompt-variant evidence-dense`), branched from
`default.md`. Every change targets a *measured* defect from the test-119
comparison rather than a general notion of effort.

**Scope: this is variant (c) of the three the comparison worklog proposes**
("a synthesis-side specificity instruction"), and deliberately nothing else.
It touches how evidence is read and how the report is written; it does not
touch search allocation, engine pairing, the `commit_context` selection rule,
or the stopping rule. Those are variants (a) and (b) and must be tested
separately — Result 9 is explicit that (a) cannot ship without a
`commit_context` rewrite in the same change, and that a round-count
instruction produces more leads rather than more depth.

An earlier draft of this file did include three search-strategy bullets
(parallel coverage areas, put a thin facet to the other engine, corroborate
load-bearing claims with a second source). They were removed on reading
Result 9: the second and third are (a) in weak form, and shipping them here
would confound the arm and, worse, be silently cancelled by the
`commit_context` rule that still tells the agent to discard "semantically
redundant" results. 85 lines now differ from `default.md`, all answer-side.

Diff against `default.md`, by finding:

| change | finding it targets | measured size |
|---|---|---|
| every world-asserting sentence carries a citation; cut what you cannot cite (two exceptions: the one "could not establish" sentence, and invented material where the brief asks you to invent) | 13.5–13.6% uncited answer objects vs 0% for both baselines | 0.063 weighted recall, 54–57% of the support gap |
| new "Reading a result" section: read for what a document *states*, note the specific on commit, re-read the committed passage before writing about it | 42–47% of the figures the agentic baseline stated and we omitted were in documents **we ourselves cited** | largest concrete quality gap found by hand |
| prefer the specific over the categorical; name the number/year/study; where sources disagree give both figures rather than calling the point "contested" | 8.6 numerals/1k words vs 15.6 for the winner | 1.8× density gap |
| assert what the evidence establishes; modals only where the source is uncertain | 16.1 modals/1k vs 12.4 | — |
| cite the passage that *states* the claim; check direction and scope; narrow the sentence rather than stretching the citation | wP 0.594 vs 0.653 even on topics where we cite every object | 46% of the support gap |
| do not attach a country, jurisdiction, regulator, emergency number, or currency the request and evidence did not name | 9 topics volunteered Australian localization | pref 0.278 vs 0.509, n=9 |
| write in English throughout; non-Latin script only inside a quoted-and-glossed name | `非開催` mid-sentence in rag2026-10 | 1 sentence, 0 in both baselines |
| the retrieval is not a character in the answer — never "the research describes" / "in the corpus" | 3 sentences (rag2026-3, -47, -99) | 3 sentences, 0 in both baselines |
| a stated form is a requirement: an article wants an article's shape | rag2026-60 asked for a ~10-minute-read article, got 38 flat declaratives | 1 topic, read by hand |
| new success-plan item 5: name the decision behind the request; a fact that would change it belongs in the answer even if unasked | the baseline volunteers the decision-relevant fact (UFLPA presumption, SRO evidence, 73% of Uri outages) | 3 of 12 topics read side by side |

Deliberately **not** carried over from the effort-prompt experiment: numeric
proxy targets (100+ documents, 4–8 queries per round, expected budget use) and
"follow every thread" language. That experiment showed those scale activity
(28 searches vs 20, 40 committed vs 24, 451K tokens vs 321K) without scaling
answer quality (all three arms reached the same thesis, 920–954 words). Raw
logs: `worklogs/assets/2026-07-20-effort-prompt-{low,medium,high}.log`.

Verified the variant loads and satisfies every invariant the prompt tests
assert of `default.md`: exactly one `__MAX_COMMITTED_DOCS__`, no "ClimbMix",
no "scratchpad", `get_documents` presented as staged, the 500,000-token
figure, both protocol headings, and the "commit first, write next turn" rule.
3,297 words rendered at `--max-committed-per-step 20`.

**One expected interaction to watch.** The cite-or-cut rule makes the answer
shorter on exactly the topics where uncited objects cluster, and Result 7
showed the arena judge's verdict tracks relative length (r = −0.429 on the
opponent's word count). So this variant may *lose* arena battles while gaining
support precision. That is not a reason to soften it — support is the announced
measure and the arena's length sensitivity is the thing under suspicion — but
it means the arena delta must be read alongside a word-count delta, not alone.

**Not done:** no run. The next step is a matched A/B against `default` on the
119 test narratives (same model, same engines, same `k`), scored on the two
rubric-free measures already implemented in `tasks/task-comparison/scripts/`.
The uncited-object rate and numerals/1k are the two cheap structural checks
that will show movement without any judge spend.

## 3. Reading further into a document: what the agent is and is not told

Prompted by "we haven't been teaching the agent to read more on truncated
chunks". Probed live against the dense endpoint rather than argued.

**The truncation framing turns out to be a non-issue, and that is the useful
part of the answer.** `execute_full_text_search` bounds each staged result at
`budget_tokens_per_result × 5` = 20,480 chars and sets `truncated` /
`original_chars` / `returned_chars`. Post-chunking, chunks are far below that:
a live `search_dense("congestion pricing revenue", k=5)` returned chunks of
990, 1,681, 2,289, 2,928 and 3,050 chars. The bound is ~7× the largest. So
`truncated` is effectively always `false`, those three fields are dead weight
in the payload, and a prompt rule about handling truncation would spend tokens
on a branch that never fires. The staging budget was sized for whole documents
and was not revisited when the index went chunk-native.

**The real gap is the denominator.** A search returns ONE page and never says
how many there are:

- `/doc/<id>` responds `{docid, text}` — no page count.
- The search envelope carries `rank, id, docid, kind, score, text` — no count.
- The chunk text *does* open with `Page <n> of document:` — the numerator only.

So a hit on `shard_01489_13822_p5` tells the agent that pages 1–4 exist and
were withheld, and tells it **nothing** about whether page 6 exists. The only
way to find out is to request the next id and see whether it lands in
`missing`. Verified: `shard_04438_19655_p1` and `_p2` return 2,259 and 1,681
chars, `_p3` is missing — a 2-page document, discoverable only by asking.

Two changes, one made and one recommended:

- **Made:** `GET_DOCUMENTS_TOOL`'s description now states that a search returns
  one page of a document, that no page total is available anywhere, and that
  asking for a non-existent page is *free* (returns in `missing`, stages
  nothing, costs no context) — so the probe is also the way to find a
  document's end. The previous wording mentioned `missing` only as an error
  outcome, never as the discovery mechanism, and never said a hit implies
  unseen pages.
- **Recommended, not made:** put `Page <n> of <m>` into the docstore's chunk
  prefix at index-build time. The prefix is already there and already written
  by us; adding the denominator removes the probe entirely and gives the agent
  a direct "there is more here" signal at zero runtime cost. This is a
  `tasks/chunking-strategy` / docstore change and a re-index, so it is a
  proposal, not a patch.

**Deliberately NOT added to `evidence-dense.md`.** A rule about *when* to read
deeper is a trajectory-shape change, which is Result 9's variant (b)
territory, and adding it here would confound the answer-side arm. The tool
description is shared by every variant and changes them equally, so it does not
break a paired A/B — but it does change the baseline relative to the published
test-119 runs, which any comparison against those must account for.

**A caveat on all of the above:** the test-119 trajectories are archived
off-host (`data/outputs/aus_agent/` holds 7 failed dev runs), so actual
`get_documents` call counts could not be re-measured this session. The 0–4%
figure is Result 9's, measured on the same-lead pairing proxy rather than on
`get_documents` directly. A direct count is worth taking when the archive is
restored — if the tool is genuinely never called, the affordance fix above is
the cheap thing to try before any prompt rule.

## 3b. Variants (a) and (b), and the shared selection-rule change

Result 9's items 8 and 9, built. Both are branched from `default.md`
**programmatically**, by anchored string replacement of exactly the sections
being changed, so each file differs from the control only where declared:
`paired-lead.md` in 14 lines, `done-condition.md` in 47.

### The selection rule is shared policy, not an arm

`COMMIT_CONTEXT_TOOL`'s description told the model:

> Do not select an id already committed, **or a semantically redundant result
> supporting the same claim**, unless it adds materially different evidence.

and all three prompts restated it as "Skip semantically similar results when
they support the same claim." Rewritten in both places — the tool description
and `default.md` / `firsthand.md` / `evidence-dense.md` — to **adjudicate
rather than de-duplicate**: several results bearing on one claim is the batch
working, especially when a lead was searched on more than one engine; keep the
complementary ones, or the single best where they genuinely coincide, against
stated criteria (concrete figure/date/named finding over categorical
description; worked example over generalisation; primary or better-sourced over
a report of it; the more precise statement of the same point). A result is
rejected because another beat it on those grounds, never because it looked
similar. The `reason` field now asks which criterion it won on, which makes
compliance checkable from the trace.

This had to land in every prompt, not just the new variant: leaving the old
line anywhere would contradict the tool on the one turn that decides, and would
silently cancel a paired round by discarding the second engine's contribution.
Two tests pin it — `test_the_description_adjudicates_rather_than_de_duplicates`
and a parametrized `test_no_variant_reinstates_blanket_de_duplication`.

### `paired-lead.md` — variant (a)

One rule, expressed as a readiness criterion rather than a step script (per the
reasoning guide's "avoid prescribing intermediate steps"): **a lead is ready to
judge when both engines have answered it, not before.** The justification given
to the model is Result 8's: the two engines return almost entirely different
documents for the same need, and nothing in either result set signals what the
other would have found — so a single-engine lead was judged on roughly half its
evidence with no indication anything was missing. Explicitly volume-neutral:
the same searches per round, spent as fewer leads covered properly. Each query
of the pair is written for its own engine so the pair is two views rather than
one query sent twice, and the prompt says to expect both to return support for
the same point — pointing at `commit_context` as where they get weighed.

No round count and no per-round lead count appear in the file. The 2–3 leads ×
2 engines shape is the arithmetic consequence of the criterion at constant
volume, not an instruction.

### `done-condition.md` — variant (b)

Two changes. The **Decide** step now keeps a lead ledger — every lead standing
at *resolved* / *refuted* / *needs-depth* — and routes a needs-depth lead to
`get_documents` on documents already paying off *before* another search, on the
grounds that a new query opens a new lead and a new lead is not what an
unfinished one needs. That is where the "read until you have read enough of
that document" behaviour becomes a rule rather than an affordance.

The **stopping** section is replaced by a marginal-yield done-condition:
continue while the round just finished committed something that changed the
plan (resolved a lead, opened one, corrected a claim, replaced a categorical
statement with the figure behind it); stop when a round returns only what is
already committed or only material that will not change the answer. Two
corollaries are stated because they are the two ways the rule gets misread: a
fully resolved ledger after a dry round is finished *however much budget
remains*, and a ledger still holding a needs-depth lead is not finished
*however many rounds have passed*. The context-budget ceiling remains as the
only early stop. No round count appears anywhere — Result 9's warning is that a
number in the prompt becomes a target.

### Drift guard

Five near-identical 15 KB prompt files is exactly the drift risk the
effort-prompt review named. Rather than refactor the loader, a parametrized
`test_every_variant_keeps_the_shared_harness_contract` now asserts, for every
file in `prompts/system/`, the clauses the harness actually enforces: one
`__MAX_COMMITTED_DOCS__`, the staged/committed protocol heading, the final
response contract heading, one-sentence-per-line, the budget figure taken from
`DEFAULT_CONTEXT_TOKEN_BUDGET` rather than hardcoded, commit-then-report, the
`get_documents` staging sentence, and the two deliberate absences (ClimbMix,
scratchpad). A variant that dropped one of these would fail as a *run*, and the
cause would be invisible in the scores it was being compared on. 1548 tests
pass.

### How to run the three arms

```bash
for v in default paired-lead done-condition evidence-dense; do
  uv run --group aus-agent python src/systems/aus_agent/run.py --all \
    --prompt-variant "$v" --run-id "promptab-$v" --k 20 \
    --max-committed-per-step 20 --skip-existing
done
```

Each arm against `default` alone, never in combination — the whole point of the
programmatic branching is that a difference in scores is attributable. Note the
selection-rule rewrite moves `default` itself relative to the published
test-119 runs, so `default` has to be re-run as the control rather than reusing
`test-semantic-119` / `test-keyword-119`.

## 3c. RESULTS — the four arms actually run

10 topics (`rag2026-0..9`), `gpt-5.6-luna`, `semantic,keyword`, `k=20`,
`--max-committed-per-step 20`. 40/40 completed. Run ids `promptab0805-*`.

```bash
bash tasks/task-comparison/scripts/run_prompt_variants.sh <variant>   # per arm
uv run --no-project python worklogs/assets/2026-08-05-prompt-variant-comparison.py
```

| | control | paired-lead | done-condition | evidence-dense |
|---|---|---|---|---|
| rounds | 2.5 | 3.2 | 2.8 | 2.8 |
| searches | 10.5 | **13.8** | 10.9 | 10.4 |
| searches/round | 4.2 | 4.3 | 3.9 | 3.7 |
| commits | 2.4 | 3.1 | 2.6 | 2.6 |
| same-lead rounds | 4% | **72%** | 0% | 0% |
| both-engine rounds | 36% | 81% | 11% | 25% |
| engine mix sem:kw | 90:10 | **52:48** | 88:12 | 91:9 |
| `get_documents`/topic | 0.0 | 0.0 | **0.0** | 0.0 |
| words | 839 | 839 | 826 | 779 |
| answer objects | 26.1 | 25.7 | 24.0 | 21.1 |
| references | 15.5 | 15.2 | 16.0 | 14.4 |
| citations/object | 1.24 | 1.25 | 1.28 | **1.55** |
| uncited objects | 20.3% | 16.0% | 10.0% | **1.9%** |

The control replicates the published test-119 shape closely (rounds 2.5 vs
~2.4, same-lead 4% vs 4%, engine mix 90:10 vs 86:8, refs 15.5 vs 15.0-15.9,
strict numerals 8.6 vs 8.58/8.78), so the arms are being compared against a
baseline that behaves like the published one.

### paired-lead: moved the invariant, but is NOT volume-neutral

Same-lead pairing 4% → **72%** (18x), engine mix 90:10 → **52:48**. First time
anything has moved the trajectory shape that Result 9 found invariant across
every prior run, prompt, engine, and topic set. It also answers the
2026-08-04 open question "why does the agent under-use the sparse engine" —
operationally, by removing the choice.

But the prompt's volume-neutrality claim is **false in practice**. It says the
pairing is "the same number of searches in a round, spent as fewer leads
covered properly". Searches/round stayed flat (4.2 → 4.3), so it did not cover
fewer leads — it kept the leads and added the second engine to each, then ran
more rounds: **+31% searches, +29% commits**. Result 9's argument for (A)
rested on it being free. It is not, so it must now justify itself on quality.
The prompt's neutrality sentence should be rewritten or dropped; as written it
is a claim the run falsifies.

### done-condition: did not take

`get_documents` 0.0, same-lead 0%, rounds 2.8 vs 2.5. The ledger vocabulary
("ledger", "resolved", "refuted", "needs-depth") appears **zero** times in the
recorded reasoning across all 10 topics — suggestive but not conclusive, since
the OpenAI provider stores a lossy `reasoning.summary` plus opaque
`encrypted_content` (9,648 chars of real text were scanned). Its one movement
is uncited objects 20.3% → 10.0%, which was not its target.

### get_documents is never called — 0/40 topics, four prompts

Zero across every arm, including the one whose prompt explicitly routes a
needs-depth lead there *before* another search. Plumbing verified, not a bug:
`trace.input.tools` lists `['search', 'get_documents', 'commit_context']` in
every run with the improved description, and the provider forwards it.

So the escalation failed at every level — better tool wording: zero; an
explicit prompt rule: zero. **This retracts §3's recommendation.** Putting
`Page <n> of <m>` in the docstore prefix only helps a model that was going to
call the tool, and this one was not. Deprioritise it until something makes the
tool get called at all; the live options are structural (return neighbouring
pages from `search` itself, or enlarge chunks) rather than textual.

### evidence-dense: the citation half worked, and the density half did too

Uncited objects 20.3% → **1.9%**, against 0% for both organizer baselines —
the structural half of the support gap (worth ~0.063 weighted recall) is
essentially closed. Citations/object 1.24 → **1.55**, moving toward the
baselines' 1.72. Cost is a shorter answer: 839 → 779 words, 26.1 → 21.1
objects, exactly as the cut-what-you-cannot-cite rule predicts — which matters
because Result 7 showed the arena judge tracks relative length, so this arm may
*lose* battles while gaining support.

### A metric artifact that inverted one conclusion

The published numerals/1k metric — `\b\d[\d,.]*\b` full-matching a
whitespace token — counts only **bare** numerals and structurally cannot see
`$480`, `34%`, or `4.3x`. The arms that produced more figures produced them
predominantly with units attached, so on the strict metric `paired-lead` reads
as 8.7 → 7.0 (*less* specific) when it is in fact more specific. Measured on
the same 10 topics, against both organizer baselines:

| run | strict | any-digit | %/$ | year-like | uncited |
|---|---|---|---|---|---|
| base-agentic-bm25 | 9.6 | 19.2 | 6.8 | 4.1 | 0.0% |
| base-singlepass | 5.1 | 12.5 | 6.3 | 2.8 | 0.0% |
| ours-default | 8.6 | 14.7 | 4.2 | 2.4 | 20.3% |
| ours-paired-lead | 7.3 | 17.6 | **8.3** | **4.6** | 16.0% |
| ours-done-condition | 8.4 | 16.3 | 6.7 | 2.3 | 10.0% |
| ours-evidence-dense | 8.9 | **18.2** | 7.3 | 4.0 | **1.9%** |

Two things follow, and both revise earlier conclusions:

1. **`evidence-dense` reaches parity with the winning baseline on evidence
   density** (any-digit 18.2 vs 19.2, %/$ 7.3 vs 6.8, years 4.0 vs 4.1), and
   `paired-lead` *exceeds* it on figures-with-units. The strict metric hides
   all of this.
2. **The published "1.8x density gap" is much smaller on these topics than the
   119-topic number suggests.** `base-agentic-bm25` scores strict 9.6 here
   against the 15.58 published over all 119 — so these 10 narratives are far
   less numeric than the 119 average. This does not refute the 119-topic
   finding; it means a 10-topic subset cannot test it, and the whole density
   comparison should be re-run over all 119 with the inclusive measure before
   the gap is treated as real.

### What these results do and do not establish

They are **structural proxies measured on 10 topics**, not the announced
measures. No support judging, no arena, no second judge. Uncited rate and
citations/object are mechanically related to weighted support but are not it;
density is a hand-observed correlate of the arena outcome that Result 7 already
showed does not predict individual battles. The honest reading is that
`evidence-dense` moved every proxy it targeted and `paired-lead` moved its
target at a real cost, and that both now deserve the 119-topic run plus
`judge_test119_support.py` before anything is concluded about quality.

## 4. Reading of the comparison, and what it implies for the backlog

The framing that "the prompt didn't help" needs one correction and one
concession.

**Correction: the arena measure probably cannot see prompt effects.** Result 7
established that in the ours-keyword vs base-agentic-bm25 pair the judge's
verdict tracks *relative answer length* (r = −0.429 on baseline word count,
+0.416 on the word gap) and is indifferent to relative fact density once length
is controlled (the 2×2 rows separate by ~0.35, the columns not at all). A
measure that resolves length and not substance will report a null for any
prompt change that does not change length. So 0.485 is evidence that we are
level on *length-adjusted preference*, not evidence that prompt content is
inert.

**Concession: on the measure that is not a preference vote, we do lose.**
Weighted citation support is 0.590/0.581 against 0.635/0.634, and we lose the
paired per-topic comparison 79–39. That gap is real, it decomposes cleanly
(≈54% uncited objects, ≈46% citation quality), and it is what §2 targets.

**What actually dominated the four-way spread was architecture, not prompt or
model.** Both organizer baselines share a generator (`gpt-5.6-sol`) and differ
only in retrieval strategy: agentic BM25 scores 0.654, single-pass with a
FIRST/Qwen3-8B listwise reranker scores 0.195. That is a 3.4× spread inside one
model, and it dwarfs every ours-vs-theirs difference. It supports the instinct
to optimize the trajectory rather than the wording.

Result 9 sharpens *which* part of the trajectory. The search shape is invariant
— ~2.3 rounds, ~9 searches, ~3.8 per round, ~2.3 commits — across every run,
every prompt variant, both engines, and both the 10-topic dev sets and the
119-topic test set. Prompt wording has never moved it. That is consistent with
"the prompt didn't help", and it locates the reason: the levers tried so far
were phrased as encouragement, and the two that would actually move the shape
are a selection *rule* and a termination *condition*, neither of which any
variant has changed.

**"Diversity" splits into two layers that point opposite ways, and an earlier
draft of this worklog got it wrong by conflating them.** At the *citation*
layer we already spread wider than the winner and score worse — 15.92
references per narrative vs 9.92, at 1.37 citations per answer object vs their
1.72. At the *retrieval* layer, Result 8 shows dense and sparse return sets
that share only 3.6% (Jaccard 0.0355; 93% of each run's documents are unique to
it; 21 of 119 topics overlap in nothing at all), and the unique 93% supports its
sentences as well as the shared 7% (mean support 1.105 vs 1.134 on 0–2). So
retrieval diversity is real and underexploited, while citation diversity is
excess. The correct statement is *widen what the agent sees per lead, narrow
what it cites per claim* — which is Result 9's change (A) plus the
`commit_context` rewrite, not a single instruction in either direction.

Source **credibility** is still untested — nothing in the comparison scores it.

### Backlog

Reordered against Results 8 and 9. The comparison worklog's own "What to act
on" list (items 1–10 there) is canonical; this is what falls to this session's
work and what it changes.

**Shipped here, unmeasured** — the answer-side arm, Result 9's variant (c):

1. Cite every world-asserting sentence / cut what cannot be cited — 0.063 wR,
   mechanical.
2. Carry the specific out of the committed passage — 42–47% of missed figures
   were already in hand. Open question the artifacts cannot answer: generation
   choice, or context truncation? Needs the trajectories, not the submissions.
   The unused-figure and 23–24%-citation-rate numbers together say selection
   and use, not coverage, are the binding constraint — which is why this arm
   is answer-side and not "search more".
3. Localization, English-only, no meta-reference to the retrieval, stated form
   is a requirement — small n each, all zero in both baselines.

**Next, and bigger than anything above** — Result 9's variant (a), one change:

4. Pair both engines on each lead, fewer leads per round (volume-neutral),
   **and** rewrite `commit_context`'s selection rule from blanket
   de-duplication to adjudication against specificity criteria. These cannot
   ship separately: pairing produces exactly the "semantically redundant"
   results the current rule
   (`src/systems/aus_agent/tools/commit_context.py:10`) tells the agent to
   discard, so the search change alone would pay for the retrieval and throw
   the second engine's contribution away. Today only 0–4% of rounds pair a
   lead across engines and cross-engine query similarity averages 0.09, so
   **no lead in any run has ever been resolved against both retrievers'
   candidates** — every lead was reviewed against roughly half its available
   evidence. This is also the second attack on item 2, from the selection side.

**Then** — Result 9's variant (b):

5. Make termination a done-condition on marginal yield, never a round count.
   Every run is invariant at ~2.3 rounds / ~9 searches / ~2.3 commits across
   all prompts, engines, and topic sets, with `safety_max_rounds=100` untouched
   and all 238 trajectories `completed`. Nothing needs raising; the agent stops
   by its own judgement. Express it as a done-definition plus a lead ledger
   (leads named up front, each marked resolved / refuted / needs-depth), not as
   a step script — a round number in a prompt becomes a target, and "more
   rounds" reliably produces more leads rather than more depth.
6. `get_documents` adjacent-page navigation is the depth mechanism that already
   exists and is barely used (0–4% pairing, and the 2026-07-29 meeting recorded
   the same). The *rule* for when to use it belongs inside (5)'s "needs-depth"
   branch rather than as its own instruction. The *affordance* was fixed this
   session (§3) and is independent of it.
7. Put `Page <n> of <m>` in the docstore chunk prefix at index-build time (§3).
   Today the agent has the page number and no denominator anywhere in the
   stack, so it cannot tell a document's last page from its middle without
   spending a probe. Needs a re-index, so it belongs with the next index build
   rather than on its own.

**Diagnostics that gate the above:**

8. Citation-quality diagnosis — wrong document chosen from the staged set, or
   claim drifting past what the right document says? Different fixes; the
   existing `support-judgments/` tree can separate them without new spend.
9. Capture token usage before touching `reasoning.mode`/`effort`.
   `providers/openai.py:93` sends only `{"summary": "auto"}`, so every run to
   date is `standard`/`medium` by default, and trajectories record no `usage` —
   a `pro` run would yield a quality delta with no cost denominator. Raise
   `max_output_tokens` (16000 today) while in there: it is a ceiling, not an
   allocation, so a generous value is free and serves only as a runaway guard.
   Add `status: "incomplete"` detection alongside.
10. Fixed-query dense-vs-sparse replay — Result 8's 93% disjointness confounds
   engine with query wording (the agent writes per-engine queries). The 1,073 +
   1,070 queries are already in the trajectories, so replaying one run's
   queries against both engines is cheap and decides how much of (4)'s premise
   is engine and how much is query generation.
11. Second judge, and a length-controlled arena re-run. Everything is
    single-judge, the judge generated two of the four runs, and the arena
    verdict tracks relative length. Both bear on how much weight to give every
    number above — including whether `evidence-dense` "worked".

### Still open from the 2026-07-29 meeting

Per-subquery relevance labels in the trajectory (Shuai Wang's named blocker for
dense-retriever fine-tuning; `context.py::ContextLedger.commit()` still
operates over the union of pending staged results, so a turn with parallel
searches yields one flat committed/rejected list with no per-query
attribution). BFS vs DFS strategy control. Budget-constrained mode. Cost in
`trace.summary`. A non-Anthropic Bedrock path for the open-weight submission.
The 120-topic trajectory run.

The required-`search_engine` change above is a prerequisite for the first of
these: per-subquery labels are only usable if each search's engine is the one
the model chose.
