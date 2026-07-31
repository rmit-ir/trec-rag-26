# BM25 tune harness — session handoff (WP6 calibrate driver + remaining WPs)

**Written 2026-07-31.** This is a self-contained resume point. Read it, then read
`tasks/bm25_tune/PLAN.md` for the full design. Branch: **`feat/bm25-tune`**
(cut from `origin/main`; the earlier `feat/systems-test-harness` was a stale
merged branch — do NOT build on it).

---

## Non-negotiable constraints (carried across every session)

1. **Local pyserini, not the hosted server.** The hosted BM25 server can't take
   `k1`/`b`, so tuning runs local pyserini against the local chunked index,
   read-only, under `BM25_TUNE_INDEX_DIR`.
2. **Keyword queries only** (aus_agent's — 1063 unique pairs). Never narrative
   queries for the sweep itself. (Prompt *variants* may put narrative or keyword
   in `{q}` — that's a judge-target question, separate from the retrieval query.)
3. **Judge = `gpt-oss-20b` on Bedrock** (`openai.gpt-oss-20b-1:0`, bare id,
   region `ap-southeast-2`), graded **0–3**, parsed from `##final score: <0-3>`.
   gpt-oss-20b emits `reasoningContent` before `text`; `maxTokens=1024`.
4. **Cache every (query,doc) pair on disk** so a pair is never re-judged.
   Cache key `jkey = prompt_version::topic_id::chunk_id` (topic-level).
5. **Optimize nDCG@10**; graded + binary P@10 computed and persisted in the same
   pass.
6. **$50 hard budget cap, a REQUIRED operator input** (`BM25_TUNE_BUDGET_USD`,
   **no default anywhere in code**). `APPROVED_BUDGET_USD=50.0` appears only in
   the "you must export this" message string.
7. **Costs recorded/stored** for the paper's cost analysis.
8. **Checkpoints**; resume = "re-run the same command".
9. **WP0/WP6 judge calibration is a MANDATORY gate before ANY sweep spend.**
10. **NO Bedrock spend beyond WP3's one validation call ($0.00005525) until the
    user reviews WP6's `calibration/report.md` and confirms the prompt version.**
11. Judge calibration must respect that most collection docs are not relevant and
    only very few earn grade 3 — but must not be too harsh (would be useless).
12. **Process discipline: Fable writes the plan → user reviews → default-model
    agents execute.**
13. `uv` per-task env. JAVA_HOME the tests need:
    `export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"`.
    Run tests with dep groups:
    `DEP_GROUPS="--group dev --group o3-deep-research --group aus-agent"; uv run $DEP_GROUPS pytest …`
    or `bash scripts/test.sh`. The suite is skip-free and FAILS on any skip.

---

## What is DONE and committed (branch `feat/bm25-tune`)

- WP1 scaffolding: `config.py`, `prompts.py`, `extract.py`, CLI skeleton.
- WP2–WP4: `searcher.py`, `pool.py`, `judge.py`, `pricing.py` (metering + $50
  ceiling), `metrics.py`, `stats.py`.
- WP5: end-to-end CLI tests (`tests/bm25_tune/test_cli.py`) — resume, budget
  stop, `--fresh`, drain.
- WP6 **offline core** (commit `c9bf8bf`): `bm25tune/calibration.py` — pure
  gate/decision/report module + `tests/bm25_tune/test_calibration.py` (30 tests).
- Required `$50` cap with no default; top-10 measures; two-sided judge gate;
  WP0 gate widened from the hand-graded read of 22 real hits.

## WP6 is now DONE (calibrate driver + offline tests, committed)

- **`tasks/bm25_tune/bm25tune/cli.py`** — the WP6 **spend-half** `cmd_calibrate`
  and its helpers are committed. The three prior-session bugs were fixed
  (`Counter`/`Mapping` imports; dead `and False` removed; parse-failure predicate
  `record.get("error") == "parse_failure"`). `STUBS` is now empty (`calibrate`
  was the last stub) — kept as an extension point, not deleted.
- **`tests/bm25_tune/test_cli_calibrate.py`** (new) — 9 offline cases driving
  `cli.main(["calibrate", …])` over the `--n 4 --seed 7` mini sample (2 pos / 2
  neg): artifacts, 5×N per-pair billing, cache-free re-run, gate PASS→0 /
  FAIL→6, cache-bypassing stability probe, layer-2 budget stop→5 + partial
  report, both label mixes + §3.3b caveats, cred-expiry resume.
- Two consequential fixes surfaced by the full suite (in the commit):
  `[CALIB]`/`[GATE]` added to `logging_setup.LOG_PREFIXES` (the grep contract;
  count 17→19), and `test_cli_wp1.py`'s empty-`STUBS` parametrize (a forbidden
  skip) rewritten as a loop.
- Full suite: **1467 passed, skip-free**.

### ⛔ IMMEDIATE next step is the HUMAN GATE — do not run calibrate yourself

The user runs `calibrate` against real Bedrock (~$0.23), reviews
`data/bm25-tune/calibration/report.md`, and confirms the prompt version **in
writing** before any WP7 sweep spend. The exact command is in
`NEXT-STAGES-PLAN.md` §1.4.

### The calibrate implementation (already in cli.py, verified against source)

Helpers, in order in the file: `_calibration_pairs` (persists
`calibration/sample-280.jsonl` via `extract.calibration_sample`, builds
`JudgePair`s from the sample + topic narratives, returns
`(pairs, agent_class_by_chunk, sample_path)`); `_judge_variant` (one variant
through the audited `JudgePoolDriver`, shared metered `CostMeter`,
`stage="calib"`); `_variant_result` (reads grades back from the cache snapshot →
`VariantResult`); `_variant_cost_from_log` (sums calls/tokens/cost/parse-failures
from the log via `pricing.iter_log_records`, filtered to `stage=="calib"`);
`_stability_probe` (cache-bypassing re-judge of the winner, `stage="calib-probe"`,
fresh empty `JudgmentCache`, ≥90% match target); `cmd_calibrate` (pricing→cap→
judge all 5 variants→`calib.decide`→probe winner→write report→exit 6 on gate
fail); `_write_calibration_report` (renders `report.md` + `report.json`).
Subparser `calibrate` wired with `--n`/`--seed`/`--stability-pairs`/
`--concurrency`/`--queries`/`--fresh`. `--log-file`/`--verbose` are top-level.

Constants already in cli.py: `CALIBRATION_SAMPLE_BASENAME="sample-280.jsonl"`,
`CALIBRATION_REPORT_MD/JSON`, `CALIBRATION_LOG_BASENAME="calibrate.log"`,
`CALIBRATION_SAMPLE_N=280`, `CALIBRATION_SAMPLE_SEED=7`, `CALIBRATION_STAGE="calib"`.

---

## IMMEDIATE next step (finish WP6, no spend)

1. **Write offline `calibrate` CLI tests** in `tests/bm25_tune/test_cli.py`
   (or a sibling `test_cli_calibrate.py`) using the existing `Harness` pattern:
   `_FakeConverse` (Bedrock transport, reasoning-block-first envelope) + the
   `judge.BedrockJudge`/`judge.JudgePoolDriver` monkeypatched factories. **No
   `_FakeLucene` needed** — calibration reads historical hit text from the
   labeled input (`ObservedHit.text`), never the index. Cover:
   - `calibrate` writes `calibration/sample-280.jsonl`, `report.md`, `report.json`.
   - All 5 variants judged on byte-identical pairs; each pair billed once;
     re-run is a full cache hit (zero further calls/spend).
   - Grades drive the gate → a green run returns `EXIT_OK` and names a winner;
     construct fake grades that FAIL the gate → returns `EXIT_GATE_FAILED` (6)
     and still writes the report.
   - Stability probe re-judges the winner cache-bypassing (extra calls appear
     under `stage="calib-probe"`), match rate recorded.
   - A mid-calibration budget stop returns 5 and writes a partial report.
   - `report.md` carries both label mixes (sample vs `POOL_LABEL_MIX`), the
     §3.3b caveats, and never presents agent-label agreement as accuracy
     (calibration.py's REPORT_PREAMBLE already does this — just assert it).
   - **The mini fixture has only 6 rows / 2 topics.** Use small `--n` and
     `--stability-pairs` (e.g. `--n 4 --stability-pairs 2`) so the sampler has
     enough; do not assume 280 pairs exist in tests.
2. **Run the full suite** (the reason: `cli.py` is a shared layer):
   `export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm" && bash scripts/test.sh`.
   Must be green and skip-free.
3. **Commit** on `feat/bm25-tune` (e.g.
   `feat(bm25_tune): WP6 calibrate driver — 5-variant judging, gate, report`).
   Co-author line per repo convention.
4. **STOP for the user.** The user must run `calibrate` for real, review
   `calibration/report.md`, and confirm the prompt version. **No sweep spend
   until then.** (This is why the calibrate tests must be fully offline.)

---

## Later WPs (after user confirms the judge)

- **WP7 — Stage A sweep.** 5×5 grid + baseline = 26 configs over the
  subsample-250 query set (238 rows). `search-sweep --stage A` → pool → 
  `judge-pool` (metered, cached) → `score`. Pilot line first (PLAN §5.7), get
  the full run authorized before launching. Budget arithmetic in PLAN §6.2b.
- **WP8 — Stage B + statistics.** Best cell(s) on the full-1063 held-out queries;
  significance testing (PLAN §6.4). `stats.py` already exists.
- **WP9 — docs.** `tasks/bm25_tune/README.md` (PLAN §7.1 required contents),
  worklog (self-contained down to raw inputs per CLAUDE.md), CLAUDE.md update.

---

## Key API reference (all verified against source this session)

- `extract.calibration_sample(hits, n=280, seed=7)` — stratified by agent label.
  `extract.load_observed_hits(cfg.input_file)`; `ObservedHit.text` (prefix-
  stripped), `.agent_class` ∈ {positive,negative,unjudged}, `.chunk_id`,
  `.topic_id`, `.to_json()`. `extract.write_jsonl(path, records)->int` (atomic).
- `calibration.evaluate_gate(counts)->GateResult` (attrs: `passed`, `counts`,
  `modal_grade/share`, `share_ge2/eq3`, `entropy`, `failures`, `failed_names()`,
  `distance_from_band()`); `decide(results)->Decision` (`winner`, `best_effort`,
  `gated`, `passing`, `ranked`, `rationale`); `render_report_md(...)`;
  `gate_log_lines(r)`; `counts_from_grades`; `agent_agreement`; `POOL_LABEL_MIX`;
  `STABILITY_PROBE_PAIRS` (=50), `STABILITY_MIN_MATCH_RATE` (=0.90);
  `VariantResult(prompt_version, gate, agreement, counts_by_class={}, …,
  stability_match_rate=None, stability_pairs=0)` with `.pool_share_ge2`.
- Gate constants: `GATE_MAX_MODAL_SHARE=0.60`, `GATE_MIN_SHARE_GE2=0.20`,
  `GATE_MAX_SHARE_GE2=0.90`, `GATE_MAX_SHARE_EQ3=0.50`. Bounds inclusive; cond
  3–4 two-sided; exit 6 on gate failure.
- `judge.JudgePair(topic_id, chunk_id, narrative, keyword, passage_text)`;
  `pending_pairs(pairs, cache, pv)->(pending, hits)`; `sample_pairs(pairs, n,
  seed=13)`; `BedrockJudge(model_id, region, …)`; `load_pricing()`;
  `JudgePoolDriver(*, judge, spec, log_store, cache, meter, guard, rates,
  pricing_mod, run_id, stage, concurrency=16, snapshot_path=None, run_dir=None)`;
  `.install_signal_handlers()/.restore_signal_handlers()/.run(pairs)->int`,
  `.usages/.stats/.cache`. `ERROR_PARSE="parse_failure"`.
- `store.jkey(pv, topic, chunk)`; `JudgmentCache.load(log_dir, *,
  prompt_version=, snapshot_path=)`, `.get(key)`, `JudgmentCache(prompt_version=)`;
  `JudgmentLog(log_dir)`; `cache_snapshot_path(cache_dir, pv)`;
  `rename_superseded(target, *, log_dir, costs_dir)`; `KIND_JUDGMENT="judgment"`,
  `KIND_ATTEMPT_ERROR="attempt_error"` (a `parse_failure` record has
  `kind=attempt_error`, `error="parse_failure"`); `is_success(record)`.
- `pricing.iter_log_records(log_dir)` yields every log record;
  `CostMeter.load(costs_dir)/.reconcile(log_dir)/.spent_usd()`;
  `BudgetGuard(meter, cap_usd, concurrency, *, rates=)/.preflight(est, stage=)`.
- `prompts.CALIBRATION_ORDER = ("umbrela-v1","umbrela-kw-v1","facet-v1",
  "facet-name-v1","facet-rare3-v1")`; `all_versions()`, `get_prompt(v)`;
  `DEFAULT_PROMPT_VERSION="facet-v1"`. `PromptSpec.query_slot/.emits_facet/
  .template_sha256/.version_id`.
- Exit codes: `OK=0, ERROR=1, NOT_IMPLEMENTED=2, CRED_EXPIRY=3,
  BUDGET_PREFLIGHT=4, BUDGET_STOP=5, GATE_FAILED=6, SIGINT=130, SIGTERM=143`.

## Test wiring (`tests/bm25_tune/conftest.py`)

Fixtures: `mini_labeled_path` (6-row fixture, 2 topics), `bm25_config` (Config on
a tmp data dir seeded with the mini input; exports `BM25_TUNE_BUDGET_USD=50.0`),
`write_sha256sums`. No dep group needed — bm25tune is stdlib-only at import time
(pyserini/boto3 imported inside functions). Root autouse fixtures apply:
`no_network`, `no_ambient_creds`, `isolated_data_dir`.
