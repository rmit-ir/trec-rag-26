---
name: bm25-parameter-tuning
description: Use when tuning BM25 k1/b on any Anserini/Lucene index with any query set — running the pooled LLM-judge sweep in tasks/bm25_tune/ against a corpus other than ClimbMix, or reproducing the ClimbMix run. Covers the env-var profile for a new index, building a query set from a plain JSONL/TSV/CSV/one-per-line file, the mandatory judge-calibration gate (including the --from-pool path for corpora with no labeled log), the metered judge, scoring, consensus qrels, significance testing, the exit-code contract, and the spend rules.
metadata:
  version: v0.1.0
---

# Tuning BM25 `k1`/`b` on any index

The harness is `tasks/bm25_tune/` (package `bm25tune`, 14 subcommands). It was
built for ClimbMix but is corpus-agnostic: everything ClimbMix-specific is an
environment variable with a ClimbMix default, so **leaving the environment alone
reproduces the published run, and overriding seven variables runs the same method
on your index**.

What it does: sweep a `k1`×`b` grid at depth 30, union each topic's hits across
every grid cell into one pool, judge that pool **once** with an LLM judge (0–3),
then score every cell against the shared qrels and significance-test the winners
on held-out queries.

Read `tasks/bm25_tune/PLAN.md` for the design and the measured numbers behind
every figure quoted here. This skill is the operating procedure.

## Non-negotiables

1. **`BM25_TUNE_BUDGET_USD` has no default anywhere in the code.** Export it in
   the shell that launches a spending command. A `[BUDGET]` trip is *prima facie*
   a bug (runaway prompt length, cache-miss storm, retry loop) — diagnose it,
   never raise the cap on your own initiative.
2. **Calibration is a gate, not a report.** `calibrate` exits 6 when no prompt
   variant produces a usable grade spread, and a gated judge must not judge a
   pool. A mode-dominated judge ties neighbouring grid cells, which is
   indistinguishable from "`k1`/`b` doesn't matter on this corpus".
3. **One data dir per corpus.** The judgment cache key is
   `prompt_version::topic_id::chunk_id` — **no corpus component**. Two corpora
   sharing `BM25_TUNE_DATA_DIR` will serve each other's grades wherever a topic id
   collides, producing a complete and plausible wrong answer.
4. **Pilot before scale.** `judge-pool --pilot 200` prints a *measured* cost
   basis. Run it before the full pool, every time, on a new corpus or prompt.
5. **Data artifacts live under `data/`**, never under `tasks/`.
6. Temperature stays at 0.0. It is not in the cache key, so a `temp>0` grade
   written into the real `judgments/log/` silently corrupts the qrels — any
   temperature experiment goes in a throwaway `BM25_TUNE_DATA_DIR`.

## Setup

JDK 21 and the task env, for every command:

```bash
export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"
uv run --project tasks/bm25_tune python -m bm25tune <subcommand>
```

### 1. Probe the index

Two facts must be established before spending anything, and both fail silently:
the document count (the identity guard), and whether document text is retrievable
at all. `judge-pool` sends the **passage**, not the docid — an index with no
stored text yields empty passages that every judge grades 0 uniformly, producing
a complete-looking score matrix in which no config beats any other.

```bash
uv run --project tasks/bm25_tune python \
    skills/bm25-parameter-tuning/scripts/probe_index.py /path/to/index \
    --query "a phrase you know is in the corpus" --query "another one"
```

Exit 0 = usable (and it prints the two exports to copy); 1 = unopenable; 2 =
opens but stores no text — **stop and rebuild the index**; 3 = no query matched,
so nothing was proven either way, retry with terms you know are present.

Which accessor works is build-dependent and the two common cases are exact
opposites: a custom generator populates `contents()` with `raw()` empty; a stock
`pyserini.index.lucene --storeRaw` index is the reverse. The probe reuses the
harness' own accessor rather than reimplementing it, so it cannot pass while the
real run gets nothing.

### 2. Generate the env profile

```bash
uv run --project tasks/bm25_tune python \
    skills/bm25-parameter-tuning/scripts/make_profile.py \
    --name mycorpus --index /path/to/index \
    --grid-k1 "0.5,0.7,0.9,1.2,1.6" --grid-b "0.2,0.35,0.5,0.65,0.8" \
    --baseline 0.9:0.4 --out /tmp/mycorpus.env
source /tmp/mycorpus.env
```

`num_docs` is read off the live index rather than typed — the reason this is a
script and not a documented template. `BM25_TUNE_BUDGET_USD` is written as a
**commented-out** line on purpose (rule 1).

The seven variables that make the harness corpus-agnostic:

