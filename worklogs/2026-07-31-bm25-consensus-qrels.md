# 2026-07-31 — Consensus qrels via a disagreement-triggered prompt ensemble

Stage A of the BM25 `k1`/`b` sweep was judged by one prompt (`facet-name-v1`) and
came out essentially flat: the best cell beat the pyserini-default baseline by
**+0.0007 nDCG@10**, on a judge that reproduces its own grade only ~84 % of the
time at temperature 0 (`worklogs/2026-07-31-judge-temperature-sweep.md`). A
+0.0007 difference measured with a ±16 %-noisy instrument is not a result.

This session built and ran a second, differently-calibrated label set to see
whether the flatness is the *grid's* or the *judge's*, and re-scored the grid
against it. It also fixed three defects the real run exposed.

**Spend: $3.895 → $4.062 of the $50 cap (8.1 %).** The tiebreak cost $0.167.

Everything below is recomputed by
[`assets/2026-07-31-consensus-analysis.py`](assets/2026-07-31-consensus-analysis.py)
from the run dir; its output is saved verbatim as
[`assets/2026-07-31-consensus-analysis.out`](assets/2026-07-31-consensus-analysis.out).
The tiebreak judge run's log is
[`assets/2026-07-31-consensus-tiebreak.log`](assets/2026-07-31-consensus-tiebreak.log).

---

## 1. Why not textbook self-consistency

PLAN §3.2 had penciled in a self-consistency vote: same prompt, resampled at
temperature > 0, majority wins. The operator pushed back — *"will it be the same
prompt with temp 0.0? Consider the vote idea, but with different prompts and
potentially different temp"* — and that instinct is right, for a reason our own
measurements already contained.

Judge error decomposes into two parts:

1. **Random sampling noise.** Measured: temp-0 self-agreement 0.840, so ~16 % of
   grades are a coin-flip the judge would re-flip differently.
2. **Systematic prompt bias.** `umbrela-v1` puts 72.5 % of its mass on grade 1;
   `facet-v1` puts 75 % at ≥ 2. Neither prompt says anything to the judge about
   how often relevance should occur, so **grade frequency is an accident of
   wording**.

Resampling one prompt attacks only #1 — and it attacks it badly, because raising
the temperature degrades every sample it draws (per-sample stability falls
0.84 → ~0.65 at temp 1.0). It cannot touch #2 at all: three samples from a
prompt that over-uses grade 2 agree on grade 2 and produce a *confidently*
miscalibrated qrel. Averaging a biased instrument yields a precise wrong number.

A prompt-diverse ensemble at temperature 0 attacks both: each vote is drawn at
the prompt's most stable setting, and the votes disagree about *calibration*, not
just about sampling.

## 2. The cascade the operator specified

> *"Do 2-prompt adding rare3 only, then only for pairs that the prompts disagree
> run another prompt and do median"* — and, on the disagreement rule, **"≥ 2
> grades apart"**.

So:

1. Two prompts judge the **whole** pool: `facet-name-v1` (Stage A's, already
   paid for) + `facet-rare3-v1`.
2. **|Δ| ≤ 1 → agreement**, settled free as the **rounded-down mean**
   (`(a+b)//2`, so (2,3) → 2). Round *down* deliberately: when two judges split
   on relevance the experiment understates rather than credits a config for a
   chunk only one judge liked.
3. **|Δ| ≥ 2 → conflict**, escalated to a third prompt (`facet-v1`) and settled
   by **median of three** — a median, not a mean, so the label is always a grade
   some judge actually assigned and one outlier cannot drag it.

The threshold is the whole cost argument. Escalating on *any* inequality would
have escalated 52.0 % of the pool (~$0.98) mostly to arbitrate noise between
adjacent grades. Escalating on |Δ| ≥ 2 escalated **10.3 %** ($0.167) and spent it
only where the two prompts genuinely disagree about whether a passage is useful
at all.

The `umbrela-*` variants were excluded from the ensemble: a prompt with a 72.5 %
grade-1 collapse is not a second opinion, it is a broken instrument, and
including it would have dragged every conflict toward 1.

## 3. Measured agreement (full pool, n=12,840 doubly-graded)

