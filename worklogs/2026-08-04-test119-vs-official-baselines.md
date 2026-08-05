# 2026-08-04 — aus_agent test-119 vs the official TREC RAG 2026 baselines

Evaluating our two full 119-narrative test runs against the two organizer RAG
baselines that shipped in the data submodule, using **rubric-free** measures
only (the test narratives have no nuggets, no rubrics, and no qrels).

## The four runs

| label | source | generator | retrieval |
|---|---|---|---|
| `ours-semantic` | `data/outputs/aus_agent/`, `run_id=test-semantic-119` | `openai/gpt-5.6-luna` | our dense/semantic index |
| `ours-keyword` | `data/outputs/aus_agent/`, `run_id=test-keyword-119` | `openai/gpt-5.6-luna` | our keyword index |
| `base-agentic-bm25` | `…/baselines/rag/gpt-5.6-sol_medium_agentic-search_bm25_output-mode-answer.jsonl` | `openai-codex/gpt-5.6-sol` | agentic BM25 over climbmix-400b |
| `base-singlepass` | `…/baselines/rag/gpt-5.6-sol_medium_single-pass-rag_first-qwen3-8b-listwise-top100.jsonl` | `openai-codex/gpt-5.6-sol` | FIRST/Qwen3-8B listwise top-100 |

Both of ours are 119/119 with `trace.status == "completed"`. They were produced
by `tasks/task-comparison/scripts/run_test119_engines.sh`
(`--prompt-variant default --k 20 --max-committed-per-step 20`) on 2026-07-29.

Submodule pin at evaluation time: `data/official/trec-rag-2026-data` @ `a6255c10`.

## Reproducing

```bash
# 1. assemble the four runs in the organizer schema + validate + structural stats
PYTHONPATH=src uv run --group aus-agent python \
    tasks/task-comparison/scripts/build_test119_eval_set.py

# 2. wider audit: Answer Rules, not just Validation Rules
PYTHONPATH=src uv run --group aus-agent python \
    tasks/task-comparison/scripts/audit_test119_conformance.py

# 3. resolve every cited docid to text via the OFFICIAL pyserini doc endpoint
PYTHONPATH=src uv run --group aus-agent python \
    tasks/task-comparison/scripts/resolve_test119_refs.py --workers 8 --rate 6

# 4. anonymized pairwise battles, both orders, all 119 narratives
PYTHONPATH=src uv run --group aus-agent python \
    tasks/task-comparison/scripts/judge_test119_arena.py --workers 16

# 5. weighted citation precision/recall, all citations, all 119 narratives
PYTHONPATH=src uv run --group aus-agent python \
    tasks/task-comparison/scripts/judge_test119_support.py --workers 16
```

Artifacts: `data/task-comparison/test119-eval/` — `<label>.jsonl` (strict
schema), `<label>.resolved.jsonl` (+ `segments`), `doc-cache/` (5,900 of 6,021
cited ClimbMix documents), `arena-judgments/`, `support-judgments/`,
`support-metrics/`, `arena-summary.json`, `structural_stats.json`.

## Method notes that change the numbers

- **RAGDoll supplies the methodology; only execution is ours.** RAGDoll drives
  models through the `pi` local-agent binary, which is not installed on this
  host (`ragdoll doctor` → `[FAIL] pi binary not found`). So we import RAGDoll's
  `render_support_prompt` / `parse_support_label` / `support_metric` and its
  `render_arena_prompt` / `parse_verdict` / `TIE_VERDICTS` directly, and route
  the calls through the OpenAI-compatible endpoint the agent runs already use.
  The prompts and the arithmetic are RAGDoll's, unmodified.
- **Reference text comes from the official pyserini endpoint for all four runs**,
  not from our own trajectories. Our agents retrieve *chunks* (`<docid>_pN`) and
  the baselines retrieve whole documents; harvesting our trajectory text would
  hand the judge a short focused chunk for us and a full document for them. One
  shared source keeps the judge's view identical. (Our own dense server can no
  longer serve these ids at all — it now indexes chunk ids, so `/doc/batch` on a
  parent docid returns `found: 0`.)
- **Documents are truncated at 24,000 chars.** Median cited document is 4,420
  chars; the cap leaves 86.1% complete and does not drive cost.
- **Every arena pair is judged in both orders and pooled.** Order consistency
  runs 0.748–0.874, i.e. position bias is real; pooling measures it instead of
  burying it.
- **Judge-identity caveat.** The judge is `gpt-5.6-luna` — the model that
  generated *our* two runs, while the baselines came from `gpt-5.6-sol`. For
  support judging (an entailment check) self-preference is weak. For arena
  (a preference vote) it is exactly the failure mode, and it biases **toward
  us** — so our arena losses below are, if anything, understated.
- 16,936/16,936 support judgments completed. A first pass lost 459 calls to
  endpoint 429s, all landing in `base-singlepass`; those cache records were
  purged and re-judged at `--workers 5`. Effect was small
  (`wP_first` 0.6381 → 0.6342) but it is now a clean sample.

## Result 1 — conformance: all four runs are clean

`validate_rag_output` reports **zero violations** across all 476 narrative
objects. The wider audit adds no hard violation either: no duplicate references,
no empty text, narratives byte-identical to `trec_rag_2026_queries.tsv`, every
citation in range, every `citations` array ≤ 3.

Advisories only:

| run | advisory |
|---|---|
| ours-semantic | 399 uncited answer objects |
| ours-keyword | 410 uncited answer objects |
| base-singlepass | 1 answer object over 80 words |

One robustness note: `ours-keyword` has a narrative at **exactly 1024 words**
(the cap). Valid, but zero headroom — a one-word drift in a re-run breaks it.
`>= 1015 words`: ours-semantic 3, ours-keyword 4, each baseline 1.

