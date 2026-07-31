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

Agent-positive vs agent-negative means: 1.88 vs 1.79 — thin separation. **Read
this alongside §4 Finding 1:** hand-grading the same kind of pairs gives 2.60 vs
1.47, so part of the thinness is the *judge* compressing and part is that the
agent's `negative` class is ~half relevant to begin with. A perfectly calibrated
judge would not reach 1.88-vs-0.x here, and the separation that matters for R1 is
the judge's use of the full scale, not its agreement with a staging decision.
Mitigations already in place: the mandatory §3.3 gate, exponential gain (which
triples the 3-vs-2 reward, 7 vs 3), effect sizes with bootstrap CIs rather than
p-values alone, and pre-registered secondaries. **A null result at topic level
remains a genuine possible outcome.** If calibration comes back marginal, the
strongest available lever is the ~$16 3-sample self-consistency vote — easily
affordable inside the headroom above, and the user's call.

## 2026-07-31 follow-ups (four user instructions)

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

> **⚠ Conditions 3–4 were WRONG and are superseded by §4 below** (`20 %–90 %` and
> `≤ 50 %`). They were set a priori, and the hand-grading in §4 — done a few hours
> later, at the user's instruction — landed at **65.3 % / 25.0 %**, i.e. failing
> both. Everything in the rest of this subsection is retained as the record of what
> was believed at the time; read §4 before acting on any of it.

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

> **⚠ RETRACTED — see §4, Finding 3.** That stated limitation turned out to be
> fatal rather than minor. Re-running with grades *correlated to retrieval rank*
> reverses the column's ordering entirely (umbrela-like 0.150 vs saturated 0.050),
> because mean |Δ| grows with label variance whether or not that variance carries
> signal. The right statistic is power, and by that measure the distribution
> barely matters. Do not cite this table.

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

> **⚠ Superseded by §4.** Under the corrected band `facet-v1` **passes** (0.750 is
> inside 0.20–0.90), so only `umbrela-v1`/`umbrela-kw-v1` are expected to fail on
> their priors. `facet-rare3-v1` is *not* the leading candidate — §4 Finding 4
> reclassifies its base-rate anchor as a hypothesis that may push the judge below
> the floor, since the claim it makes about the corpus is false of the judged pool.

Calibration volume rises from 4 × 280 + 50 = 1,170 calls (~$0.18) to
**5 × 280 + 50 = 1,450 calls (~$0.23)**, ~20–25 min.

The gate constants live in PLAN §3.3 only — `calibrate` is still a stub
(`EXIT_GATE_FAILED = 6` is its sole code trace), so **WP6 must implement the
four-condition form, not the old three-condition one.**

Full suite after all three follow-ups: **1270 passed, 0 skipped, 5 deselected**.

### 4. Hand-grading 22 real passages, and what it changed

User: *"Before that, sample a few examples and judge them yourself, also check
whether they were staged or rejected in the original file as a guidance. These
should guide the prompt calibration. No need to add any text from my instructions
to the umbrella prompt, the instructions are only for you to guide calibration."*

Done as asked, and it **overturned two things committed earlier the same day** —
the gate's upper bounds (§3, Gap 1) and the saturation argument behind them (§3's
mean-|Δ| table). Both are struck through above; this section is the replacement.
Per the last sentence of the instruction, **no prompt template was modified** —
the guidance went into the gate constants, PLAN §3.3b, and Finding 4's warning
against over-correcting.