| \|Δ\| | count | share |
|---|---|---|
| 0 | 6,169 | 48.0 % |
| 1 | 5,348 | 41.7 % |
| 2 | 1,222 | 9.5 % |
| 3 | 101 | 0.8 % |

89.7 % settled free; 1,320 pairs escalated. A 478-pair pilot overlap had
predicted 7.1 % escalation — the full pool came in at 10.3 %, so the pilot was
optimistic by ~3 points and the tiebreak cost $0.19 rather than the $0.13 quoted
at the authorization gate. Flagged to the operator before spending.

Conflicts are about *existence* of relevance, not rubric level, and they touch
**116 of 119 topics** — this is the two prompts' calibration differing
everywhere, not a few pathological queries:

| votes | count |
|---|---|
| (0, 2) | 1,016 |
| (1, 3) | 206 |
| (0, 3) | 101 |

## 4. The bias resampling cannot fix

Same 12,846 passages, three prompts:

| prompt | n | 0 | 1 | 2 | 3 | mean |
|---|---|---|---|---|---|---|
| `facet-name-v1` (primary) | 12,841 | 2,213 | 381 | 6,486 | **3,761** | 1.919 |
| `facet-rare3-v1` (secondary) | 12,845 | 3,349 | 2,238 | 6,885 | **373** | 1.333 |
| `facet-v1` (tiebreak, conflicts only) | 1,323 | 564 | 339 | 400 | 20 | 0.906 |
| **CONSENSUS** | 12,846 | 2,950 | 2,280 | 7,279 | **337** | 1.389 |

(Per-prompt rows come from the cache snapshots restricted to this run's pool, not
from `consensus-pairs.jsonl`'s `grades` tuple — a `single`-status pair stores a
1-tuple, so positional indexing would misattribute those 6 votes. The tiebreak
row counts only the 1,323 votes that actually broke a tie; its snapshot holds 80
further in-pool pairs graded during WP6 calibration, which decided nothing here.)

`facet-name-v1` hands out grade 3 to **29 %** of everything it sees;
`facet-rare3-v1`, which is the same prompt plus an explicit base-rate anchor,
gives it to **2.9 %** — a 10× difference from one paragraph of calibration text,
on identical passages. `facet-name-v1` also barely uses grade 1 (3 %), collapsing
the middle of the scale. No amount of resampling `facet-name-v1` at any
temperature would have revealed this; only a second prompt does.

Note the tiebreak's mean (0.906) is far below both — expected and not a bug: it
only ever sees the 1,320 pairs the other two *fought* over, which are
disproportionately marginal passages, not a random sample.

How the tiebreak actually broke the ties:

| votes | + tiebreak → | count |
|---|---|---|
| (0, 2) | 0 | 491 |
| (0, 2) | 1 | 282 |
| (0, 2) | 2 | 243 |
| (0, 3) | 0 | 52 |
| (0, 3) | 1 | 20 |
| (0, 3) | 2 | 22 |
| (0, 3) | 3 | 7 |
| (1, 3) | 1 | 58 |
| (1, 3) | 2 | 139 |
| (1, 3) | 3 | 9 |

On the (0,2) conflicts the tiebreak sided with "not useful" 491 times vs 243 for
"useful" — i.e. where the two disagree, the stricter reading wins about twice as
often.

**The consensus qrel is therefore not a denoised Stage-A qrel — it is a
differently and more strictly calibrated one.** Grade 3 falls from 3,761 pairs to
337. This was flagged to the operator before the spend, because it changes what
the re-score means: the two matrices are two instruments, not two precisions.

## 5. Result — the grid is flat under *both* label sets

Full matrices: `scores.csv` (single-judge) and `scores-consensus.csv`; the
per-cell comparison is in the asset `.out`. Headlines on `ndcg10_exp`:

| | winner | winner score | baseline `k1_0.9__b_0.4` | Δ | baseline rank | spread |
|---|---|---|---|---|---|---|
| single-judge | `k1_0.9__b_0.2` | 0.6014 | 0.6007 | **+0.0007** | 4 / 26 | 0.0218 |
| consensus | `k1_0.9__b_0.2` | 0.5602 | 0.5587 | **+0.0015** | 3 / 26 | 0.0256 |

- **Same winner**, and **Spearman ρ = 0.961** across the 26 cells. A completely
  different, stricter label set reproduces the ordering.