## Result 2 — structural comparison (no LLM)

| run | narratives | words mean | min | max | objects | refs mean | cites/object | uncited rate | uncited objects |
|---|---|---|---|---|---|---|---|---|---|
| ours-semantic | 119 | 791.4 | 351 | 1021 | 24.8 | 15.92 | 1.37 | **13.50%** | 399 |
| ours-keyword | 119 | 796.1 | 338 | 1024 | 25.3 | 14.97 | 1.36 | **13.64%** | 410 |
| base-agentic-bm25 | 119 | 665.3 | 384 | 1017 | 20.8 | 9.92 | 1.72 | **0%** | 0 |
| base-singlepass | 119 | 679.9 | 293 | 1018 | 22.6 | 15.55 | 1.78 | **0%** | 0 |

Every reference in every run is cited at least once (`unused_refs_mean = 0`).

Reference overlap is negligible everywhere — mean per-topic Jaccard over
`references`:

| pair | Jaccard |
|---|---|
| ours-semantic vs ours-keyword | 0.0433 |
| ours-semantic vs base-agentic-bm25 | 0.0331 |
| ours-semantic vs base-singlepass | 0.0295 |
| ours-keyword vs base-agentic-bm25 | 0.0594 |
| ours-keyword vs base-singlepass | 0.0427 |
| base-agentic-bm25 vs base-singlepass | 0.0530 |

Even the two organizer baselines agree on only 5.3% of cited documents. On a
corpus this size there is no meaningful consensus set of "the relevant docs".

## Result 3 — the uncited-object tail

The 13.5% average badly misdescribes the distribution:

| | ours-semantic | ours-keyword |
|---|---|---|
| topics with **zero** uncited objects | 70 / 119 | 83 / 119 |
| topics with ≥ 5 uncited | 29 | 25 |
| worst topic | `rag2026-62` — 39/48 (81%) | `rag2026-62` — 63/65 (97%) |

Worst offenders (semantic): `rag2026-62` 81%, `rag2026-113` 68%, `rag2026-20`
65%, `rag2026-55` 62%, `rag2026-30` 56%, `rag2026-15` 53%, `rag2026-36` 52%.

Uncited objects are not shorter filler — median 29 words vs 32 for cited ones.
Reading them splits into three causes:

1. **Creative generation** — `rag2026-62` ("write a novel…"), `rag2026-113`
   ("outline a Black Mirror episode… suggest actors"). Sample uncited objects:
   *"The Boy Between Worlds."* / *"Jessie Buckley would be a strong choice for
   Lena…"*. Nothing in ClimbMix can ground these. Not fixable by retrieval.
2. **Engineering design** — `rag2026-36` (anti-cheat architecture),
   `rag2026-20` (tutoring-bot design). e.g. *"A simple design is two bots
   sharing one student record and one rule engine…"*. The corpus supports
   background, not the design.
3. **Procedural advice** — `rag2026-30` (supplier due diligence), `rag2026-15`
   (genocide-remembrance program). e.g. *"Ask for the legal names and addresses
   of the brand, importer, cut-and-sew factory…"*. These **are** groundable;
   the agent simply did not attach a reference. **This is the recoverable
   category.**

Both baselines cite every object on all three kinds of topic, so they trade
recall risk for precision risk; we do the opposite.

## Result 4 — anonymized pairwise battles (RAGDoll arena prompt)

1,428 battles = 119 narratives × 6 pairs × 2 orders. Zero unparsed, zero failed.

| pair (left \| right) | battles | left-right-ties | left pref rate | order consistency |
|---|---|---|---|---|
| base-agentic-bm25 \| base-singlepass | 238 | 203-34-1 | 0.855 | 0.874 |
| ours-keyword \| base-agentic-bm25 | 238 | 115-122-1 | **0.485** | 0.782 |
| ours-keyword \| base-singlepass | 238 | 185-52-1 | 0.779 | 0.824 |
| ours-semantic \| base-agentic-bm25 | 238 | 96-140-2 | **0.408** | 0.748 |
| ours-semantic \| base-singlepass | 238 | 186-52-0 | 0.782 | 0.815 |
| ours-semantic \| ours-keyword | 238 | 114-122-2 | 0.483 | 0.748 |

Overall preference rate against all opponents:

| run | rate | battles |
|---|---|---|
| base-agentic-bm25 | **0.6541** | 714 |
| ours-keyword | 0.5938 | 714 |
| ours-semantic | 0.5574 | 714 |
| base-singlepass | 0.1947 | 714 |

We beat the single-pass baseline decisively and lose to the agentic BM25
baseline — clearly for semantic, within noise for keyword. Keyword edges
semantic (0.483 left rate means keyword is preferred), consistent with the
support table.

**The citation gap does not explain the arena result.** Splitting our per-topic
win rate vs `base-agentic-bm25` by our own uncited rate:

| our uncited rate | ours-semantic topics / win rate | ours-keyword topics / win rate |
|---|---|---|
| 0% | 70 / 0.407 | 83 / 0.455 |
| 1–20% | 22 / 0.341 | 12 / 0.500 |
| > 20% | 27 / 0.463 | 24 / 0.583 |
| all | 119 / **0.408** | 119 / **0.485** |

Flat, even slightly *better* on high-uncited topics. Citations are absent from
the presented answers by construction (the organizer schema keeps `citations`
in a separate field from `text`), so the preference judge never sees them.
**Citation recall and answer preference are two independent problems.**

What does separate the runs is evidence density:

| run | numerals / 1k words | proper nouns / 1k | modals (should/may/can/might/could) / 1k |
|---|---|---|---|
| ours-semantic | 8.58 | 40.79 | 16.14 |
| ours-keyword | 8.78 | 40.69 | 16.07 |
| base-agentic-bm25 | **15.58** | **47.31** | **12.44** |
| base-singlepass | 13.21 | 46.55 | 15.75 |

The winner carries 1.8× the quantitative content and hedges less. Reading the
samples agrees: ours reads as a prescriptive checklist ("Prioritize…", "Fund…",
"Require…"), the winner as an evidence briefing ("4.3 times less likely to
remain", "34% fewer reported low-level offenses", "CAHOOTS requested police
backup in only 1% of its 2020 calls"). Note `base-singlepass` also scores high
on numerals and still loses badly, so density alone is not sufficient.

## Result 5 — weighted citation support (RAGDoll, all 119 narratives)

All citations judged (not first-only), so the `_all` columns are real.
16,936 judgments, all `completed`.

| run | wP_first | wR_first | wP_all | wR_all | hardP | hardR |
|---|---|---|---|---|---|---|
| ours-semantic | 0.5805 | 0.5174 | 0.5751 | 0.5117 | 0.2422 | 0.2146 |
| ours-keyword | 0.5897 | 0.5283 | 0.5858 | 0.5254 | 0.2410 | 0.2123 |
| base-agentic-bm25 | **0.6353** | **0.6353** | 0.6222 | 0.6222 | 0.3044 | 0.3044 |
| base-singlepass | 0.6342 | 0.6342 | 0.6279 | 0.6279 | 0.3043 | 0.3043 |

P == R exactly for both baselines — the spec's own prediction when every answer
object carries a citation, and a useful sanity check on the implementation.

Decomposing our weighted-recall deficit vs `base-agentic-bm25`:

| | ours-semantic | ours-keyword |
|---|---|---|
| total recall gap | 0.1179 | 0.1070 |
| …from **uncited objects** | 0.0631 (54%) | 0.0614 (57%) |
| …from **citation quality** | 0.0548 (46%) | 0.0456 (43%) |

Paired per-topic on weighted precision vs `base-agentic-bm25`:

| | better | worse | tied | mean diff |
|---|---|---|---|---|
| ours-semantic | 39 | 79 | 1 | −0.0548 |
| ours-keyword | 35 | 82 | 2 | −0.0456 |

And restricted to the topics where **we cite every object**, so the uncited
penalty is removed entirely:

| | topics | ours P = R | base P = R |
|---|---|---|---|
| ours-semantic | 70 | 0.5942 | 0.6529 |
| ours-keyword | 83 | 0.5794 | 0.6435 |

So roughly half the support deficit is structural (fixable by citing every
object) and half is that **our citations support their claims less often**, even
on our best topics.

## Result 6 — hand judgment, 10 narratives

Deterministic sample, every 12th narrative: `rag2026-{0,12,24,36,48,60,72,84,96,108}`.
Dump: `tasks/task-comparison/scripts/dump_sample_for_hand_judging.py`.

All 10 satisfy every Validation Rule. Word counts 613–1020. Coverage of
multi-part narratives is good — `rag2026-12` (vitamin D) answers every
sub-request including the IU table by age, the tolerable upper limits, D2 vs D3,
per-demographic risks, and mitigation; `rag2026-72` supplies the requested
mathematical derivations in LaTeX.

Four citations were verified verbatim against the fetched source documents:

| claim | cited docid | verdict |
|---|---|---|
| `rag2026-60` #1 "Founded in 2004 … PayPal cofounder Peter Thiel" | `shard_05811_12799` | **faithful** — doc reads *"Palantir was founded in 2004 by a team that includes PayPal cofounder Peter Thiel"* |
| `rag2026-12` #14 "400 IU infants, 600 IU 1–70, 800 IU over 70" | `shard_03738_51460` | **faithful** — RDA table present verbatim |
| `rag2026-24` #9 "price fell from £180 per ton to about £65 by 1965" | `shard_04496_76870` | **faithful** — verbatim |
| `rag2026-0` #5 "ninth-grade students needed early health-care exposure" | `shard_04399_16517` | **faithful** — *"Students in ninth grade need exposure to health careers and math and science support"* |

Worth flagging: Palantir was founded in **2003**, and `base-agentic-bm25` says
2003. Our answer says 2004 because the cited ClimbMix document says 2004. So we
are correctly grounded in a wrong document, and **support scoring will award
that full support**. Faithfulness and factual accuracy are different measures
and only the first is being scored.

## Result 7 — hand analysis of the ours-keyword losses to base-agentic-bm25

Follow-up question: read the topics where `ours-keyword` lost to
`base-agentic-bm25` *in both presentation orders*, so order bias is excluded.

Everything below is reproduced by
`worklogs/assets/2026-08-04-keyword-vs-agentic-loss-analysis.py` (restore the
archived eval tree first — see `~/local_large/trec-rag-26/ARCHIVE-MANIFEST-2026-08-04.md`).
The side-by-side answer text actually read by hand is
`worklogs/assets/2026-08-04-keyword-vs-agentic-loss-sample.txt`.

```bash
uv run --no-project python \
    worklogs/assets/2026-08-04-keyword-vs-agentic-loss-analysis.py \
    --dump-sample worklogs/assets
```

### The framing has to be corrected first

This pair is **0.485 over 238 battles (115-122-1)** — a dead heat, not a defeat.
Splitting the 119 narratives by both-order agreement:

| outcome (both orders agree) | topics |
|---|---|
| lost to base-agentic-bm25 | 48 |
| won against base-agentic-bm25 | 45 |
| order flip (judge disagreed with itself) | 25 |
| tie verdict | 1 |

48 consistent losses are almost exactly matched by 45 consistent wins. So "the
cases where ours-keyword failed" is a sample of ~40% of topics drawn from a coin
flip, and anything found only in the losses has to be checked against the wins
before it can be called a cause. Three of the four hypotheses below died on
exactly that check.

The 48 both-order losses: `rag2026-1 -3 -6 -7 -10 -12 -16 -17 -19 -21 -22 -28
-30 -32 -38 -39 -40 -44 -47 -49 -56 -57 -58 -59 -60 -62 -63 -66 -68 -74 -77 -78
-80 -81 -82 -86 -87 -88 -89 -95 -99 -102 -104 -107 -108 -109 -115 -116`.

12 were read in full side by side (every 4th): `rag2026-1 -10 -19 -30 -40 -56
-60 -68 -80 -87 -99 -108`.

### Our answers are identical whether we win or lose

| feature (mean) | ours.loss | ours.win | ours.split | base.loss | base.win |
|---|---|---|---|---|---|
| words | 793.8 | 800.2 | 793.0 | **730.9** | **613.7** |
| sentences | 26.0 | 25.2 | 24.0 | 23.4 | 19.1 |
| uncited fraction | 0.09 | 0.14 | 0.06 | 0.00 | 0.00 |
| citations / sentence | 1.45 | 1.37 | 1.54 | 1.72 | 1.76 |
| distinct refs | 15.3 | 14.8 | 14.6 | 9.9 | 10.1 |
| numerals / 1k words | 10.1 | 6.8 | 8.9 | **17.1** | **14.3** |
| modals / 1k words | 19.7 | 20.1 | 17.7 | 14.9 | 16.6 |

Every one of our columns is flat. Our uncited fraction is *higher* on topics we
won. What varies is the opponent: on topics we lost, the baseline wrote 731
words; on topics we won, 614.

### The outcome tracks the baseline's answer length

| correlation with our preference | r |
|---|---|
| our word count | **+0.019** |
| baseline word count | **−0.429** |
| word gap (ours − baseline) | +0.416 |
| baseline sentence count | −0.390 |

| baseline length quartile | our preference rate |
|---|---|
| 384–589 words | 0.655 |
| 589–645 | 0.621 |
| 646–735 | 0.552 |
| 737–1017 | **0.156** |

Our own length quartiles produce 0.466 / 0.431 / 0.655 / 0.406 — no trend. We
do not win by writing more; we win when the baseline writes less.

### Is that verbosity bias, or does the longer answer carry more?

Crossing the length gap with the fact-density gap (medians: +144 words,
−4.57 numerals/1k) separates the two:

| | baseline denser | ours denser |
|---|---|---|
| **ours longer** | 0.704 (n=27) | 0.625 (n=32) |
| **baseline longer or equal** | 0.318 (n=33) | 0.315 (n=27) |

The rows separate by ~0.35; the columns do not separate at all. Conditional on
relative length, being the more fact-dense answer is worth nothing to this
judge. That is a caution about the arena measure, not a compliment to us:
the baseline's longest answers are also its densest (11.2 numerals/1k in its
shortest quartile rising to 23.3 in its longest), so length and substance are
confounded in the baseline and the 2×2 can only show that length is the
variable carrying the signal.

