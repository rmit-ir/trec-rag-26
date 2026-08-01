# BM25 tune harness — execution plan: WP6 finish → WP7 → WP8 → WP9

Repo `/home/el7/E103037/repos/trec-rag-26`, branch `feat/bm25-tune`. Read
`tasks/bm25_tune/HANDOFF.md` first, then PLAN §3.3, §5.6, §5.7, §6, §7 as needed.
All commands run from the repo root. (Plan authored by Fable, 2026-07-31.)

**Standing rules for every executor (non-negotiable):**
- `BM25_TUNE_BUDGET_USD` has **no default**. Export `BM25_TUNE_BUDGET_USD=50.0`
  before any spending command; never raise it on your own initiative — a
  `[BUDGET]` trip is prima facie a bug (PLAN §6.2b/R11), escalate with a
  diagnosis.
- **No Bedrock spend at all in WP6-finish.** The calibrate tests are fully
  offline. The first real spend after WP3's single validation call is the
  user-run `calibrate` (~$0.23), and it is the *user* who runs it.
- Tests: `export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm" && bash
  scripts/test.sh` (skip-free suite; fails on any skip). Targeted:
  `DEP_GROUPS="--group dev --group o3-deep-research --group aus-agent"; uv run
  $DEP_GROUPS pytest tests/bm25_tune -q`.
- Task-env CLI: `uv run --project tasks/bm25_tune python -m bm25tune <subcommand>`.

---

## Stage 1 — Finish WP6: offline `calibrate` CLI tests, suite green, commit, STOP

**Spend: $0.00.** Every test runs under the root conftest's
`no_network`/`no_ambient_creds` autouse fixtures — a test that reaches Bedrock
fails loudly.

### Preconditions
- Working tree already contains the uncommitted `cmd_calibrate` implementation in
  `tasks/bm25_tune/bm25tune/cli.py` (imports cleanly; the three prior-session
  bugs are fixed). Do **not** re-implement `cmd_calibrate`; only write tests. If
  a test exposes a real defect in the calibrate helpers, fix minimally in
  `cli.py` and note it in the commit message.
- Existing 46 tests (`test_calibration.py` + `test_cli.py`) pass.

### 1.1 New test file: `tests/bm25_tune/test_cli_calibrate.py`

Create a **sibling** file (do not bloat `test_cli.py`; cross-file imports between
test modules are fragile under `--import-mode=importlib`, so give this file its
own small fakes). No `_FakeLucene` needed — calibration reads historical hit text
from `ObservedHit.text` and never opens the index.

