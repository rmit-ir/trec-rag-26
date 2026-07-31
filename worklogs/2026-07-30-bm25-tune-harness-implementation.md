# 2026-07-30 — BM25 k1/b tuning harness: implementation (WP1–WP4)

Builds the harness specified in `tasks/bm25_tune/PLAN.md` for finetuning BM25
`k1`/`b` against an LLM-judged, pooled qrel. **No tuning results here** — this
session lands and verifies the machinery. Bedrock spend to date: **$0.00005525**
(one validation call).

Commits: `d9ce39c` (plan), `1dab631` (WP1), `63ca735` (WP2–WP4).

## What was built

| WP | Modules | Tests |
| --- | --- | --- |
| WP1 | `config`, `logging_setup`, `prompts`, `extract`, `cli` skeleton | 22 |
| WP2 | `searcher.py`, `pool.py` | 80 |
| WP3 | `judge.py`, `store.py` | 122 |
| WP3b | `pricing.py` | 52 |
| WP4 | `metrics.py`, `stats.py` | ~120 |

Full suite at the end of WP4: **1233 passed, 0 skipped, 5 deselected** (all
deselected are `live`-marked); **1270** after the 2026-07-31 follow-ups below. Everything is stdlib-only at import time; `pyserini` enters only
inside `ChunkSearcher._open()` and `boto3` only inside `BedrockJudge._client()`,
which is what keeps the suite hermetic with no dependency group.

## Independent verification (beyond the agents' own tests)

Each package was written by a separate agent, so the numbers below were
re-derived by hand or against a reference implementation rather than taken on
trust.

### The experiment's central premise — do `k1`/`b` actually matter?

Live against the real chunked index (`num_docs = 921,892,634`), searching three
ad-hoc keyword queries at depth 30 through `ChunkSearcher`:

| config | vs baseline (0.9, 0.4) | top-10 overlap | order changed | scores changed |
| --- | --- | --- | --- | --- |
| (0.5, 0.2) | q1 `electric vehicle battery recycling` | 0.80 | yes | yes |
| (0.5, 0.2) | q2 `medicare eligibility age requirements` | 0.90 | yes | yes |
| (0.5, 0.2) | q3 `antibiotic resistance mechanisms bacteria` | 1.00 | yes | yes |
| (1.6, 0.8) | q1 | 0.60 | yes | yes |
| (1.6, 0.8) | q2 | 0.70 | yes | yes |
| (1.6, 0.8) | q3 | 0.80 | yes | yes |

Re-running `(0.9, 0.4)` after three other configs gave **bit-identical** top-10
and top-1 scores for all three queries, so flipping `set_bm25` between batches
on one live instance is safe and the rankings are self-consistent. Cold start
was 5.5 s open+warmup with a warm page cache (the 9.4 s `[measured]` figure in
the plan stands as the cold-cold case).

### Grid

`stage_a_grid()` returns exactly 26 cells: k1 ∈ {0.5, 0.7, 0.9, 1.2, 1.6} ×
b ∈ {0.2, 0.35, 0.5, 0.65, 0.8} = 25, plus the baseline `(0.9, 0.4)` as the
26th. No duplicates; contains the Lucene default corner.

### Pooling

Synthetic 2-config × 2-query case over one topic, rankings of 35/2/2/1 hits:
pool = 33 chunks. Depth-30 cut honoured (`d30`–`d34` excluded, `d29` included),
union across both queries *and* both configs, duplicate `d0_p1` counted once.
Topic-level, matching the topic-level cache key.

### nDCG conventions

Hand-computed for topic qrel `{a:3, b:2, c:1, d:0}` with ranking `[c, a, b]`:

| gain | hand | `metrics.ndcg_at_k` | agreement |
| --- | --- | --- | --- |
| exponential `2^g−1` | 0.736363617134 | same | < 1e-12 |
| linear `g` | 0.817493513800 | same | < 1e-12 |

Perfect ranking = exactly 1.0. A lone grade-1 chunk with grades 3 and 2 above it
in the topic qrel scores 0.106465 — the topic-level ideal correctly deflates
absolute values, which is why only *relative* comparisons are meaningful. An
all-zero qrel returns `None`, not `0.0`, so an unjudged topic cannot be averaged
in as a real zero.

### Statistics