Surviving artifacts (this section's judgment rests on them):

| asset | what it is |
| --- | --- |
| `assets/2026-07-31-judge-sample-14-stratified.json` | pass 1: 14 hits, seed 1729, stratified 5 pos / 7 neg / 2 unjudged, with `label`/`reason`/`commit_reason` and full passage text |
| `assets/2026-07-31-judge-sample-neg8.json` | pass 2: 8 more negatives, seed 90210, pass-1 chunk ids excluded |
| `assets/2026-07-31-hand-grade-tally.py` | the sampler (`--resample`) + every figure quoted below, recomputed from the two JSONs |
| `assets/2026-07-31-label-distribution-sim.py` | the three simulation probes, including the one that falsified §3's table |

**Method.** Sampled from
`data/bm25-tune/inputs/trec-rag26-test119-search-labeled.jsonl`, keyword rows
only, `strip_page_prefix` applied. Graded each passage against its **narrative**
(the judge target PLAN §0 settles on) on the 0–3 scale, **blind to the agent's
label** — grades 1–5, then 6–10, then 11–14 were recorded before any label was
revealed; the label/`commit_reason` columns were printed only afterwards. Pass 2
existed because 3-of-7 negatives at ≥2 was too thin a base to set a gate bound
on. Grade 5 was recorded as "0/1 borderline" and resolved to 0.

#### The full matrix (all 22, nothing omitted)

| # | topic | chunk | rank | BM25 | chars | agent label | my grade |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `rag2026-85` | `shard_03697_80708_p1` | 5 | 18.97 | 2280 | positive | **2** |
| 2 | `rag2026-74` | `shard_01655_22066_p1` | 4 | 26.44 | 1645 | negative | **1** |
| 3 | `rag2026-34` | `shard_05805_11973_p1` | 3 | 30.08 | 3069 | positive | **3** |
| 4 | `rag2026-23` | `shard_05569_72495_p2` | 6 | 21.52 | 2148 | unjudged | **2** |
| 5 | `rag2026-8` | `shard_03806_64057_p2` | 4 | 29.81 | 1273 | negative | **0** |
| 6 | `rag2026-102` | `shard_00504_62147_p2` | 7 | 37.43 | 1796 | positive | **3** |
| 7 | `rag2026-94` | `shard_01362_64274_p3` | 3 | 20.05 | 2238 | positive | **2** |
| 8 | `rag2026-96` | `shard_02551_69125_p2` | 8 | 19.48 | 1356 | negative | **0** |
| 9 | `rag2026-52` | `shard_04679_62961_p2` | 4 | 18.35 | 2255 | negative | **0** |
| 10 | `rag2026-8` | `shard_03171_23894_p1` | 3 | 23.94 | 2519 | positive | **3** |
| 11 | `rag2026-24` | `shard_05399_52238_p1` | 3 | 27.64 | 2672 | negative | **2** |
| 12 | `rag2026-40` | `shard_01046_66646_p4` | 4 | 25.30 | 2629 | negative | **2** |
| 13 | `rag2026-40` | `shard_06199_45477_p1` | 6 | 19.25 | 3072 | negative | **3** |
| 14 | `rag2026-21` | `shard_02585_11006_p4` | 10 | 20.35 | 1642 | unjudged | **1** |
| 15 | `rag2026-82` | `shard_00742_69346_p2` | 8 | 24.49 | 1559 | negative | **2** |
| 16 | `rag2026-107` | `shard_00776_62651_p1` | 6 | 27.53 | 1788 | negative | **1** |
| 17 | `rag2026-109` | `shard_01865_59827_p19` | 8 | 29.97 | 2468 | negative | **2** |
| 18 | `rag2026-6` | `shard_01463_13953_p1` | 9 | 29.46 | 2365 | negative | **1** |
| 19 | `rag2026-118` | `shard_00617_884_p1` | 5 | 20.03 | 1231 | negative | **1** |
| 20 | `rag2026-76` | `shard_04306_61146_p3` | 8 | 28.87 | 1847 | negative | **2** |
| 21 | `rag2026-26` | `shard_05819_37837_p2` | 3 | 32.19 | 2772 | negative | **3** |
| 22 | `rag2026-71` | `shard_03338_39939_p1` | 2 | 21.43 | 2251 | negative | **2** |

The keyword queries, verbatim (these are what aus_agent issued; the judge sees the
narrative, not these, but they are what BM25 retrieved on and therefore what a
`k1`/`b` sweep will move):

| # | search_query |
| --- | --- |
| 1 | `autonomous driving winter rain fog nighttime perception` |
| 2 | `Midway Japanese victory Pacific War turning point` |
| 3 | `portable HEPA units classrooms wildfire smoke schools fine particles` |
| 4 | `Climate Change Response Act Taiwan carbon fee intergenerational equity implementation` |
| 5 | `2020 election poll watchers blocked mail ballots drop boxes` |
| 6 | `Hague law aerial bombardment civilians military necessity proportionality World War II` |
| 7 | `voting age political competence uniform age threshold democracy` |
| 8 | `guaranteed income women bargaining power economic autonomy cash transfer` |
| 9 | `Washington DC July 4 2025 weekend events activities` |
| 10 | `Cyber Ninjas Arizona audit criticism methodology 2020 results` |
| 11 | `Ghana Pan-African diplomacy Nkrumah Cold War` |
| 12 | `workplace wearable monitoring employee autonomy privacy consent performance data` |
| 13 | `workplace human enhancement exoskeletons employee safety fairness pressure` |
| 14 | `Green Bay Packers game day traffic neighborhood noise parking residents` |
| 15 | `IEX speed bump high-frequency trading market structure` |
| 16 | `Western Roman Empire survival after 395 CE collapse turning point` |
| 17 | `FDA software medical device clinical decision support generative AI radiology regulatory` |
| 18 | `COVID-19 pandemic before after global changes public health work education travel economy mental health` |
| 19 | `sports women leadership pay equity working conditions coaches` |
| 20 | `Korean War United Nations collective security Security Council Soviet boycott` |
| 21 | `Canada Oregon Netherlands Belgium Switzerland assisted dying safeguards disability dementia Indigenous clinicians palliative social support` |
| 22 | `plea bargaining race poverty effects victims interests accountability data reporting` |

#### Why each grade, in one line (graded by reading, against the narrative)

| # | grade | reasoning |
| --- | --- | --- |
| 1 | 2 | Waymo weather blog write-up: names the real failure modes (condensation, lens fog, droplets, road dirt, ice, wet-road glare) for the shuttle-pilot narrative's winter-rain facet, but it is vendor PR, thin on what the city should require. |
| 2 | 1 | Battle-of-Midway commemoration boilerplate, repeated four times. On-topic for an Axis-victory counterfactual, but supplies no mechanism a counterfactual could turn on. |
| 3 | 3 | Missoula clean-air needs assessment with exactly the numbers the district asks for: 698 classrooms with no smoke filtration, 280 of those without AC, 15.6 % with MERV-13+ or portable cleaners. Concrete, quotable, on the budget facet. |
| 4 | 2 | Hansen on carbon fee-and-dividend and intergenerational inequity — squarely on the narrative's duties-to-future-people facet, but it is advocacy quotation, not the ethical-frameworks comparison requested. |
| 5 | 0 | Erie County mail-ballot return mechanics. Keyword-matches "drop boxes"/"poll" and nothing else; the narrative is about fraud claims and election-integrity law. |
| 6 | 3 | Lauterpacht/Parks/Johnson footnote apparatus documenting the wartime erosion of the anti-civilian norm and the British inclusion of enemy morale as a target by 1941 — the primary-source spine of the bombing-ethics timeline. |
| 7 | 2 | The competency argument (age limits track competence; drunk adults may still vote) is directly usable on the voting-age narrative, but it is one blog-style argument, not the intergenerational-equity treatment. |
| 8 | 0 | A Colombian agroecology cooperative (AMOY, Yolombó). "Economic autonomy"/"bargaining power" match lexically; nothing about guaranteed income or cash transfers. |
| 9 | 0 | SEO spam colliding Memorial Day with Fourth of July across Atlanta/Ohio/Florida. Wrong holiday, wrong city, no itinerary. |
| 10 | 3 | Hobbs on the Maricopa audit: procedures changed on the floor, Cyber Ninjas had no election experience, initially refused to release procedures. Named sources for the audit facet. |
| 11 | 2 | Nkrumah/Pan-Africanism and Operation Cold Chop including the CIA angle — real coverage of two facets, but encyclopedic and it skips Volta/Akosombo and cocoa entirely. |
| 12 | 2 | Wearables in the workplace: privacy, third-party data sharing, productivity monitoring, pressure to share data. Genuinely on the monitoring facet, generic in treatment. |
| 13 | **3** | DHL Trend Research on bionic enhancement: active vs passive exoskeletons, lifting/reaching/overhead applicability, musculoskeletal-injury and fatigue evidence, older-worker angle. Exactly the exoskeleton facet, with specifics. **Agent rejected it.** |
| 14 | 1 | NFL Youth Football Fund grants and Packers Coach of the Week. Packers-adjacent, says nothing about living in Green Bay. |
| 15 | 2 | The Katsuyama/IEX 60-km-fiber speed bump explained concretely — useful on the speed-bump facet, but it is a Michael Lewis retelling with no policy analysis. |
| 16 | 1 | Blog post on why the Western Empire fell, ending at 410 CE. The narrative demands a *post-395* turning point and a counterfactual; this gives neither. |
| 17 | 2 | FDA SaMD framing, DEN-numbered clearances, locked vs continuously-learning software — right on the regulatory facet, but arrives via digital *pathology*, not the pitched vision-language model. |
| 18 | 1 | An essay-mill topic list ("Cancel Culture Before and After…", "Post-Pandemic Work Environment"). Covers every facet as a title and none as content. |
| 19 | 1 | Textbook chapter intro on gender equity in athletics — announces what it will discuss; no interventions, metrics, or pipeline evidence the board could act on. |
| 20 | 2 | NSC-68, rollback, and the Soviet Security Council boycott/Taiwan seating pretext: real content on the UN facet, inside a polemic ("the war it had stoked") needing heavy discounting. |
| 21 | 3 | The five-jurisdiction legislative landscape the narrative names, plus the vulnerable-persons objection — directly the comparison asked for. |
| 22 | 2 | Plea-bargaining reform levers: victim input, mandatory minimums, practitioner training. On several facets at once, but summary-level. |

#### Finding 1 — the agent's `label` is a *staging* decision, not a relevance judgment

This is the part of the user's instruction that paid off most. Cross-tabulating my
blind grades against the labels:

| | my grade ≥2 | my grade <2 | n | mean grade |
| --- | --- | --- | --- | --- |
| agent `positive` (committed) | 5 | 0 | 5 | **2.60** |
| agent `negative` (not selected) | **8** | 7 | 15 | **1.47** |
| agent `unjudged` (voided batch) | 1 | 1 | 2 | 1.50 |

The ordering is right — committed passages really are better — but **53 % of the
rejected passages are grade ≥2**, and every committed one is. So `negative` means
"not staged into the committed context", which is a *set*-level decision made
under a context budget, and it is routinely satisfied by de-duplication rather
than by irrelevance.

Row 13 is the clean demonstration. It is a DHL exoskeleton passage I graded 3,
labelled `negative`. Dumping everything topic `rag2026-40` committed shows the
**same keyword query** — `workplace human enhancement exoskeletons employee safety
fairness pressure` — committed `shard_06028_30922_p1` at rank 1, on exoskeletons,
"Explains occupational exoskeleton function, potential ergonomic benefits, and
practical limitations including cost, comfort, mobility, and customization." The
agent had the facet covered from a better-ranked hit and dropped mine. That is not
a relevance signal.

Measured at scale over all **6,638 rejected keyword hits** — this is the number
that matters, not the 15-passage read:

```
keyword negatives: 6638
  ...where the SAME query also yielded a committed chunk: 6232 (93.9%)
  ...and where a committed chunk outranked it:            5103 (76.9%)

committed chunks per topic (keyword only): min=5 p50=19 mean=19.9 max=37
keyword queries per topic:                 min=3 p50=8  max=16
queries with ZERO committed hits: 65 of 1070 (6.1%), spread over 44 topics
```

**Consequence for the harness:** the agent's 23.8 % positive rate is *not* an
estimate of the relevant share, and a gate bound derived from it is calibrated
against the wrong quantity. PLAN §3.3's caveat now says so explicitly — a judge
scoring well above 23.8 % is expected, not a red flag. The label mix keeps its two
legitimate uses: stratifying the 280-pair sample (§3.1), and the agreement smell
test, which should show **ordering** (mean grade committed > rejected) and must not
be read as accuracy.

#### Finding 2 — this pool is not mostly-irrelevant at depth 10

My 22 grades tally to `{0:3, 1:5, 2:9, 3:5}` — 63.6 % at ≥2. That sample is
stratified, so it is not itself a base rate. Reweighting by class to the pool's
real mix (2368 positive / 6638 negative / 202 unjudged):

| basis | 0 | 1 | 2 | 3 | ≥2 | =3 | modal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw 22 (stratified — **not** a base rate) | 3 | 5 | 9 | 5 | 0.636 | 0.227 | 0.409 |
| **reweighted to the pool** (2368/6638/202) | 14 % | 20 % | 40 % | 25 % | **0.653** | **0.250** | 0.402 |
| reweighted to the 280-pair sample (42.5/54.6/2.9) | 11 % | 16 % | 40 % | 33 % | 0.731 | 0.328 | 0.403 |

**The pool-reweighted row fails the gate committed in §3 above** (65.3 % vs a
65 % ceiling; 25.0 % vs a 25 % ceiling, inclusive). A gate that rejects a careful
human read of the very data it governs is measuring its own assumptions, so the
bounds were widened to **20 %–90 % at ≥2** and **≤ 50 % at grade 3**.

The high base rate is structural, not a grading error: these are **BM25 top-4-to-10
hits for agent-authored keyword queries against broad multi-facet narratives**. The
narratives ask for many things at once (see the queries table — topic 21 alone
names five jurisdictions and six protected groups), so a passage covering *one*
facet earns 2 under any facet-aware rubric. The user's "most documents are not
relevant" is true of **ClimbMix as a corpus** and stays the right instinct for
**grade 3** in particular; it is not true of **this pool**, and the pool is what
gets judged. Even so, the read is not lenient at the top: only 5 of 22 got a 3, and
three of the eight `negative`-but-≥2 passages got exactly 2.

Wilson 95 % CIs at n=22 on the raw tally: share ≥2 = 14/22 → **[0.430, 0.803]**;
share =3 = 5/22 → **[0.101, 0.434]**. Wide, which is a further argument for loose
bounds rather than a reason to distrust the direction.

#### Finding 3 — mean |Δ| was the wrong statistic; the retraction

§3's table above said saturation compresses nDCG@10's dynamic range, on a
simulation with grades assigned **at random**. Re-running with grades correlated to
retrieval rank — the realistic case, since retrieval works — **reverses the
ordering**:

| label distribution | ≥2 | mean \|Δ\| rank-correlated | mean \|Δ\| random (§3's column) |
| --- | --- | --- | --- |
| `umbrela-v1` measured `{18,72,5,5}` | 0.10 | **0.1498** | 0.1375 |
| base-rate-like `{45,30,20,5}` | 0.25 | 0.1421 | 0.1489 |
| on-target `{32,28,29,11}` | 0.40 | 0.1156 | 0.1372 |
| hand-read, pool-wt `{14,20,40,25}` | 0.65 | 0.0778 | 0.1066 |
| `facet-v1` measured `{12,13,60,15}` | 0.75 | 0.0771 | 0.0991 |
| hand-read, sample-wt `{11,16,40,33}` | 0.73 | 0.0674 | 0.0945 |
| saturated `{1,1,50,48}` | 0.98 | 0.0496 | 0.0617 |

The harshest distribution now shows the *largest* mean |Δ|. Diagnosis: mean |Δ| is
a spread statistic, so it grows with label variance whether or not that variance
carries signal — it cannot distinguish a discriminating judge from a noisy one.

The statistic the experiment actually needs is **power**: how often a paired t-test
at Bonferroni 0.05/3 detects a config that genuinely ranks better (noise sd 1.0 vs
1.0+gap).

| label distribution | ≥2 | power, n=825, gap 0.30 | power, n=119, gap 0.06 | Cohen d (small) |
| --- | --- | --- | --- | --- |
| `umbrela-v1` `{18,72,5,5}` | 0.10 | 1.00 | 0.03 | 0.055 |
| base-rate-like `{45,30,20,5}` | 0.25 | 1.00 | 0.01 | 0.069 |
| on-target `{32,28,29,11}` | 0.40 | 1.00 | 0.03 | 0.065 |
| hand-read, pool-wt `{14,20,40,25}` | 0.65 | 1.00 | 0.03 | 0.063 |
| `facet-v1` `{12,13,60,15}` | 0.75 | 0.99 | 0.02 | 0.049 |
| hand-read, sample-wt `{11,16,40,33}` | 0.73 | 1.00 | 0.01 | 0.062 |
| saturated `{1,1,50,48}` | 0.98 | 1.00 | 0.01 | 0.064 |

Power is ~1.00 for **every** distribution at the large effect and ≤0.03 for
**every** one at the small effect; usable-topic share is 100 % throughout. **The
label distribution is not the binding constraint on power — sample size and effect
size are.** R1 (grade compression) therefore stands on its own evidence and no
longer borrows this argument, and PLAN §3.4's warning is unaffected.

What survives to justify a ceiling at all is only the genuinely degenerate corner —
all-grade-2, all-grade-3, ~98 % relevant — where IDCG converges on DCG and nDCG@10
approaches 1 for every config regardless of ranking. Hence 90 % / 50 %, loose
enough to admit the hand-read distribution and still reject that corner.

#### The revised gate, verified

```
GATE_MAX_MODAL_SHARE = 0.60   GATE_MIN_SHARE_GE2 = 0.20
GATE_MAX_SHARE_GE2   = 0.90   GATE_MAX_SHARE_EQ3 = 0.50
GATE_REQUIRE_ALL_GRADES = True        # every bound inclusive
```

| distribution | modal | ≥2 | =3 | verdict |
| --- | --- | --- | --- | --- |
| `umbrela-v1` measured `{18,72,5,5}` | 0.725 | 0.100 | 0.050 | **FAIL** cond. 1, 3 (from below) |
| `facet-v1` measured `{12,13,60,15}` | 0.600 | 0.750 | 0.150 | **PASS** (on the modal bound) |
| hand-read, sample-wt `{11,16,40,33}` | 0.403 | 0.731 | 0.328 | **PASS** |
| hand-read, pool-wt `{14,20,40,25}` | 0.402 | 0.653 | 0.250 | **PASS** |
| saturated `{1,1,50,48}` | 0.500 | 0.980 | 0.480 | **FAIL** cond. 3 (from above) |
| all-grade-2 `{0,0,100,0}` | 1.000 | 1.000 | 0.000 | **FAIL** cond. 1, 2, 3 |
| all-grade-3 `{0,0,0,100}` | 1.000 | 1.000 | 1.000 | **FAIL** all four |
| on-target `{32,28,29,11}` | 0.321 | 0.398 | 0.107 | **PASS** |

Both degenerate corners and both measured extremes behave; the human reading
passes. **The gate is a floor on usability, not the selection criterion** — several
variants can pass, and WP6's report plus the user's review pick the winner.

#### Finding 4 — do not over-correct the prompts

The instruction's last sentence (*"No need to add any text from my instructions to
the umbrella prompt"*) turned out to be the right call on the evidence, not just a
scoping preference. `facet-rare3-v1`, added a few hours earlier under §3 Gap 2,
opens with:

> These passages come from a broad web crawl retrieved by a keyword search, so
> **MOST of them are not useful evidence**

Findings 1–2 say that sentence is **false of the judged pool** — ~65 % of it is
grade ≥2 by hand. It may therefore push the judge *below* the 20 % floor, i.e.
the variant introduced to fix leniency could fail from the harsh side. It is a
**hypothesis WP0 measures, not a fix already applied.** Concretely:

- `facet-rare3-v1` is **not** the presumed winner; all three facet variants are
  live going in, and `facet-v1` — which §3 expected to fail — passes on its prior.
- The **"Equally, do not be stingy"** counterweight is what keeps the variant
  viable at all and must not be dropped;
  `test_only_facet_rare3_states_a_base_rate_and_states_it_both_ways` pins both
  halves.
- Do **not** tighten the other four templates toward the anchor before the n=280
  measurement exists — that would remove the contrast the calibration is for.
- No template text was edited in this pass, so all five sha256 pins are unchanged.

The `prompts.py` module docstring and PLAN §3.2/§3.3b now carry this caveat, so the
next reader does not mistake the new variant for a correction that landed.

Files changed in this pass: `tasks/bm25_tune/PLAN.md` (§0, §3.3 gate constants,
§3.3 caveat + decision rule, new §3.3b, R1), `tasks/bm25_tune/bm25tune/prompts.py`
(module docstring only — no template text), this worklog, and the four assets.
Full suite re-run after the PLAN.md structural edits (which
`test_facet_v1_matches_the_text_measured_in_the_plan` parses): **1270 passed, 0
skipped, 5 deselected**. **No Bedrock spend in this pass** — every figure above is
from the labeled input file or a local simulation.

## Next

- **WP5** — end-to-end `test_cli.py` (resume, budget-stop, `--fresh`
  protection, drain-code table). In flight.
- **WP6 = the calibration pilot** (1,450 calls, ~$0.23). Implements and applies
  the **four-condition two-sided** §3.3 gate over five variants — using the
  **§4-corrected constants** (0.60 / 0.20 / **0.90** / **0.50**, all inclusive),
  not §3's — and produces `calibration/report.md`. The report must print the pool
  and sample label mixes next to the band, and must **not** present agreement with
  the agent's `label` as accuracy (§4 Finding 1). **The user reviews that report
  and confirms the prompt version before WP7 launches** — no further Bedrock spend
  before then.
- WP7 Stage A (`--pilot 200` first, then the full job), WP8 Stage B +
  statistics over the 825 held-out queries, WP9 docs/publication.