- The winner's margin doubles (+0.0007 → +0.0015) and stays negligible.
  Per-query paired against the baseline (n=238): single-judge mean +0.00069
  (sd 0.0337, **98 win / 103 loss** / 37 tie) — the "winner" loses on more
  queries than it wins. Consensus mean +0.00150 (sd 0.0326, 92/91/55). The
  per-query sd is ~20× the mean difference under both.
- Absolute scores drop ~0.042 across the board, which is just the stricter scale
  (fewer 3s → smaller gains); it says nothing about any config. Part of the gap
  is also an accounting asymmetry: the single-judge matrix scores against the
  whole `facet-name-v1` snapshot (13,038 pairs), which includes 197 WP6
  calibration pairs across 108 topics (74 of them grade 3) that no config
  retrieved, so they inflate the ideal-DCG denominator only. The consensus
  matrix is pool-scoped (12,846). Both denominators are constant across configs
  within a matrix, so neither ranking is affected — but it is one more reason
  the two matrices' absolute numbers are not comparable, on top of the
  deflation caveat that already forbids it.
- `judged@10 = 1.000` in every cell of the **consensus** matrix, and ≥ 0.99958
  in the single-judge one (5 of 26 cells sit at 0.99958 — one chunk among
  `facet-name-v1`'s 5 parse failures reached a top-10). So no part of either
  spread is a coverage artifact, and the ensemble incidentally *repaired*
  coverage: the union of two prompts covers all 12,846 pooled pairs even though
  neither prompt alone does (`facet-name-v1` 12,841, `facet-rare3-v1` 12,845).
  That is what the 6 `single`-status pairs are — a parse failure in one prompt is
  covered by the other rather than deflating `judged@10`.
- The one real signal, unchanged: high `k1` (1.6) and high `b` (0.8) are
  consistently worst; `b` ∈ [0.2, 0.4] with `k1` ≤ 1.2 clusters at the top.
  Expected for short, uniform-length chunks, where length normalization has
  little to bite on. It is a gradient, not a peak.

**Conclusion: BM25 parameters do not matter much on this index+query set, and
that finding now survives a change of judge.** The flatness is the grid's, not
the judge's. The pyserini default is within noise of the best cell, and the
honest Stage-B question is no longer "which cell wins" but "can any cell be
distinguished from the default at all" — which is exactly what WP8's paired test
on the 825 held-out queries is for.

Note the top-3 differ slightly, which matters for Stage B's pre-registered 3
candidates:

- single-judge: `k1_0.9__b_0.2`, `k1_1.2__b_0.35`, `k1_0.9__b_0.35`
- consensus: `k1_0.9__b_0.2`, `k1_0.9__b_0.35`, `k1_0.9__b_0.4`

The consensus top-3 includes the baseline itself at rank 3 — under the stricter
labels, two of the three "best" cells are the baseline and its immediate
neighbour. `k1_1.2__b_0.35` is the only cell that moves materially (rank 2 → 8),
which is itself evidence that ranks 2-8 are one indistinguishable blob.

## 6. Code: `consensus` (PLAN §6.2b) and three defects fixed

New `consensus` subcommand + `bm25tune/consensus.py`, a pure stdlib combiner
(all the cascade arithmetic, testable with no Bedrock and no index). It
**spends nothing itself**: the discover pass folds cached grades, writes the
settled labels, emits the escalation set as a *normal run dir*, and **halts by
design** (PLAN §5.7) printing the metered `judge-pool` command. Finalize folds
the tiebreak in.

Artifacts in the run dir: `qrels-consensus.txt` (4-column TREC — published in
that form on purpose, since it spans prompt versions and so must not go through
the `.jsonl` loader's single-prompt identity check) and
`consensus-pairs.jsonl` (per-pair audit trail: every vote + status, so no
consensus label is unfalsifiable).

Three defects the real run exposed, each now with a regression test:

1. **`consensus` crashed on 14 unpoolable conflicts** (`264489f`). A prompt's
   qrels snapshot is *experiment-wide*, so it also carries WP6's 280-pair
   calibration sample — pairs drawn from the labeled input, not from any sweep
   pool. They have no passage in this run's `pool-texts.jsonl`, so a conflict
   among them can never be escalated, and no config in the run retrieved them.
   `_restrict_to_pool` now scopes all three grade maps to the run's pool keys and
   logs the count dropped. The `_write_tiebreak_pool` guard stays as a hard
   invariant (now unreachable from the CLI) so removing the filter fails loudly.
2. **The consensus re-score silently overwrote the single-judge matrix**
   (`e42c676`). The output basenames are fixed, and one run dir is legitimately
   scored against two label sets — having both matrices is the *only* evidence
   the consensus preserved the ranking, i.e. §5's entire result. New
   `score --label consensus` suffixes the three outputs and nests the manifest
   record under `score_consensus`. Both matrices were regenerated afterwards
   (re-scoring is free, so nothing was lost); the single-judge pass reproduced
   0.6014 exactly.
3. **`score --qrels` mislabelled the consensus matrix as `prompt version:
   facet-v1`** (`e42c676`) — `--prompt-version` keeps its default when `--qrels`
   overrides the path, so the header named *one of the three votes* as if it were
   the whole label set, which reads as a single-judge result. It also meant
   passing that default into `load_qrels`, applying the single-prompt identity
   check to a file that spans versions by design. `_qrels_label` returns `None`
   under an override; the header then names the qrels file and defers to the
   manifest. Same fix in `stats`, which shares the override.

Suite: **1481 passed, skip-free** (`bash scripts/test.sh`, `JAVA_HOME` exported).

## 7. Reproduce

```bash
export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"
export BM25_TUNE_BUDGET_USD=50.0
R=data/bm25-tune/runs/20260731T103000-stageA

# 1. second full-pool judge (spends ~$1.86; pilot first, per PLAN §5.7)
uv run --project tasks/bm25_tune python -m bm25tune judge-pool \
  --run-id 20260731T103000-stageA --prompt-version facet-rare3-v1 --stage consensus-secondary

# 2. discover conflicts — writes qrels-consensus.txt + the escalation dir, then STOPS
uv run --project tasks/bm25_tune python -m bm25tune consensus \
  --run-id 20260731T103000-stageA --primary facet-name-v1 --secondary facet-rare3-v1

# 3. tiebreak the 1320 conflicts (spends $0.167)
uv run --project tasks/bm25_tune python -m bm25tune judge-pool \
  --run-id 20260731T103000-stageA-consensus-tiebreak \
  --prompt-version facet-v1 --stage consensus-tiebreak

# 4. finalize (free) and score both label sets side by side (free)
uv run --project tasks/bm25_tune python -m bm25tune consensus \
  --run-id 20260731T103000-stageA \
  --primary facet-name-v1 --secondary facet-rare3-v1 --tiebreak facet-v1
uv run --project tasks/bm25_tune python -m bm25tune score \
  --run-id 20260731T103000-stageA --prompt-version facet-name-v1
uv run --project tasks/bm25_tune python -m bm25tune score \
  --run-id 20260731T103000-stageA --qrels $R/qrels-consensus.txt --label consensus

python3 worklogs/assets/2026-07-31-consensus-analysis.py $R
```

Ledger at close — `by_stage`: `A` $1.8438 (12,771 calls), `consensus-secondary`
$1.8434 (12,769), `consensus-tiebreak` $0.1671 (1,321), `calib` $0.1928 (1,400),
`calib-probe` $0.0153 (100). Total **$4.0624 / $50.00**, 28,361 billed calls.

## 8. Next

**WP8 / Stage B.** Sweep the top-3 + baseline over all 1,063 queries and run the
paired t-test on the **825 held-out** queries (set difference against the
persisted 238-query subsample, never recomputed from a seed), Bonferroni
α = 0.0167. Open question for the operator: which top-3 to carry forward, since
the two label sets disagree on ranks 2-3. The union is only four cells
(`k1_0.9__b_0.2`, `k1_0.9__b_0.35`, `k1_1.2__b_0.35`, `k1_0.9__b_0.4`) and the
baseline is one of them, so testing the consensus top-3 costs nothing extra —
but "3 candidates" is pre-registered and changing the count changes the
correction, so it needs an explicit decision, recorded.

Given §5, the realistic expectation is that **no candidate separates from the
baseline** on the held-out set. That is a publishable finding for this index and
should be reported as one rather than mined for a winner.