`compare()` on deltas `[0.1, −0.2, 0.3, 0.0, 0.15, −0.05, 0.2, 0.1]` returned
**t = 1.3612278195, p = 0.2156349254** — an exact match to
`scipy.stats.ttest_rel` (checked in an ephemeral env; scipy is not a task dep).
`alpha_bonferroni` is the exact `0.05/3 = 0.016666…`, **not** a rounded
`0.0167`; the distinction matters because rounding up would make p = 0.01668
read as significant. Cohen's d = 0.481267, bootstrap CI (10k resamples, seed 13)
= [−0.025000, 0.175000].

### Cost model

`pricing.py` reproduces the plan's §5.3 worked example byte-for-byte (934 in /
212 out → `usd 0.00013285`, `input_usd 6.734e-05`, `output_usd 6.551e-05`). It
raises `UnknownRate` on an unknown model/region/tier rather than guessing,
returns `None` for null usage, refuses an over-cap preflight with
`BudgetRefused`, and scales the reserve $0.000275 / $0.004400 / $0.017600 at
concurrency 1 / 16 / 64.

**Wasted spend cannot hide.** A billed parse failure followed by a successful
retry meters *both*: $0.00015759 + $0.00008086 = $0.00023845, versus $0.00008086
for the winning call alone. Every attempt in `result.history` yields its own
record with its own `cost` block.

**Parsing traps confirmed handled**: a response whose `content` is
`[reasoningContent, text]` — gpt-oss-20b's actual shape — parses correctly
(the idiomatic `content[0]["text"]` would raise `KeyError` on a *good* response,
the most expensive available mistake since it looks like a model failure). The
last `##final score:` match wins (`"...score: 0 ... score: 3"` → 3).

### Cache key

`jkey = "<prompt_version>::<topic_id>::<chunk_id>"`. Same triple → same key;
differs on prompt version and on topic; `::` inside any component and empty
components are rejected (otherwise `("a::b","c","d")` and `("a","b::c","d")`
would collide and one topic's grades would answer another's lookups).
`run_id`/`stage` are billing metadata and deliberately absent, so **a Stage-A
judgment is a Stage-B cache hit**.

## The cross-writer contract check (the risk the tests could not cover)

WP4 flagged that it built its fixtures by hand rather than by running WP2's
`search-sweep` and WP3's `judge-pool`, so a divergence between the sibling
writers and readers would be invisible to the suite. Verified directly, at zero
Bedrock cost, with a real sweep:

```bash
export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"
export BM25_TUNE_INDEX_DIR=/home/eh6/E128356/projects/trec-rag-26/data/built-indexes/climbmix-bm25-chunked
uv run --project tasks/bm25_tune python -m bm25tune search-sweep \
  --stage B --run-id contract-check --configs 0.9:0.4,1.6:0.8 --limit 8
```

Produced 2 × 240-line TREC run files and a 290-pair pool over 1 topic
(inflation 1.30× at 2 configs, consistent with the plan's `[measured]` 1.44× at
6). Then read back with the **real** readers, nothing patched:

- `cli._load_judge_pairs` → **290 `JudgePair`s**, 0 empty passages, all
  narratives non-empty, 290/290 unique jkeys (no collisions), and
  `chunk_id.rsplit("_p", 1)[0] == parent_docid` for every pair.
- Real prompt rendering via `spec.render_pair`: **2291 / 3941 / 5587** chars
  (min / median / max) → median ≈ 985 input tokens, which corroborates the
  plan's 900-token planning figure. Median cost $0.00016372/call.
- `pool.read_trec_run` → `metrics.ndcg_at_k` over both real run files with a
  seeded synthetic qrel (no Bedrock): 0.261653 vs 0.282670 — the two configs are
  distinguishable through the whole chain.

**No contract divergence found.** The throwaway run (780 KB) was deleted;
`data/bm25-tune/{judgments,costs}` still do not exist, confirming zero spend.

## Defects found and fixed

Ordered by what they would have cost if they had reached a real run.

1. **`[tool.uv] package = false` broke the plan's own canonical invocation**
   (WP1). The repo root landed on `sys.path[0]`, so
   `uv run --project tasks/bm25_tune python -m bm25tune` died with
   `No module named bm25tune`. Replaced with a hatchling build backend.
