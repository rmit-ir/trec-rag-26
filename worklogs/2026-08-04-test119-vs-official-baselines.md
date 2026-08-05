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
   with no judge-identity confound, since both sides share a generator.

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
- Whether the unused-figure finding (Result 7, 42–47%) is a generation choice
  or a context-window truncation. Distinguishing them needs the aus_agent
  trajectories, not the submission artifacts — the staged passages the
  generator actually saw are not in the eval tree.
- 121 of 6,021 cited documents never resolved (persistent HTTP 429). Coverage is
  96.6–97.1% of citation pairs and is even across runs, so it does not bias the
  comparison, but it is not 100%.