This qualifies Result 4. Evidence density does separate the four *systems* in
aggregate; it does not predict which of two answers wins a *given* battle.

### What hand reading found anyway

The 12 read side by side show a consistent qualitative difference that the
scores above say is not what decided the battles — worth fixing on its merits:

- **The baseline supplies the figure where we supply the category.** rag2026-56
  (WWII bombing) is the clearest: it gives Dresden at 22,700–25,000 "not the
  propagandistic totals of 200,000 or more", RAF accuracy at ~30% of missions
  reaching target, Tokyo at 279 B-29s / 90,000–100,000 dead / 267,000 buildings.
  We call Dresden "a contested case" and never state what is contested.
- **The baseline volunteers the decision-relevant fact the asker did not think
  to ask for.** rag2026-30: UFLPA makes unknown cotton origin presumptively
  disqualifying for a US importer — the single most consequential fact for that
  purchasing committee, and we never mention it. rag2026-68: reviews find
  limited evidence that school resource officers improve safety — live in any
  post-Uvalde school-safety budget argument, and absent from ours. rag2026-99:
  coal and gas were 73% of unplanned outages in Winter Storm Uri, which directly
  rebuts the members' "the lights won't stay on" worry; we assert a portfolio is
  needed but never rebut the premise.
- **Instruction-following slip.** rag2026-60 asked for a ~10-minute-read
  article. We produced 38 short declaratives with no article shape, 16 of them
  uncited, almost entirely Q1-2024 financials — omitting the TITAN ($178.4M) and
  Maven ($480M) contracts that explain the 2024–25 defence story.

### Four defects found by reading, and whether each explains the losses

| defect | measured | explains losses? |
|---|---|---|
| figures available in **our own cited docs** but unused | 42% of baseline-only figures on lost topics | **No** — 45% on won topics, 47% on flips |
| Australian localization on locale-free narratives | 9 topics, ours-pref 0.278 vs 0.509 elsewhere | Suggestive, n=9 |
| non-Latin script leak | 1 sentence (rag2026-10) | No — single instance |
| meta-reference to the retrieval | 3 sentences (rag2026-3, -47, -99) | No — 3 instances |