2. **A trigger raised by the writer thread during the drain was being lost**
   (WP3, found by its own budget-trip test). The budget check runs on the
   writer, so on a short run the trip can land *after* the main thread has
   entered `drain_and_checkpoint` and already chosen exit 0. A late trigger now
   overrides a zero exit code, never the reverse. This is what made exit 5
   reliable.
3. **A resumed sweep destroyed its own provenance** (WP2, found by its own live
   resume). A resume never opens the index, so it knew neither `num_docs` nor a
   warmup time, and the manifest merge wrote `index_num_docs: null` — erasing
   the only record of which corpus produced the run files. Unmeasured fields are
   now omitted and `created_utc` is write-once.
4. **`--no-fetch-texts` silently disarmed the passage-change check** (WP2):
   `texts=None` rewrote every `text_sha256` as `null`. Digests are now
   re-derived from the existing sidecar, and text fetching is incremental so a
   resume re-reads none of the ~1 TB stored-fields file.
5. **Partial `pool-texts.jsonl` only logged** (WP3). A truncated sidecar leaves
   chunks unjudged, which deflates judged@10 *uniformly across the grid* —
   invisible in exactly the comparison the experiment makes, and paid for by the
   time you'd notice. Now a hard refusal below
   `MIN_POOL_TEXT_COVERAGE = 0.99`, with `--allow-partial-texts` as an explicit
   override that still logs the gap.
