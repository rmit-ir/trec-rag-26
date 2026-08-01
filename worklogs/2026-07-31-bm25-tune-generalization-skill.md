# Generalizing the BM25 tuning harness, and packaging it as a skill

**2026-07-31.** Branch `feat/bm25-tune`. Follows
`worklogs/2026-07-31-bm25-consensus-qrels.md`.

Goal (user's words): *"make it a skill that can be generalized enough with the
written scripts to run BM25 parameters tuning easily on any given anserini index
with any queries."*

Deliverable: `skills/bm25-parameter-tuning/` (SKILL.md + two scripts) plus the
harness changes that make the claim in that SKILL.md true. **Zero Bedrock spend
this session** — every verification below is either offline or search-only.

---

## What was ClimbMix-specific, and what each fix cost

Auditing `bm25tune` for corpus assumptions turned up seven hardcoded values and
one structural blocker.

### The seven values → env vars with the ClimbMix values as defaults

| var | default | what was hardcoded before |
|---|---|---|
| `BM25_TUNE_GRID_K1` | `0.5,0.7,0.9,1.2,1.6` | `searcher.GRID_K1` tuple |
| `BM25_TUNE_GRID_B` | `0.2,0.35,0.5,0.65,0.8` | `searcher.GRID_B` tuple |
| `BM25_TUNE_BASELINE` | `0.9:0.4` | `searcher.BASELINE_CONFIG` |
| `BM25_TUNE_EXPECTED_NUM_DOCS` | `921892634` (`none`/`off`/`0`/`any`/`disabled` disables) | `searcher.EXPECTED_NUM_DOCS` |
| `BM25_TUNE_QUERIES_FULL` | `keyword-1063.jsonl` | `cli.QUERIES_FULL_BASENAME` |
| `BM25_TUNE_QUERIES_SUBSAMPLE` | `subsample-250.jsonl` | `cli.QUERIES_SUBSAMPLE_BASENAME` |
| `BM25_TUNE_INPUT_FILE` | the labeled log basename | `config.INPUT_BASENAME` |

Defaults are the ClimbMix values, so **an unset environment reproduces the
published run byte for byte** — the generalization is not a behaviour change.
The module constants now *derive* from the `config.DEFAULT_*` strings via the
public `parse_grid_axis`/`parse_cell` parsers, and import-time asserts pin the
dataclass literals to those strings so the two cannot drift apart silently.

`config.describe()` grew `grid_k1=/grid_b=/baseline=/expected_num_docs=/queries=`
and an `overridden=` list, so the `[LOAD]` line every command prints is a full
statement of what the run thinks it is doing. `expected_num_docs` prints literally
`any` when the guard is off, rather than a number that would read as "guarded".

`input_file` became `input_file_override: Path | None` + `require_input_file()`:
the labeled search log is an *input adapter for one corpus*, not a requirement of
the method, so commands that genuinely need it now say so and the rest work
without it.

### Bring-your-own-queries: `make-queries`

New subcommand. Reads JSONL (`topic_id`/`qid`/`query_id`, `query`,
`narrative`/`description`), TSV/CSV (positional or headed), or one query per
line, **sniffing content rather than trusting the extension** (a `.txt` holding
JSONL parses as JSONL), and writes both the full set and the Stage-A subsample
with their sha256s. Nine tests in `tests/bm25_tune/test_extract.py` cover the
formats, dedupe, refusals, and `--topic-prefix`.

Two behaviours worth stating because they are the quality levers an operator
controls:

- **No narrative column** → the query string is used and a warning fires. Grading
  a keyword string is a weaker target than grading an information need.
- **No `topic_id` column** → each query becomes its own topic. Correct, but it
  forgoes all cross-query judgment reuse, so the bill scales with queries rather
  than topics.

### The structural blocker: `calibrate` could not run on any corpus but ClimbMix

The significant find. PLAN §3.3 makes judge calibration a **mandatory gate before
any sweep spend**, but `_calibration_pairs` sampled exclusively from
aus_agent's labeled search log. On a new index that left two bad options: skip the
gate and spend on an unvalidated judge, or fabricate a log.

Fix: `extract.pool_calibration_sample(entries, texts, queries, n, seed)` draws the
sample from a sweep's `pool.jsonl` + `pool-texts.jsonl` — the same two artifacts
`judge-pool` reads, which every sweep already produces — exposed as
`calibrate --from-pool RUN_ID`. It duck-types `PoolEntry` via `getattr` because
`pool.py` imports `extract` (a real import cycle, not a style preference), and
round-robins one hit per topic per round from a per-topic seeded shuffle so
per-topic counts stay uniform to within one, matching `calibration_sample`'s shape.

**What the path loses, and how that is reported.** A pooled sample carries no
agent labels, so every hit's `agent_class` is honestly `"unjudged"` and the
secondary agent-agreement smell test (AUC) is *undefined*. `roc_auc` already
returned `None` rather than `0.5` for an empty class — the right call — but the
rendered table then showed bare dashes, which reads as "this judge failed the
smell test" when the truth is "this corpus has no smell test". Opposite
conclusions from an identical table. So `render_report_md` now prefaces the table
with an explicit *"Not computable for this sample: no agent labels… This is an
absent measurement, not a failed one"* whenever no variant has an AUC.

Deliberately a **flag, not a fallback**: an operator who mistyped
`BM25_TUNE_INPUT_FILE` on ClimbMix would otherwise silently lose the agreement
column and never know to look for it.

Also verified: the sampler is retrieval-biased (top-30 BM25 hits), so a
share-at-≥2 read from it is an upper bound. That is in the function docstring and
the report caveat, because it moves the interpretation of gate condition 3.

---

## The skill

`skills/bm25-parameter-tuning/SKILL.md` — the operating procedure: probe → profile
→ `make-queries` → `search-sweep` → `calibrate --from-pool` (gate) →
`judge-pool --pilot` then full → `score` → optional `consensus` → `stats`, with
the six non-negotiables (budget has no default; the gate is a gate; one data dir
per corpus; pilot before scale; artifacts under `data/`; temperature stays 0.0),
the seven-variable table, the exit-code contract, and the cost arithmetic.

Two scripts, both of which exist because the failure they prevent is silent:

**`scripts/probe_index.py`** — opens any index, prints `num_docs`, issues each
`--query`, and shows a snippet or `*** NO STORED TEXT ***` per hit. It imports the
harness' own `_document_text` rather than reimplementing accessor logic: *a probe
that answers "is text retrievable" with different logic than the code that fetches
it can pass while the real run gets nothing.* Exit 0 usable / 1 unopenable / 2
**no stored text** / 3 no hits.

The no-text case is the one that matters. `judge-pool` sends the passage, not the
docid, so an index with no stored text yields empty passages that every judge
grades 0 uniformly — a complete-looking score matrix in which no config beats any
other. Which accessor works is build-dependent and the two common cases are exact
opposites: `climbmix-bm25-chunked` has `contents()` populated with `raw()` None; a
stock `--storeRaw` index is the reverse; a `DefaultLuceneDocumentGenerator` index
with no `--storeRaw` has neither.

**`scripts/make_profile.py`** — writes a sourceable env profile, reading `num_docs`
**off the live index rather than accepting it as an argument**. That is the whole
reason it is a script and not a documented template. `BM25_TUNE_BUDGET_USD` is
written as a **commented-out** line: the ceiling must be a live decision by
whoever launches a spending command, not a value inherited from a file they
generated last week and no longer read.

### Registered in two places, because one of them would have failed CI

`AGENTS.md` (= `CLAUDE.md`, a symlink) gained the corpus-agnostic paragraph and a
pointer to the skill, and `scripts/check_vendored_skills.py` gained
`bm25-parameter-tuning` in `LOCAL_ONLY`. The second is not cosmetic: that script
iterates *every* directory under `skills/`, and anything upstream does not publish
prints "not published upstream — treat as local-only and add it to `LOCAL_ONLY`".
So the weekly `vendored-skills.yml` run would have started nagging about our own
skill. `LOCAL_ONLY` is the difference between "ours" and "drifted".

---

## Verification (all offline or search-only; $0.00 spent)

Everything below is reproducible from
`worklogs/assets/2026-07-31-bm25-generic-rehearsal.sh` — the whole rehearsal as one
script, re-run from scratch to confirm the figures in this worklog are the ones it
actually produces. It builds its own corpus and indexes, so it needs nothing but
the task env and JDK 21.

### Two throwaway indexes, built to exercise both probe verdicts

- `/tmp/bm25-generic-check/idx` — 400 synthetic docs, `--storeRaw`. Two topics with
  disjoint vocabularies (soil-moisture / library-funding) plus filler docs, 60
  words each, `random.seed(11)`.
- `/tmp/bm25-notext/idx` — same corpus via `DefaultLuceneDocumentGenerator` with
  **no** `--storeRaw`, i.e. no retrievable text at all.

Probe exit codes, all four paths: `notext=2, ok=0, nohits=3, missing=1`.

Building the second index is what caught a bug **in the probe itself**: the first
version conflated "no hits" with "no text", so it reported the *healthy* index as
broken whenever the default probe term (`"information"`) happened to be absent —
the normal case on a small or domain-specific corpus. Hence `EXIT_NO_HITS=3` and a
distinct INCONCLUSIVE message.

### Full-pipeline rehearsal on the foreign index

Plain TSV in, scores and stats out, in a throwaway data dir (`/tmp/rehearse-data`),
grid cut to 2×2 for speed. Exact inputs:

`/tmp/rehearse-queries.tsv` (tab-separated, headed):

```
topic_id	query	narrative
t-1	soil moisture irrigation	How do growers use soil moisture sensors to schedule irrigation?
t-1	tensiometer scheduling	How do growers use soil moisture sensors to schedule irrigation?
t-2	library funding levy	How is public library funding allocated across branches?
t-2	municipal budget branches	How is public library funding allocated across branches?
```

| step | command | result |
|---|---|---|
| probe | `probe_index.py /tmp/bm25-generic-check/idx --query "soil moisture irrigation" --query "library funding levy"` | exit 0, `num_docs=400`, both queries 3 hits with text |
| profile | `make_profile.py --name rehearse --index … --data-dir /tmp/rehearse-data --grid-k1 "0.9,1.2" --grid-b "0.4,0.75"` | wrote `/tmp/rehearse.env`, `num_docs=400` |
| queries | `make-queries /tmp/rehearse-queries.tsv --per-topic 1` | 4 queries / 2 topics; full sha256 `693d5ee62922c960dcb79f4961666468baf4de17f9e848ee070ecffe035b27c9`, subsample `27aeb56d24c21897188182cde9e94a922d96823d4fb37cafcab520539562ee49` |
| sweep | `search-sweep --stage A --run-id rehearse-a` | 4 cells × 2 queries, 30 hits/query, pool = **60 pairs over 2 topics**, `inflation_vs_single=1.00x`, 60/60 texts fetched |
| gate (sampler only) | `cli._pool_calibration_hits(cfg, ns(from_pool="rehearse-a", n=8, seed=7))` | 8 drawn, both topics, `classes={'unjudged'}`, narrative correctly off the query file |
| budget refusal | `calibrate --from-pool rehearse-a` with `BM25_TUNE_BUDGET_USD` unset | **exit 1** before any call, message naming the $50 figure |
| score | `score --run-id rehearse-a --qrels /tmp/rehearse-qrels.txt --prompt-version facet-v1 --label synthetic` | qrels read as `60 judged pairs, grades {3: 60}`; all 4 cells `ndcg10_exp=1.0000`, `judged@10=1.000`, `recall10_bin2=0.3333` |
| stats | `stats --run-id rehearse-a --candidates k1_1.2__b_0.75 --metrics ndcg10_exp --bootstrap 200` | held-out = 2 of 4; `delta=+0.0000 CI=[+0.0000,+0.0000] p=1 p_bonf=1 wilcoxon_p=1 ns`; warned that 1 candidate ≠ the pre-registered 3 |

The gate's judging half was **not** run against Bedrock (rule: no spend beyond
WP3's validation call until the user confirms the prompt version), so it was
exercised offline instead — see the test section.

Two of these numbers are degenerate, and the degeneracy is the honest reading, not
a defect in the rehearsal:

- **`inflation_vs_single=1.00x`** — the four cells retrieve *identical* sets. On a
  400-doc synthetic corpus a 2×2 grid does not reorder anything, so there is
  nothing here for a sweep to find. This is exactly the signal the skill tells
  operators to check before spending on judging, and seeing the harness report it
  correctly on a corpus where it is true is worth more than a contrived non-null.
- **`grades {3: 60}`** — the synthetic qrels grade by vocabulary overlap
  (`min(|passage_words ∩ topic_vocab|, 3)`), and with 60 words drawn from an
  8-word topic vocabulary every pooled passage overlaps on ≥3 terms. So every
  pooled document is maximally relevant, which is why every cell ties at 1.0.

The purpose of steps 7–8 is to exercise the `score`/`stats` plumbing end to end
with **no Bedrock spend** — qrels parsing, per-query output, the held-out split
read from disk, the Bonferroni divisor, the candidate-count warning — and it does
that regardless of the label distribution. What it deliberately does *not* do is
demonstrate that the harness can detect a real `k1`/`b` effect; only the ClimbMix
run's judged pool speaks to that.

`verify-inputs` on the foreign corpus printed only "input not found" — technically
correct and practically useless, since the likeliest reader is an operator for whom
that file does not exist and never will. Added a third line naming `make-queries`
and `search-sweep` as the actual next steps. (The `input_file_override` branch
already had its own version of this message; this is the no-override path.)

### Offline tests: 1512 passed, 7 deselected, skip-free

New this session:

- `test_extract.py` +14: nine `load_plain_queries` format/refusal cases, five
  `pool_calibration_sample` cases (gate runnable without a log; every pair
  `unjudged`; a pure function of the seed regardless of pool row order; textless
  chunks skipped but an entirely textless pool fatal; topics absent from the query
  file dropped). 40 defined, 44 collected (parametrized).
- `test_cli_calibrate.py` +3: `--from-pool` runs the whole gate **with the labeled
  log deleted** (not merely ignored — if any path still reached for it the test
  fails); `auc: null` with the "absent measurement, not a failed one" note in the
  report; both missing-artifact cases refusing with the command that fixes them
  (`search-sweep`, `--no-fetch-texts`) at exit 1 rather than 6.
- `test_cli_wp1.py` +9: the env overrides (comma- and space-separated axes,
  malformed grid/baseline refused, `EXPECTED_NUM_DOCS=none` → `describe()` showing
  `expected_num_docs=any`, `INPUT_FILE` bare-name vs. path, `make-queries` writing
  both artifacts and refusing identical basenames), plus
  `test_every_subcommand_can_render_its_own_help`.

### A real CLI bug the help-rendering test caught

`judge-pool --help` crashed:

```
TypeError: %o format: an integer is required, not dict
```

`f"{MIN_POOL_TEXT_COVERAGE:.0%}"` inside an argparse `help=` string leaves a
literal `%` in the text, and **argparse `%`-expands help strings** — so `%` before
`o`f `of` was read as a format spec. Fixed to `f"{… * 100:.0f}%%"`. Grepped the
file for others: this was the only one.

Worth the note because the flag still *parsed* — every behaviour test passed while
the subcommand was undocumented and unrunnable-by-reading. Hence
`test_every_subcommand_can_render_its_own_help`, which walks
`parser._actions[…].choices` and calls `format_help()` on each.

---

## Open, carried forward

**Which top-3 candidates Stage B tests.** The two label sets disagree on ranks
2–3: single-judge has `k1_1.2__b_0.35`, consensus has the baseline
`k1_0.9__b_0.4` at rank 3. The union is 4 cells, so no extra sweep cost — but "3
candidates" is pre-registered and changing the count changes the Bonferroni
divisor. `stats` warns when the count differs, so the artifact will say so either
way. **User's call.**

WP8 (Stage B) remains. WP9's CLAUDE.md entry is done here; the task README is not.