**Fixture wiring (mirror `test_cli.py`'s `harness` fixture, minus the searcher):**
1. Build on `bm25_config` (tmp data dir seeded with the mini fixture,
   `BM25_TUNE_BUDGET_USD=50.0`).
2. Write the query file the calibrate path requires — `_calibration_pairs` calls
   `_topic_context`, which reads `queries/keyword-1063.jsonl`:
   ```python
   queries = extract.load_keyword_queries(mini_labeled_path)
   extract.write_query_file(bm25_config.queries_dir / cli.QUERIES_FULL_BASENAME, queries)
   ```
3. A transport fake `_CalibConverse` modeled on `_FakeConverse` (records prompts,
   reasoning-block-**first** envelope, `stopReason="end_turn"`, large usage
   `inputTokens=2000, outputTokens=800` so layer-2 budget trips are reachable),
   but with grade **keyed on passage text, not prompt sha1**:
   ```python
   def _grade_for(prompt: str) -> int:
       for chunk_id, text in texts.items():
           if text in prompt:
               return grade_by_chunk[chunk_id]
       raise AssertionError("prompt carries no known passage")
   ```
   This forces a chosen grade distribution deterministically and **identically
   across all five variants** (passage text appears verbatim in every variant's
   `{p}` slot).
4. Monkeypatch factories exactly as `test_cli.py` does:
   `judge.BedrockJudge` → real class with `converse=fake, sleep=lambda s: None,
   rng=random.Random(0)`; `judge.JudgePoolDriver` → real class captured into a
   `driver_box` for pacing.
5. Replicate the `_quiet_logging` autouse fixture (calibrate re-points logging at
   `calibration/calibrate.log`).
6. Harness method: `calibrate(*extra)` →
   `cli.main(["calibrate", "--n", "4", "--stability-pairs", "0",
   "--concurrency", "1", *extra])`.

**Mini-fixture facts (verify against the committed fixture before relying on
exact ids):** 6 observed hits over 2 topics; agent classes ≈ 3 positive, 2
negative, 1 unjudged. `extract.calibration_sample(hits, n=4, seed=7)` is
deterministic — **assert the ids it returns rather than hardcoding a guess**.
Use `--n 4`, never assume 280. `--stability-pairs 2` only where the probe is
under test, `0` elsewhere.

**Grade maps:**
- **PASS** (all four grades used; modal ≤0.60; share≥2 in [0.20,0.90]; share=3
  ≤0.50; positives above negatives → AUC=1.0): e.g.
  `{<pos hi>:3, <pos>:2, <neg>:1, <neg>:0}`.
- **FAIL** (every pair grade 2 → fails modal 1.0, all-grades-used, share≥2 1.0):
  `{every chunk: 2}`.

### 1.2 The test cases (each with a docstring saying why it matters)

1. **Artifacts written.** PASS map, probe off → exit `EXIT_OK`;
   `calibration/sample-280.jsonl` exists (basename is the constant regardless of
   `--n`) with exactly 4 rows; `report.md` + `report.json` exist;
   `report.json["winner"]` non-null and in `prompts.all_versions()`;
   `["gated"] is False`. Do not pin *which* variant wins unless you also assert
   the tie-break determinism deliberately.
2. **Five variants, byte-identical pairs, billed once.** Probe off: total calls
   == `5 × 4 = 20`; per variant the embedded passage texts == the 4 sampled;
   no (variant, passage) twice; `spent_usd() == approx(20 * CALL_USD)` where
   `CALL_USD = pricing.load_rates(...).call_usd(2000, 800)` (never hardcoded).
3. **Re-run fully cached — zero further calls/spend.** Two runs, **both
   `--stability-pairs 0`**. Second: exit 0, calls unchanged, spend unchanged.
   (Probe is cache-bypassing by design, so the zero-spend property holds only for
   variant judging — state that in the docstring.)
4. **Gate PASS → exit 0, named winner.** Assert `[GATE] PASS — recommended
   judge:` via caplog; `report.json["passing"]` names all five under PASS.
5. **Gate FAIL → exit 6, report still written.** FAIL map → returns
   `EXIT_GATE_FAILED` (6); both artifacts exist; `["gated"] is True`,
   `["winner"] is None`, `["best_effort"]` non-null; `[GATE] no variant passed`.
6. **Stability probe cache-bypassing under `stage="calib-probe"`.** PASS map,
   `--stability-pairs 2`: exit 0; calls == `20 + 2`; exactly 2 successful log
   records carry `stage == "calib-probe"` naming the winner's `prompt_version`;
   winner's report entry has `stability_pairs == 2`, `stability_match_rate ==
   1.0`; non-winners `None`; winner's qrels snapshot key count still 4.
7. **Mid-calibration budget stop → exit 5 + partial report.** PASS map, probe
   off, `pace_to_writer()`, cap via
   `_cap_that_passes_preflight_but_trips_midrun(4)` set with
   `monkeypatch.setenv("BM25_TUNE_BUDGET_USD", repr(cap))`. Expect
   `EXIT_BUDGET_STOP` (5); artifacts exist (partial, `variants` len ≥ 1); spend ==
   billed × `CALL_USD`; successful log records ⊂ variant 1's 4 pairs. **Caution:**
   the cap must admit ≥1 completed judgment (`_variant_result` on zero grades
   raises `CalibrationError`); assert `0 < judged < 4`. The trip must be layer-2,
   not a per-variant preflight refusal (that raises `BudgetRefused` → exit 4, no
   report — a different path).
8. **`report.md` carries both label mixes + §3.3b caveats.** Assert `"sample
   label mix"` and `"pool label mix"` present; the three preamble strings
   present — `"floor on usability, not the selection criterion"`, `"smell test,
   not accuracy"`, `"deliberately not the pool"`; `report.json["pool_label_mix"]
   == calibration.POOL_LABEL_MIX`.

Optional (cheap, high value): a **resume** case — `fail_from(k,
"ExpiredTokenException")` → exit 3, re-run → exit 0, zero re-judged pairs.

### 1.3 Verify and commit
```bash
export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"
bash scripts/test.sh            # FULL suite — cli.py is shared; must be green + skip-free
```
Commit on `feat/bm25-tune`: modified `cli.py`, new `test_cli_calibrate.py`, and
`HANDOFF.md` + this plan. Message e.g. `feat(bm25_tune): WP6 calibrate driver —
5-variant judging, gate, report` with the co-author line.

### 1.4 ⛔ HARD STOP — human gate (first real spend)
**Do not proceed to WP7. Do not run `calibrate` against real Bedrock yourself.**
Hand the user:
```bash
export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"
export BM25_TUNE_BUDGET_USD=50.0
export AWS_REGION=ap-southeast-2   # + fresh SSO creds
uv run --project tasks/bm25_tune python -m bm25tune calibrate \
  2>&1 | tee /tmp/bm25-tune-calibrate.log
```
- ~1,450 calls ≈ **$0.23 typical / $0.40 worst**. 💰 user-executed,
  user-authorized. Exit 0 = passed; exit 6 = gated (escalate with least-bad
  ranking; proceeding demotes headline to binarized nDCG@10 per §3.3 fallback).
- User reviews `data/bm25-tune/calibration/report.md` and **confirms the prompt
  version in writing** (`<PV>`). Surface §6.2b's optional extras (self-consistency
  ≈$16; finer grid ≈+$1; full-pool continuity ≈+$4) with the report.