| var | default (= the ClimbMix run) | why you'd change it |
|---|---|---|
| `BM25_TUNE_INDEX_DIR` | *(required)* | your index |
| `BM25_TUNE_DATA_DIR` | `data/bm25-tune` | **always** set per corpus — rule 3 |
| `BM25_TUNE_EXPECTED_NUM_DOCS` | `921892634` | your `num_docs`; `none` disables the guard (correct only during the first probe) |
| `BM25_TUNE_GRID_K1` | `0.5,0.7,0.9,1.2,1.6` | comma- or space-separated |
| `BM25_TUNE_GRID_B` | `0.2,0.35,0.5,0.65,0.8` | " |
| `BM25_TUNE_BASELINE` | `0.9:0.4` | the cell candidates are compared to — pyserini's default is `0.9:0.4`, Lucene's is `1.2:0.75` |
| `BM25_TUNE_QUERIES_FULL` / `_SUBSAMPLE` | `keyword-1063.jsonl` / `subsample-250.jsonl` | a name carrying your corpus, since `keyword-1063` would be a lie in every log line |

`BM25_TUNE_INPUT_FILE` points at the ClimbMix labeled search log. On any other
corpus you never set it: `make-queries` replaces it, and `verify-inputs` (which
checks that one file against a frozen fingerprint) has nothing to do and says so.

Confirm what the harness thinks it is doing — every command logs a `[LOAD]` line
naming the grid, baseline, guard, query files, and which variables you overrode.

### 3. Build the query set

Bring any query file. `make-queries` accepts JSONL (`topic_id`/`qid`,
`query`, `narrative`/`description`), TSV/CSV (positional or headed), or one query
per line, sniffing the content rather than trusting the extension:

```bash
uv run --project tasks/bm25_tune python -m bm25tune make-queries \
    /path/to/queries.tsv --per-topic 2 --seed 13
```

It writes both artifacts — the full set and the Stage-A subsample — and prints
each one's sha256.

**`topic_id` is the most consequential field in the file.** Judgments are cached
per topic, the judge target is the topic's *narrative*, and the ideal DCG is
computed per topic. So:

- Queries sharing a `topic_id` share judgments — that is the reuse economy that
  makes pooled judging affordable (**[measured]** 1.44× pool inflation at 6
  configs vs. 30 hits for one).
- A **narrative** is what the judge grades against. With no narrative column the
  query string is used and `make-queries` warns; grading a keyword string is a
  weaker signal than grading an information need, and it is the single biggest
  quality lever you control.
- No `topic_id` column means every query becomes its own topic (`q-1`, `q-2`, …
  via `--topic-prefix`). Correct, but it forgoes all cross-query judgment reuse,
  so the judge bill scales with queries rather than topics.

## The pipeline

### 4. Sweep (search only — spends nothing)

```bash
uv run --project tasks/bm25_tune python -m bm25tune search-sweep \
    --stage A --run-id mycorpus-a 2>&1 | tee /tmp/sweep-a.log
```

Writes one TREC run file per cell under `runs/<run-id>/trecruns/`, plus
`pool.jsonl` (the per-topic union) and `pool-texts.jsonl` (the passages the judge
will read). Resume = re-run the identical command; cells whose run file exists are
skipped. Watch the `[POOL] inflation_vs_single=` line — near 1.0 means the grid
isn't moving rankings at all, so there is nothing for the sweep to find and no
reason to spend on judging.

Do **not** pass `--no-fetch-texts` unless you are only checking plumbing: it
leaves the pool with no passages, so `judge-pool` has nothing to send.

### 5. Calibrate — the mandatory gate

Judges every registered prompt variant over one persisted sample, applies four
grade-distribution conditions, and picks the variant with the **lowest modal
share** among those that pass. ~1450 calls, ≈$0.23 typical at the committed
`gpt-oss-20b` rates.

```bash
export BM25_TUNE_BUDGET_USD=50.0
uv run --project tasks/bm25_tune python -m bm25tune calibrate \
    --from-pool mycorpus-a 2>&1 | tee /tmp/calibrate.log
```

`--from-pool` is **the any-corpus path**: it draws the sample from the sweep's
`pool.jsonl` + `pool-texts.jsonl` instead of the ClimbMix labeled log. Without it
the gate would be unrunnable on your corpus, leaving only two bad options — skip
the gate and spend on an unvalidated judge, or fabricate a log.

What `--from-pool` costs you: a pooled sample carries no agent labels, so the
secondary agent-agreement smell test (AUC) is **undefined**. The report says so
explicitly rather than showing bare dashes, and `report.json` carries `auc: null`
— never `0.5`. The gate then rests on its four distribution conditions, which
were always the ones deciding whether a judge can separate grid cells.

Exit 0 → `report.md` names a recommended variant. **Exit 6 → no variant passed;
stop.** The report still gets written, with a `best_effort` variant and the
distance from the failing bound, so an escalation carries a diagnosis. A gated
judge means one of: the grid isn't separating documents on this corpus, the
narratives are too thin to grade against, or the passages are truncated/empty.

Then **read `calibration/report.md` and decide** which variant to judge under.
The gate is a floor on usability, not the selection criterion.

### 6. Judge the pool — the metered job

