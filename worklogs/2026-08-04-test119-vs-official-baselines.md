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
   change, not an index change.
4. **keyword ≥ semantic on every measure here** (arena 0.594 vs 0.557, support
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
  before being treated as settled.
- 121 of 6,021 cited documents never resolved (persistent HTTP 429). Coverage is
  96.6–97.1% of citation pairs and is even across runs, so it does not bias the
  comparison, but it is not 100%.