- **No sweep spend before this confirmation.**

---

## Stage 2 — WP7: Stage A sweep (26 configs × 238 queries)

**Preconditions:** WP6 committed; user confirmed `<PV>`; `python -m bm25tune
budget` output pasted into chat. Budget (§6.2b): ≈10–13k unique pairs → **≈$2.05
typical / $3.58 worst**; ~2–3.5 h judging at concurrency 16.
Fix `RUN_A=$(date -u +%Y%m%dT%H%M%S)-stageA`.

### 2.1 Search sweep (no spend)
```bash
export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"
export BM25_TUNE_INDEX_DIR=<chunked BM25 index dir>
uv run --project tasks/bm25_tune python -m bm25tune verify-inputs
uv run --project tasks/bm25_tune python -m bm25tune search-sweep --stage A --run-id "$RUN_A" \
  2>&1 | tee /tmp/bm25-tune-sweep-stageA.log
```
Verify: 26 files under `runs/$RUN_A/trecruns/`; `pool.jsonl`+`pool-texts.jsonl`;
`[POOL]` unique pairs ~10–13k, inflation ~1.7–2.2× (else stop before judging).

### 2.2 Pilot judge line (💰 metered, small — needs prior WP7 authorization)
```bash
export BM25_TUNE_BUDGET_USD=50.0   # + fresh SSO creds; AWS_REGION=ap-southeast-2
uv run --project tasks/bm25_tune python -m bm25tune judge-pool \
  --run-id "$RUN_A" --prompt-version <PV> --pilot 200 \
  2>&1 | tee /tmp/bm25-tune-judge-stageA-pilot.log
```
Stops by design after 200. **⛔ STOP: paste the `[COST]`/pilot-basis + `[BUDGET]`
preflight lines into chat and get the full run explicitly authorized.**

### 2.3 Full Stage-A judging (💰 ≈$2, ~2–3.5 h — only after 2.2 authorization)
Launch as a tracked background task, full command printed verbatim in chat:
```bash
JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm" \
BM25_TUNE_INDEX_DIR=... BM25_TUNE_JUDGE_REGION=ap-southeast-2 BM25_TUNE_BUDGET_USD=50.0 \
uv run --project tasks/bm25_tune python -m bm25tune judge-pool \
  --run-id "$RUN_A" --prompt-version <PV> \
  2>&1 | tee /tmp/bm25-tune-judge-stageA.log
```
`tail -f`; `[HEARTBEAT]` every 60 s. Exit 3 = refresh SSO + re-run (free resume).
Exit 5 = **stop and escalate** (a trip at this cap is a bug). Exit 130/143 =
drained; re-run resumes. Verify: `[SUMMARY]`, parse-fail < 1 %, manifest cost
block.

### 2.4 Score + cost report (no spend)
```bash
uv run --project tasks/bm25_tune python -m bm25tune score --run-id "$RUN_A" --prompt-version <PV>
uv run --project tasks/bm25_tune python -m bm25tune cost-report --run-id "$RUN_A"
uv run --project tasks/bm25_tune python -m bm25tune budget
```
Verify: `scores.*` present, 26 cells, secondaries labeled exploratory, no
`judged@10 dips`, reconciliation clean. **⛔ STOP: present the Stage-A matrix and
get the top-3 cells confirmed** (ranked by mean `ndcg10_exp`; user confirms).

---

## Stage 3 — WP8: Stage B + statistics

**Preconditions:** user-confirmed top-3 `<C1>,<C2>,<C3>`; budget pasted. Frame:
~25–30k unique pairs, ~10–13k already cached (topic-level `jkey` reuse) →
**~15–22k new ≈ $3.47 typical / $6.05 worst**, ~2.5–4 h.
`RUN_B=$(date -u +%Y%m%dT%H%M%S)-stageB`.