The first is the substantive finding and the biggest surprise. Taking figures
the baseline stated that we did not, and asking whether they were present in a
document *we ourselves cited*: **42% were.** On rag2026-60 we cited
`shard_04990_76242`, which contains the string "$480 million AI prototype
contract and the $178 million TITAN intelligent edge AI deal", and wrote an
article about Palantir's 2024–25 success naming neither. On rag2026-56 four of
our ten cited docs carry a specific Dresden figure. On rag2026-68 three of ours
discuss SROs. This is a **synthesis failure, not a retrieval failure** — the
retriever put the material in front of the generator and the generator dropped
it. But it is flat across wins and losses, so it is a standing property of the
system rather than the cause of these battles.

The localization finding: on 9 topics our answer localizes to Australia
(`call 000`, "In Australia, obtain state or territory-specific legal advice")
where the baseline does not and the narrative names no country. Our preference
rate on those is 0.278 against 0.509 elsewhere. n=9 is too small to act on
alone, but the direction is consistent with reading — rag2026-1 tells a grieving
family to "call 000", which is simply wrong guidance for an unlocalized asker,
and rag2026-40 answers a US-shaped employment question under Australian law
while the baseline cites ADA/EEOC.

Two conformance-adjacent defects worth a lint rule, both zero in both baselines:
`非開催` (Japanese "non-holding") appears mid-sentence in our rag2026-10 English
output; and three sentences address the retrieval rather than the user
("Federal programs described in the research…", "The UAE example described in
the corpus…"). Neither is a spec violation, both are visible to any reader.

## Result 8 — are the dense and sparse retrievers complementary?

Result 2 reported a cited-reference Jaccard of 0.0433 between `ours-semantic`
and `ours-keyword`, but that conflates two things: what the retriever returned,
and what the generator then chose to cite. This reads the **trajectories**
(`data/outputs/aus_agent/*.trajectory.json`, `retrieved_docids`) instead.

```bash
uv run --no-project python \
    worklogs/assets/2026-08-04-dense-vs-sparse-complementarity.py
```

**The two runs are cleanly single-engine.** Every `search` tool call carries an
explicit `search_engine`: 1,073 calls all `"semantic"` for `test-semantic-119`,
1,070 all `"keyword"` for `test-keyword-119`, across all 119 topics each. The
identical `run_desc` on both is misleading — it records `prompt=default` for
both and never mentions the engine.

**Caveat that bounds every number below:** the agent writes its own query per
engine (dense queries average 9.8 words, sparse 8.5), so this measures
*pipeline* complementarity, not two ranking functions over identical queries.
Some of the disjointness is query variation. It is still the operationally
relevant quantity — it answers "what would fusing these two runs buy" — but it
is not a controlled retriever A/B, and a fixed-query rerun would be needed to
attribute the split between engine and query.

### They are almost entirely disjoint

| retrieved sets (119 topics) | |
|---|---|
| docs/topic | dense 66.8, sparse 69.0 |
| Jaccard | mean **0.0355**, median 0.0250, max 0.242 |
| overlap coefficient | 0.0737 |
| unique to dense | **93.1%** of its own set |
| unique to sparse | **93.5%** of its own set |
| union ÷ larger set | **1.756×** |
| topics with *zero* overlap | **21 / 119** |

Cited references follow: 86.1% of the dense run's citations point at documents
the sparse run never returned, and 88.1% vice versa. Each run cites only ~23–24%
of what it retrieves, so the disjointness is set by retrieval, not by citation
selection.

### The non-overlapping half is not junk

If the unique material were worse, fusion would add noise rather than coverage.
Splitting all 8,025 completed support judgments by whether the *other* retriever
also returned that document:

| run | document found by | n | FS | PS | NS | mean (0–2) |
|---|---|---|---|---|---|---|
| ours-semantic | both | 634 | 150 | 419 | 65 | 1.134 |
| ours-semantic | only this one | 3,347 | 614 | 2,471 | 262 | **1.105** |
| ours-keyword | both | 498 | 110 | 344 | 44 | 1.133 |
| ours-keyword | only this one | 3,546 | 664 | 2,647 | 235 | **1.121** |

A 0.01–0.03 gap on a 0–2 scale. The 93% that only one retriever found supports
its sentences as well as the 7% both found. Two retrievers, near-disjoint
evidence, equal downstream support quality, and near-equal end-to-end scores
(wP 0.5805 vs 0.5897; arena 0.557 vs 0.594).

### But they succeed on the same topics, which caps the gain

| | |
|---|---|
| corr(dense, sparse) per-topic weighted precision | **+0.538** |
| mean per-topic \|difference\| | 0.0793 |
| dense better / sparse better | 58 / 60 topics |
| oracle "pick the better run per topic" | 0.6247 (**+0.035** over the better single run) |
| arena vs `base-agentic-bm25`, corr | +0.537 |
| same arena outcome on | 70 / 119 topics |
| exactly one of the two beats the baseline | 30 topics |
| oracle pick-better-run, arena | 0.576 (vs 0.487 sparse alone) |

This is the part that tempers the headline. The evidence is complementary; the
*outcomes* are correlated at ~0.54. Topics are jointly easy or jointly hard —
the two retrievers mostly fail on the same narratives for reasons upstream of
retrieval.

**What the oracle rows do and do not measure.** "Pick the better run per topic"
requires *both full trajectories*, i.e. running two agents and choosing between
their finished answers. That is a different architecture from aus_agent, not an
upper bound for it, and its return is poor: **+0.035** weighted precision (0.6247
vs `base-agentic-bm25`'s 0.6353) for 2× the retrieval and generation cost. Read
those rows as evidence *against* the two-agent design, not as a ceiling for the
single-agent one. The arena oracle looks better (0.576 vs 0.487 for sparse
alone, 30 topics where exactly one of the two beats the baseline) but Result 7
showed the arena verdict tracks relative length, so discount it.

**Reading — and this is a correction to how these numbers were first framed.**
The natural conclusion from a disjointness measurement is "fuse the two runs",
and that is wrong for this system. Fusion (RRF and friends) combines *ranked
lists over a shared query*; aus_agent has neither prerequisite. The agent writes
a different query per engine by design, and `commit_context` already performs
selection with the passage text in front of it — an LLM review step, not a
rank-combination step. There is no ranked-list merge to do.

What the 93% disjointness actually measures for this architecture is **recall
exposure per lead**: `commit_context` can only select from what was staged, so a
lead searched on one engine is structurally blind to ~93% of what the other
engine would have surfaced for it. That is a "the agent never saw the
candidates" problem, and the fix is how the search budget is allocated across
engines (Result 9), not a merge algorithm. The one place a fusion-like step
survives is as a *staging-budget* device — pairing one lead across both engines
stages 2×k results, and interleaving to a cap would bound that. At 2–3 leads per
round it is unnecessary.

## Result 9 — how the agent spends its search budget, and what to change

Result 8 says dense and sparse return near-disjoint documents. This asks the
follow-up: given both engines, how does the agent actually allocate across them?

```bash
uv run --no-project python \
    worklogs/assets/2026-08-04-search-strategy-diagnosis.py
```

A *round* here is a maximal run of consecutive `search` calls delimited by a
reasoning item or a `commit_context` call — which is exactly the unit
`commit_context` reviews, since everything staged in a round must be committed
on the immediately following turn.

| run | topics | rounds | searches | /round | commits | rounds using both engines | rounds pairing **the same lead** across engines |
|---|---|---|---|---|---|---|---|
| cmp-base-densesparse | 10 | 2.3 | 9.4 | 4.1 | 2.3 | 26% | **4%** |
| promptab-default | 10 | 2.3 | 9.1 | 4.0 | 2.3 | 43% | **4%** |
| promptab-firsthand | 10 | 2.7 | 9.7 | 3.6 | 2.7 | 37% | **4%** |
| chunknav-dev10 | 10 | 2.4 | 8.8 | 3.7 | 2.4 | 33% | **0%** |
| test-semantic-119 | 119 | 2.4 | 9.0 | 3.8 | 2.4 | 0% | 0% |
| test-keyword-119 | 119 | 2.3 | 9.0 | 3.8 | 2.4 | 0% | 0% |

("same lead" = two searches to *different* engines in one round with query token
Jaccard ≥ 0.5 — a loose proxy, loose in the generous direction, so a low number
is meaningful.)

Three findings:

1. **The shape is invariant.** ~2.3 rounds, ~9 searches, ~3.8 per round, ~2.3
   commits — identical across every run, every prompt variant, both engines,
   and both the 10-topic dev sets and the 119-topic test set.
2. **The second engine is spent as an extra lead slot, never as a second view
   of one lead.** Cross-engine query similarity averages 0.09. A representative
   round: eight `semantic` queries and three `keyword` queries, all on different
   facets. Combined with Result 8, this means no lead in any run has ever been
   resolved against both retrievers' candidates.
3. **When both engines are offered the agent barely uses the sparse one** —
   86:8, 81:10, 84:13 semantic:keyword. The keyword engine gets 9–13% of
   searches despite `ours-keyword` scoring *better* than `ours-semantic`
   end-to-end (Result 4, Result 5).

**Nothing is capping trajectory length.** `DEFAULT_SAFETY_MAX_ROUNDS = 100`
(`src/systems/aus_agent/agent.py:58`) and all 238 test-119 trajectories report
`status: completed` — none hit the safety cap or the grace window. The agent
stops at ~2.3 rounds entirely by its own judgement, with ~97 rounds of budget
unused. Longer trajectories are therefore a *stopping-rule* problem, not a
limit to raise.

### Two changes, very different evidence

**(A) Reallocate: fewer leads per round, both engines on each.** Volume-neutral
— the same ~5 searches per round, spent as 2–3 leads × 2 engines instead of 5
leads × 1. Result 8's 93% disjointness is the argument: today every lead is
reviewed against roughly half its available evidence and the agent cannot know
what it missed. This is close to free and should be tested alone.

**(B) Longer trajectories.** The measurements argue against this *as a
standalone change*:

- Each run cites only **23–24%** of what it retrieves.
- Result 7: **42–47%** of the figures the winning baseline used were sitting in
  documents *we cited* and went unused.
- `base-agentic-bm25` beats us on support precision **0.635 vs 0.590 with 9.9
  references per topic against our 15.0** — fewer documents, better used.

Coverage does not look like the binding constraint; selection and use do. More
rounds adds volume upstream of the actual bottleneck. The operator's framing was
*depth on existing leads* rather than more leads, which is the right instinct —
but a prompt asking for more rounds will most likely produce more leads, which
is precisely what the data argues against.

### The coupling that would sink (A) silently

`commit_context`'s own tool description
(`src/systems/aus_agent/tools/commit_context.py:10`) currently instructs:

> Do not select an id already committed, **or a semantically redundant result
> supporting the same claim**, unless it adds materially different evidence.

Pairing both engines on one lead produces exactly that redundancy by
construction. Under the current rule the agent would pay for the dual retrieval
and then discard the second engine's contribution as duplicate. **(A) is not a
search-prompt change; it is a search-prompt change plus a `commit_context`
selection-rule change, and they have to ship together.**

The whole tool description is ours and should be rewritten, not patched — it is
the only place the selection policy is stated, so it is the natural home for the
new one. The replacement should make the agent **adjudicate rather than
de-duplicate**: when one lead returns results from both engines, reason over
them and keep either the *complementary* ones (each contributing distinct
evidence) or the *better* one where they overlap, against stated criteria —

- concrete figures, dates, named findings over categorical description;
- worked examples over generalities;
- primary or better-sourced over secondary;
- and, where two results say the same thing, the one that says it more
  precisely — with the duplicate rejected *by that comparison*, not by a blanket
  redundancy rule.

Two things make this the highest-value edit in the section. First, it is the
same lever Result 7 identified from the other direction: the winning baseline's
advantage was concrete figures we already had in hand and did not use, so
pushing selection toward specificity attacks the retrieval-allocation problem
and the synthesis problem at once. Second, per the reasoning guide's "give the
model the task, constraints, and desired output format" and "avoid prescribing
intermediate steps", criteria are exactly the right shape for this instruction —
the `reason` field the tool already requires per document becomes the place the
agent states which criterion the document won on, which is also a free
instrument for checking whether the policy is being followed.

Note the ledger already caps commits at `DEFAULT_MAX_COMMITTED_PER_STEP = 10`
(`agent.py:64`), so a paired round staging 2 leads × 2 engines × k=8 = 32
results still forces a sparse selection. The cap is not the constraint; the
selection rule is.

### Stopping rule

Do not hardcode a round count — a number in a prompt becomes a target and the
agent pads to it. Tie continuation to marginal yield: continue while the last
round committed evidence that changed the answer plan; stop when a round returns
only what is already committed. That makes trajectory length an output of topic
difficulty rather than an input. Pair it with an explicit lead ledger (name
leads up front, mark each resolved / refuted / needs-depth) so "more rounds"
means resolving leads rather than spawning them.

### Reasoning mode and effort are not plumbed

Per the OpenAI reasoning guide
(<https://developers.openai.com/api/docs/guides/reasoning>), GPT-5.6 exposes
**two independent** Responses-API parameters:

- `reasoning.mode` — `standard` (default) | `pro`. `pro` performs more model
  work per turn, aggregated and billed at the model's standard token rates.
- `reasoning.effort` — `none` | `minimal` | `low` | `medium` | `high` | `xhigh`
  | `max`, defaulting to `medium` in **both** modes. The guide's own mapping:
  `low` for "tool-use, planning"; `high` for "agentic coding and research";
  `xhigh` for "deep research, asynchronous workflows".

`src/systems/aus_agent/providers/openai.py:93` passes only
`reasoning={"summary": "auto"}` — neither parameter is set, no CLI flag, no env
var. **Every run to date is `mode=standard, effort=medium` by default.**

The guide's guidance reorders the recommendations in this section rather than
just adding one:

1. **"Treat `reasoning.effort` as a tuning knob, not the primary way to recover
   quality."** This is the vendor saying what the measurements already suggest:
   not pairing the engines and not using facts already in hand are policy and
   instruction gaps, not the model failing to think hard enough. Effort is not
   the fix for either.
2. **"For agentic workflows, define what counts as done and how the model should
   verify its work."** This is exactly the stopping-rule problem above, and the
   guide ranks it as *the* agentic lever — ahead of effort tuning. Strong
   support for making termination a defined done-condition rather than leaving
   it to the model's judgement, which is what produces the invariant 2.3 rounds.
3. **"Avoid prescribing intermediate steps. Give the model the task,
   constraints, and desired output format."** This tempers the lead-ledger
   proposal above: express it as a done-definition and a set of selection
   criteria, *not* as a step script ("do 2 leads, then commit, then repeat").
   The former is what the guide recommends; the latter is what it warns against.

Where more model work per turn *should* pay is the two places this section
proposes to make harder: a `commit_context` step that must adjudicate competing
results from two engines against criteria, and a done-condition that requires
judging marginal yield. Both are per-turn deliberation.

**Two blockers to clear before enabling either parameter.**

`max_output_tokens` is **16000** (`providers/openai.py:50`) against the guide's
"reserve at least 25,000 tokens for reasoning and outputs when you start
experimenting". Reasoning tokens are billed as output tokens *and* count against
this ceiling, so raising effort or mode without raising this budget pushes turns
toward the limit.

And the provider **does not check for truncation**: the guide says a capped
response returns `status: "incomplete"` with
`incomplete_details.reason: "max_output_tokens"`, and nothing in
`providers/openai.py` inspects either field. There is an `EMPTY_RESPONSE_RETRIES`
loop, which would catch a turn truncated to nothing, but a *partially* truncated
turn would be accepted silently. Enabling `pro` or `high` against a 16k ceiling
with no incomplete detection is a good way to get quiet truncation that looks
like a quality regression.

Two further notes. Reasoning state is replayed byte-for-byte across turns
(`include=["reasoning.encrypted_content"]`, required with `store=False`), and
GPT-5.6 defaults `reasoning.context` to `all_turns` — earlier turns' reasoning
is rendered into later samples. So richer reasoning grows the replayed prefix
every round: cost compounds with trajectory length rather than adding linearly,
and if higher effort *also* produces longer trajectories the two multiply. The
guide's `phase` field (`commentary` / `final_answer`) is GPT-5.5/5.4 only and
does not apply here.

Test mode and effort as their own variables *after* the prompt changes land, and
raise `max_output_tokens` plus add incomplete-detection first.

## What to act on

1. **Stop emitting uncited answer objects on groundable topics.** Worth ~0.063
   weighted recall, and it is the half of the support gap with a mechanical fix.
   The spec's own guidance points the right way: for genuinely ungroundable
   claims the fix is to *not make the claim*, not to make it uncited. Cause 3
   (procedural advice) is the recoverable slice; causes 1–2 (creative, design)
   argue for suppressing the unsupported sentence instead.
2. **Citation quality is a separate, larger-than-expected problem** — 0.594 vs
   0.653 precision even on our clean topics, and we lose the paired per-topic
   comparison 79–39. Worth judging *why*: wrong document chosen from the staged
   set, or claim drifting beyond what the document says.
3. **Answer style, not retrieval, is what loses the battles.** Evidence density
   (numerals, named findings) and less hedging is the lever, and it is a prompt
   change, not an index change. *Qualified by Result 7:* density separates the
   four systems in aggregate but does not predict individual battles once
   relative length is controlled. Treat it as a quality goal, not as an arena
   lever.
4. **Use the documents we already retrieved.** 42–47% of the figures the
   agentic baseline stated and we omitted were sitting in documents *we cited*
   (Result 7). This is generation dropping material the retriever supplied, it
   is uniform across wins and losses, and it is the largest concrete quality gap
   found by hand. A prompt change ("prefer the specific figure, date or named
   finding from the cited passage over a categorical paraphrase") targets it
   directly and is cheap to A/B on the existing harness.
5. **Do not localize to Australia unless the narrative does.** 9 topics
   volunteer Australian emergency numbers or jurisdiction where the narrative
   names no country; our preference rate on them is 0.278 vs 0.509 elsewhere.
   Small n, but "call 000" is wrong guidance for an unlocalized asker regardless
   of what the arena says.
6. **Add two cheap output lints**, both zero in both baselines: non-Latin script
   in an English answer (1 sentence), and sentences that address the retrieval
   rather than the user ("described in the research", "in the corpus" — 3
   sentences).
7. **keyword ≥ semantic on every measure here** (arena 0.594 vs 0.557, support
   0.590 vs 0.581, fewer uncited topics 83 vs 70). This is the one comparison
   with no judge-identity confound, since both sides share a generator. But
   Result 8 says do *not* read this as "drop semantic": the two retrievers share
   only 3.6% of what they return, and the unique 93% is as well-supported as the
   shared 7%.
8. **Rewrite `commit_context`'s selection rule, and pair the engines per lead —
   as one change.** Highest-value item in Result 9. The current rule discards
   "semantically redundant" results, which is exactly what dual-engine pairing
   produces, so shipping the search change alone would pay for the retrieval and
   throw away the result. Replace blanket de-duplication with adjudication
   against specificity criteria; that also attacks item 4 from the other side.
   *Not* fusion — `commit_context` is already the selection step (Result 8).
9. **Make termination a defined done-condition.** All 238 test trajectories
   stopped by choice at ~2.3 rounds with `safety_max_rounds=100` unused, so
   nothing needs raising. The reasoning guide names "define what counts as done
   and how the model should verify its work" as *the* agentic lever, above
   effort tuning. Express it as a done-condition plus a lead ledger, never as a
   round count or a step script.
10. **Before touching `reasoning.mode`/`effort`: raise `max_output_tokens` from
    16000 (guide recommends ≥25,000 reserve) and add `status: "incomplete"` /
    `incomplete_details` detection to the OpenAI provider.** Neither exists
    today, and both failure modes look like quality regressions rather than
    truncation. Then test mode and effort as their own variables.

## Not done

- UMBRELA relevance grading of cited references. It is a *development-data*
  diagnostic in the 2026 spec, not an announced test measure
  (`references/development-data.md`), so it was deprioritized below the two
  announced rubric-free measures.
- Nugget/AutoNuggetizer scoring — needs nuggets, which do not exist for the
  test narratives. Auto-creating them from the pooled cited passages is possible
  but is a separate experiment.
- A second judge model for agreement. Everything here is single-judge; the
  arena numbers in particular deserve a `gpt-5.6-sol` or Bedrock cross-check
  before being treated as settled. Result 7 sharpens this: the judge's verdict
  in the keyword-vs-agentic pair tracks relative length (r = ±0.42) and is
  indifferent to relative fact density once length is controlled. Whether that
  is a property of *this* judge or of the arena protocol cannot be settled
  without a second judge, and it bears directly on how much weight the arena
  measure should carry.
- A length-controlled arena re-run. The cleanest test of the above is to
  regenerate both sides at a matched word budget and re-judge; if the gap
  closes, the 0.485 is largely a length artifact.
- A **fixed-query** dense-vs-sparse comparison. Result 8's 93% disjointness is
  measured across runs whose queries differ (the agent writes per-engine
  wording), so engine and query effects are confounded. Replaying one run's
  queries against both engines separates them, and decides whether the lever is
  fusion or query generation. Cheap: the 1,073 + 1,070 queries are already in
  the trajectories.
- The A/B itself. The `promptab-*` harness already runs prompt variants; the
  variants Result 9 argues for are (a) paired-lead retrieval + rewritten
  `commit_context` selection rule, (b) a done-condition stopping rule, (c) a
  synthesis-side specificity instruction, each alone before any combination.
  Worth instrumenting per-lead engine coverage and same-lead cross-engine
  overlap in the trajectory, so compliance can be checked before the scores are
  read — the 4% baseline in Result 9 exists only because that was measured.
- Why the agent under-uses the sparse engine when both are offered (9–13% of
  searches) despite `ours-keyword` outscoring `ours-semantic` end-to-end. Tool
  description wording, ordering, or a genuine model preference — unknown.
- Whether the unused-figure finding (Result 7, 42–47%) is a generation choice
  or a context-window truncation. Distinguishing them needs the aus_agent
  trajectories, not the submission artifacts — the staged passages the
  generator actually saw are not in the eval tree.
- 121 of 6,021 cited documents never resolved (persistent HTTP 429). Coverage is
  96.6–97.1% of citation pairs and is even across runs, so it does not bias the
  comparison, but it is not 100%.