6. **Reported dollar figures were lossier than recorded ones** (mine, found by
   WP3's test). `build_cost_report` / `BudgetGuard.status` / `preflight` /
   `manifest_cost_fields` / `pilot_basis` rounded money to 6 dp while `cost`
   blocks record at `COST_DP = 8` and the ledger keeps 10. One call costs
   ~$0.00016, so 6 dp discarded a whole call's precision and made `spent_usd`
   disagree with the blocks it is the sum of. All persisted money now rounds to
   `COST_DP`; pinned by
   `test_reported_dollar_figures_keep_per_call_resolution`.
7. **`>1 % parse-failure abort` had no minimum-call floor** (WP3) — the first
   unparsable response read as 100 %. Added `PARSE_FAIL_MIN_CALLS = 100`
   (~$0.016 of insurance); a real regression still trips within seconds.
8. **The snapshot high-water mark was specified as a timestamp** (WP3), which
   hides records appended during the same second. Implemented as a per-segment
   physical line count.
9. **UTC log timestamps lacked `Z` and milliseconds** (WP1).
   `logging.Formatter.formatTime` ignores `default_msec_format` whenever an
   explicit `datefmt` is passed — fixed by overriding `formatTime`.
10. **My own `reserve_frac = 0.02` was 908× oversized** (caught in review). 2 %
    of $200 = $4.00 = 14,534 worst-case calls, versus $0.004403 actually in
    flight at concurrency 16 — and not tied to what is in flight at all.
    Replaced with `concurrency × max_observed_cost_per_call`, floored at the
    `[measured]` worst-case prior $0.000275.
11. **My "31 prefix outliers" planning figure was wrong** (WP1, verified
    independently): 3890/3890 keyword hits corroborate `prefix_chars` against
    the header regex exactly, 0 mismatches (8359/8359 across all engines). R4
    retired. `strip_page_prefix` now *requires* corroboration before slicing,
    because a blind slice would consume a future bad offset silently and make
    `[PREFIX-MISS]` vacuously 0.

Also corrected in the plan: the subsample is **238 rows, not ~250**, so the
held-out set is **825, not 813**.

## Cost position

Superseded 2026-07-31 — see "Cost position (revised)" below. The figures as of
WP4 were:

| | |
| --- | --- |
| Cap (hard, user-set) | $200.00 |
| Spent to date | $0.00005525 |
| Typical projection, 49,170 calls | **$7.75** |
| Worst-case projection | **$13.53** |
| Worst-case calls affordable at $200 | ~727,000 |

Three independent derivations (mine, the plan review's, WP3b's) agree. The cap
functions as a **runaway-cost circuit breaker, not a scope limiter** — a
`BudgetRefused` is prima facie a bug (runaway prompt length, cache-key miss
storm, retry loop) and should be diagnosed, not worked around by raising the cap.

Three enforcement layers are live and tested: pre-flight refusal (exit 4),
continuous per-record `guard.check()` on the writer thread (exit 5, queue still
drained because in-flight calls are already billed), and ledger-vs-log
reconciliation that self-heals a lagging ledger but reports a ledger *ahead* of
the log as an integrity error.

## The one unresolved risk (R1): judge grade compression

Not a code problem, and the reason WP0 calibration is a mandatory gate.

| prompt | grade distribution | note |
| --- | --- | --- |
| verbatim UMBRELA + narrative | `{0:7, 1:29, 2:2, 3:2}` | 72.5 % at grade 1 — badly compressed |
| adapted `facet-v1` | `{0:7, 1:8, 2:36, 3:9}` | full range, but 60 % at grade 2 |

Agent-positive vs agent-negative means: 1.88 vs 1.79 — thin separation.
Mitigations already in place: the mandatory §3.3 gate, exponential gain (which
triples the 3-vs-2 reward, 7 vs 3), effect sizes with bootstrap CIs rather than
p-values alone, and pre-registered secondaries. **A null result at topic level
remains a genuine possible outcome.** If calibration comes back marginal, the
strongest available lever is the ~$16 3-sample self-consistency vote — easily
affordable inside the headroom above, and the user's call.

## 2026-07-31 follow-ups (three user instructions)

### 1. Cap lowered to $50 and made a required input

User: *"Change the hard budget to 50$ cap"*, then *"The budget cap should be
treated as a constant variable that has to be passed from the user before
running."*

`Config.budget_usd` is now `float | None` with **no default anywhere in code**.
Every subcommand that can reach Bedrock or report against the cap calls
`Config.require_budget_usd()`, which raises `ConfigError` (exit 1) naming the
export. `config.APPROVED_BUDGET_USD = 50.0` exists solely so the refusal message
can quote the approved figure — it is never read as a fallback. `describe()`
prints `budget=<unset>` rather than inventing a number for the log.

Verified live at four boundaries (probe dir removed afterwards):

| condition | result |
| --- | --- |
| var unset, `budget` subcommand | exit 1; `[LOAD] … budget=<unset>`; message quotes `export BM25_TUNE_BUDGET_USD=50.0` |
| `BM25_TUNE_BUDGET_USD=50.0` | exit 0; `[BUDGET] spent=$0.0000 cap=$50.00 remaining=$50.0000 (reserve=$0.0044 at concurrency 16)` |
| `BM25_TUNE_BUDGET_USD=0` | exit 1, "must be positive" (a zero ceiling trips on call 1 and reads in the log exactly like a runaway) |
| var unset, `verify-inputs` | proceeds past config — free subcommands unaffected |

`tests/bm25_tune/conftest.py::bm25_config` exports `50.0` explicitly, standing in
for the operator; the two tests that assert the refusal deliberately bypass the
fixture.

### Cost position (revised)

| | |
| --- | --- |
| Cap (hard, **must be exported per run**) | $50.00 |
| Spent to date | $0.00005525 |
| Typical projection, 49,450 calls | **$7.80** |
| Worst-case projection | **$13.61** |
| Worst-case calls affordable at $50 | ~182,000 (3.7× the whole plan) |
| Plan as % of cap | 16 % typical, 27 % worst case |

Headroom drops from ~15–25× to ~3.7×, which is still comfortably a circuit
breaker rather than a scope limiter. Two consequences now recorded in PLAN §6.2b:
no cost argument exists for cutting corners (judge the full pool, keep depth 30,
run the continuity pass), and the optional extras (finer grid, 3-sample
self-consistency vote at ~$16) are now real fractions of the ceiling and must be
requested with a cost line rather than assumed.

### 2. Top-10 relevant-document measures added

User asked for a P@10-style measure alongside nDCG@10, graded if possible, binary
(grade ≥ 2) otherwise, **computed in the same pass** so re-optimizing later needs
no re-judging. Both were added:

- `p10_bin2` — `#{top-10 grades ≥ 2} / 10`, matching `trec_eval`'s `P_10`
  (flat-10 denominator).
- `gp10` — graded precision@10, `sum(top-10 grades) / (10 × 3)`.

Verified independently of the authoring agent's tests, on a worked example:

| case | `gp10` | `p10_bin2` | note |
| --- | --- | --- | --- |
| worked example (5 graded hits) | 5/30 | 0.2 | matches hand calculation |
| one grade-3 hit only | 0.1 | 0.1 | flat-10 denominator confirmed, not "1.0 of 1 retrieved" |
| ten grade-1s | 1/3 | 0.0 | exactly the signal binarization discards |
| ten grade-2s | 0.667 | 1.0 | |
| ten grade-3s | 1.0 | 1.0 | |
| forward vs reversed ranking | 14/30 both | 0.5 both | rank-flat by design (`ndcg10_exp` 1.000000 vs 0.495883 on the same pair) |
| all-zero qrel for the topic | 0.0 | 0.0 | while `ndcg10_exp` is `None` |

End-to-end through real TREC run files → `load_run_dir` → `score_all` → all three
writers: `scores.csv` carries 32 columns including `gp10`, `gp10_topicmean`,
`gp10_n`, `p10_bin2`, `p10_bin2_topicmean`, `p10_bin2_n`; per-query.csv and
scores.md carry them too. **argmax `gp10` is derivable from the persisted file
alone** — the binding requirement.

Both are marked **exploratory**, not confirmatory: the pre-registered family
stays the six metrics in `metrics.PRE_REGISTERED_METRICS`, and `N_COMPARISONS=3`
(Bonferroni `0.05/3`) counts **configs, not metrics**, so adding columns does not
change the correction.

### 3. Judge calibration against the collection's base rate

User: *"Check whether calibration to the umbrella prompt is needed and it's part
of the WP's or the plan. But, keep in mind that most of the documents in the
collection are not relevant, and only very few should receive the highest score.
Of course, it shouldn't be too harsh either, as it wouldn't be very useful."*

**Answer to the question as asked:** yes, `umbrela-v1` calibration is already in
the plan — PLAN §3.2/§3.3, WP0/WP6, and `prompts.CALIBRATION_ORDER`. It is scored
on the same 280 pairs as every other variant and retained as a continuity column
for the team's prior umbrela-bedrock runs regardless of whether it passes.

Checking the base-rate constraint against what was written surfaced **two real
gaps**:

**Gap 1 — the §3.3 gate was one-sided (a defect, now fixed).** It read `modal
≤ 60 % AND all four grades used AND ≥ 20 % at grade ≥ 2`. Probed directly: the
distribution `{0:1, 1:1, 2:50, 3:48}` — 98 % of passages relevant, 48 %
maximally so — **passes all three conditions**. A judge with almost no
discriminative power was admitted, while the harsh mode was correctly rejected
(`umbrela-v1`'s measured `{0:7, 1:29, 2:2, 3:2}` fails on both modal 72.5 % and
10 % at ≥2). The gate is now four conditions, bounded on both sides:

1. modal grade ≤ 60 %
2. all four grades used
3. **15 % ≤ share at grade ≥ 2 ≤ 65 %**
4. **share at grade 3 ≤ 25 %**

The four-condition form was then run against every distribution the plan makes a
claim about, to check the claims rather than assert them (`≤` inclusive
throughout):

| distribution | modal | ≥2 | =3 | verdict |
| --- | --- | --- | --- | --- |
| saturated `{0:1,1:1,2:50,3:48}` | 0.500 ok | **0.980 FAIL** | **0.480 FAIL** | **FAIL** (passed the old gate) |
| `umbrela-v1` measured `{0:7,1:29,2:2,3:2}` | **0.725 FAIL** | **0.100 FAIL** | 0.050 ok | **FAIL** (from below) |
| `facet-v1` measured `{0:7,1:8,2:36,3:9}` | 0.600 ok | **0.750 FAIL** | 0.150 ok | **FAIL** (from above) |
| hypothetical on-target `{0:90,1:78,2:82,3:30}` | 0.321 ok | 0.400 ok | 0.107 ok | **PASS** |

So the new gate rejects both measured variants in opposite directions and admits a
base-rate-faithful one — which is the intended behaviour, and also why WP6's
outcome may legitimately be exit 6. Note `facet-v1` sits *exactly* on the modal
bound (0.600), so condition 1 is inclusive by design; it fails only on the new
ceiling.

The band is stated against the **sample**, which deliberately is not the pool.
Measured label mixes:

| set | agent-positive | negative | unjudged |
| --- | --- | --- | --- |
| 8580 observed (topic, chunk) pairs | 23.8 % | 73.9 % | 2.4 % |
| the 280-pair calibration sample | 42.5 % | 54.6 % | 2.9 % |

Positives are enriched ~1.8× on purpose (§3.1 stratifies so the agreement smell
test has both classes per topic), so a base-rate-faithful judge should land near
~40 % at ≥2 *on this sample* — roughly 8–36 % projected back onto the pool. The
15–65 % band brackets that with room either side. `calibrate` must print both
mixes next to the band so this is auditable rather than assumed.

Simulated cost of saturation — mean |ΔnDCG@10| between two configs sharing a
candidate set, grades drawn at random under each distribution:

| label distribution | share ≥2 | mean \|ΔnDCG@10\| |
| --- | --- | --- |
| base-rate-like | 25 % | 0.1047 |
| umbrela-like | 10 % | 0.0960 |
| facet-v1-like | 75 % | 0.0826 |
| saturated | 98 % | 0.0687 |

Saturation compresses the metric's dynamic range more than any other
distribution tested. **Stated limitation:** grades were random, so this measures
dynamic range under each distribution, not judge accuracy.

**Gap 2 — no prompt stated a base rate at all.** Grepping all four templates:
`umbrela-v1`/`umbrela-kw-v1` have no frequency cue whatsoever; `facet-v1` says
only "unrelated"; `facet-name-v1` adds "few"/"unrelated". Grade frequency was an
accident of rubric wording — which is precisely why the two measured variants
land on opposite sides of the real base rate (10 % vs 75 % at ≥2).

Fixed by adding a fifth variant, **`facet-rare3-v1`** (sha256
`6c3898c45743441b78142ce25f4197a9efd35d828e897adae10e5102719e409c`, 1827 rendered
chars, `query_slot="narrative"`, `emits_facet=True`). It is `facet-name-v1` plus a
`Calibration —` paragraph, and nothing else — same forced facet-naming step, same
scale, same output format — so WP0 reads the pair as a controlled contrast that
isolates the anchor. Verbatim (the whole point of this worklog entry; the wording
is what the n=280 measurement will be evidence about):

```
Calibration — this matters as much as the rubric below. These passages come from a broad web crawl retrieved by a keyword search, so MOST of them are not useful evidence: expect to give 0 or 1 to the majority, 2 to a substantial minority, and 3 to only a small minority of genuinely excellent passages. Do NOT reward a passage merely for being on the right topic or containing the right words. Equally, do not be stingy: a passage that really would help an answer writer must not be pushed down to 1 just because it is imperfect or covers only part of the need.
```

Grade 3 is relabelled "excellent and uncommon"; grade 0 extended to cover
"purely navigational, boilerplate, or promotional text". The percentages are
soft ("the majority", "a small minority") rather than a quota **because each call
sees one passage with no batch to rank against** — an unsatisfiable local quota
would only add noise. The "do not be stingy" clause is load-bearing on its own:
without it the variant becomes a deliberately harsh judge that the new lower
bound then rejects, and finding that out costs a full 280-pair pass. Both halves
are pinned by `test_only_facet_rare3_states_a_base_rate_and_states_it_both_ways`.

**This changes the going-in expectation.** `facet-v1`'s measured 75 % at ≥2 is
*above* the new ceiling and `umbrela-v1`'s 10 % is below the floor, so on their
priors both measured variants now fail — in opposite directions. `facet-rare3-v1`
is the leading candidate and `facet-name-v1` the plausible second. Those priors
came from an ad-hoc n=60 sample, not from `sample-280.jsonl`, so WP0 re-measures
all five on identical pairs before anything is concluded.

Calibration volume rises from 4 × 280 + 50 = 1,170 calls (~$0.18) to
**5 × 280 + 50 = 1,450 calls (~$0.23)**, ~20–25 min.

The gate constants live in PLAN §3.3 only — `calibrate` is still a stub
(`EXIT_GATE_FAILED = 6` is its sole code trace), so **WP6 must implement the
four-condition form, not the old three-condition one.**

Full suite after all three follow-ups: **1270 passed, 0 skipped, 5 deselected**.

## Next

- **WP5** — end-to-end `test_cli.py` (resume, budget-stop, `--fresh`
  protection, drain-code table). In flight.
- **WP6 = the calibration pilot** (1,450 calls, ~$0.23). Implements and applies
  the **four-condition two-sided** §3.3 gate over five variants, produces
  `calibration/report.md`. **The user reviews that report and confirms the prompt
  version before WP7 launches** — no further Bedrock spend before then.
- WP7 Stage A (`--pilot 200` first, then the full job), WP8 Stage B +
  statistics over the 825 held-out queries, WP9 docs/publication.