### 3.1 Search (no spend)
```bash
uv run --project tasks/bm25_tune python -m bm25tune search-sweep --stage B --run-id "$RUN_B" \
  --configs <C1>,<C2>,<C3>,0.9:0.4 \
  2>&1 | tee /tmp/bm25-tune-sweep-stageB.log
```
Stage B has **no default configs** — baseline `0.9:0.4` must be listed. Full 1063
set. Verify 4 run files + pool.

### 3.2 Pilot then full (💰; same two-step authorization as WP7)
Pilot 200 → **⛔ STOP, paste basis + cache-hit delta, authorize** → full
`judge-pool` as tracked background task. Same exit-code runbook as 2.3.

### 3.3 Score + stats + cost (no spend)
```bash
uv run --project tasks/bm25_tune python -m bm25tune score --run-id "$RUN_B" --prompt-version <PV>
uv run --project tasks/bm25_tune python -m bm25tune stats --run-id "$RUN_B" --prompt-version <PV>
uv run --project tasks/bm25_tune python -m bm25tune cost-report
```
`stats` implements §6.4: paired t + Wilcoxon on held-out 825 (set difference vs
persisted `subsample-250.jsonl`), Bonferroni α=0.05/3, bootstrap CI 10k seed 13,
topic-level robustness (headline), full-1063 descriptive labeled as such. Warns
if candidate count ≠ 3. Verify `stats.json` + `[SUMMARY]` + manifest update.

### 3.4 Optional umbrela-v1 continuity (💰 ≈$2; §6.2 default is Stage-A-only)
**⛔ User's call with the cost line.** If authorized: `judge-pool --run-id
"$RUN_A" --prompt-version umbrela-v1` (pilot first), then `score`. Same for any
§6.2b extra — each needs its own go-ahead.

---

## Stage 4 — WP9: documentation and publication (no spend)

1. **`tasks/bm25_tune/README.md`** (new) — §7.1 checklist: purpose + one-para
   result; JDK/pyserini setup incl. `JAVA_HOME` + `pyserini.__version__` gotcha;
   env-var block + every subcommand w/ example; artifact map (§4.2); resume +
   full exit-code table (must match `cli.py`); budget/cost section (no-default
   cap, `budget`, rate table, log→ledger→totals→costs.md chain,
   $0.158/1000-judgments, "a `[BUDGET]` trip means investigate a bug"); log-prefix
   grep table; gotchas (maxTokens=1024, bare model id, block-iteration parsing,
   no mid-batch `set_bm25`, 9.4 s cold start, read-only index); metric conventions
   (§5.5) + the §3.4 honesty paragraph **verbatim**.
2. **Worklog** `worklogs/2026-XX-XX-bm25-tune-sweep.md` — self-contained per
   CLAUDE.md: verbatim 5 prompt texts; query provenance (file, sha256, counts,
   seeds); calibration matrix; **full** Stage-A matrix; Stage-B results w/ effect
   sizes/CIs; complete cost accounting (§6.2b actuals vs estimates, rate id,
   cache savings, wasted spend, total vs $50). Copy sweep logs + `costs.md` into
   `worklogs/assets/`.
3. **`tasks/bm25_tune/scripts/publish_results.py`** (new, mirrors
   `scripts/publish-ragdoll-results.py`) → `evaluation-results/bm25-tune/<run_id>/`:
   manifest, calibration-report, scores.*, stats.json, TREC qrels per PV,
   costs.*, dated `prices/` table, README noting raw judge logs excluded.
4. **`CLAUDE.md` Active Tasks** — update the existing entry (~line 317) with the
   outcome (winning k1/b, PV, results location).
5. Final `bash scripts/test.sh` green + skip-free; final commit w/ co-author line.
   **⛔ STOP:** user reviews before any merge/PR.

---

## Spend ledger (every point real money moves, all user-gated)

| step | ≈ cost | gate |
|---|---|---|
| user-run `calibrate` (end WP6) | $0.23–0.40 | user runs it personally; §1.4 |
| WP7 pilot (200) | ~$0.03–0.08 | WP7 authorized after `<PV>` confirmed |
| WP7 full Stage-A judge | $2.05–3.58 | pilot `[COST]` pasted → go-ahead |
| WP8 pilot | ~$0.03–0.08 | top-3 cells confirmed |
| WP8 full Stage-B judge | $3.47–6.05 | pilot pasted → go-ahead |
| optional continuity/extras | $2 / up to $21 | each individually w/ cost line |

`search-sweep`, `score`, `stats`, `cost-report`, `budget`, `rebuild-cache` and the
entire test suite are structurally spend-free.