```bash
uv run --project tasks/bm25_tune python -m bm25tune judge-pool \
    --run-id mycorpus-a --prompt-version <the confirmed variant> \
    --pilot 200 2>&1 | tee /tmp/judge-pilot.log
```

The pilot judges 200 pairs spread evenly across topics and prints a **measured**
cost basis for the full pool — the only honest input to a go/no-go on the full
spend. Then drop `--pilot` and run the same command; the pilot's judgments are
cached, so nothing is paid for twice.

Fully resumable and interruption-safe. Exit codes: `3` = credentials expired
(refresh and re-issue the identical command), `5` = budget stop (a stop, not a
loss — spend equals exactly what reached disk), `4` = the pre-flight refused
before spending anything, `130`/`143` = signalled, with the in-flight judgments
drained to disk first.

`--prompt-version` is a cache-key component: a different version re-judges and
re-bills the whole pool. That is deliberate — grades from two rubrics must never
mix in one qrel.

### 7. Score

```bash
uv run --project tasks/bm25_tune python -m bm25tune score \
    --run-id mycorpus-a --prompt-version <variant>
```

Reads the cache only, spends nothing. Writes `scores.csv`/`.md` plus per-query
scores. nDCG@10 is the pre-registered metric; graded and binary P@10, recall@10,
and MAP@30 come along in the same pass.

**Absolute nDCG values are deflated** because the ideal DCG is computed per topic
over the whole pool while a run answers one query — only *differences between
cells* are meaningful. The caveat is printed and written into the report header.
Check `judged@10`: a low value means the pool is under-judged and every cell's
score is understated.

### 8. Optional — consensus qrels

A second full-pool prompt whose disagreements with the first drive a tiebreak
pass, folding two label sets into one:

```bash
# discover: how many pairs disagree, and what the escalation would cost
uv run --project tasks/bm25_tune python -m bm25tune consensus \
    --run-id mycorpus-a --primary <v1> --secondary <v2>
# ... judge the escalation pool it names, then re-run with --tiebreak <v3>
```

Worth it when a cell ordering is close enough that one judge's idiosyncrasy could
decide the winner. On ClimbMix the consensus labels reproduced the flat Stage-A
grid — a null result worth having.

### 9. Significance test on held-out queries

```bash
uv run --project tasks/bm25_tune python -m bm25tune stats \
    --run-id mycorpus-b --baseline "$BM25_TUNE_BASELINE" \
    --candidates <cell> <cell> <cell>
```

Paired t / Wilcoxon / bootstrap CIs, Bonferroni-corrected. The held-out set is
the full query file **minus the persisted Stage-A subsample** — read from disk,
never recomputed from the seed, so a re-extraction cannot silently move the split.

The candidate count is pre-registered at 3 and drives the Bonferroni divisor;
`stats` warns when you pass a different number, because that is no longer the
pre-registered analysis and the report must say so.

## Costs

At the committed `gpt-oss-20b` ap-southeast-2 rates, a typical call (900 in / 300
out) is **$0.000158** — $0.158 per 1000 judgments. The ClimbMix plan's full
volume (≈49k calls: calibration + both stages + a continuity pass) is **$7.80
typical, $13.61 worst case**.

Your bill scales with the **pool**, not the query count: topics × queries-per-topic
× unique-chunks-per-query, deduped within topic. Get the real number from
`--pilot`, not from this paragraph.

`budget` prints spent/cap/remaining and makes no API call. `cost-report` writes
the roll-up plus a ledger-vs-log reconciliation line.

## Exit codes

`0` OK · `1` error · `2` not implemented · `3` credentials expired · `4` budget
pre-flight refusal · `5` budget stop mid-run · `6` **calibration gate failed** ·
`130`/`143` signalled (drained).

## Tests

```bash
export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"
bash scripts/test.sh bm25-tune     # or the whole suite before committing
```

Hermetic and skip-free: no network, no credentials, no JVM for anything but the
searcher tests. `bm25tune` imports nothing heavy at module level (pyserini opens
inside `ChunkSearcher._open()`, boto3 inside `BedrockJudge._client()`) and a
subprocess probe test enforces that — so the suite needs no dep group.

## Gotchas

- **`--fresh` never touches `judgments/log/` or `costs/`.** It refuses, naming
  `rebuild-cache` as the tool you actually wanted. The log is the source of truth
  for both the qrels and the money; the cache is always rebuildable from it.
- **A judgment cache key has no corpus and no temperature component.** Hence rule
  3 and rule 6.
- **`verify-inputs` is ClimbMix-only** by design — it checks one committed file
  against a frozen sha256 plus a dozen counts. On another corpus it exits 1 with
  an explanation, not a dozen spurious failures.
- **Don't reuse the repo-root env.** `uv run --project tasks/bm25_tune`, always.
- **Long commands go to a tracked background task with `tee`** (CLAUDE.md): the
  sweep is ~10 min and each judge job hours.
