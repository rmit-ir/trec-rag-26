"""`calibrate` end to end: five variants, one gate, one report — no spend.

`test_calibration.py` pins the pure gate/decision/report module against synthetic
distributions, and `test_cli.py` drives the metered `judge-pool` path. Neither
touches the *seam between them*: `cmd_calibrate` persists a sample, threads one
shared meter through five `JudgePoolDriver` runs plus a cache-bypassing probe,
reads the grades back out of the snapshots, and turns the decision into an exit
code. Every one of those joins is only exercised the first time someone runs
`calibrate` for real — which, by design, spends money. So this file drives
`cli.main(["calibrate", ...])` with the *same* two-fake discipline as
`test_cli.py` (real argparse, real Config/log/cache/meter; only the Bedrock
transport faked) and proves the whole thing offline, before the ~$0.23 human run.

It is a **sibling** of `test_cli.py` rather than an addition to it: cross-file
imports between test modules are fragile under `--import-mode=importlib`, and
calibration needs no `_FakeLucene` at all — it reads the historical passage text
straight out of `ObservedHit.text`, never the index. The one thing this file does
differently from `test_cli.py` is the grade: it is keyed on the **passage text**,
not the prompt digest, so a chosen grade distribution lands identically across all
five variants (the passage fills every variant's `{p}` slot verbatim) and the gate
verdict is a property of the test, not of a hash.

What it defends, in order of what it costs to get wrong:

1. **Each (variant, pair) is billed exactly once, and a re-run is free.** Five
   variants over the same persisted sample must be 5×N calls, never N judged five
   times or one variant judged twice; and re-running a finished calibration must
   cost nothing (variant judging is cached — the probe is deliberately not).
2. **The gate is the exit code.** A healthy grade spread → exit 0 and a named
   winner the launcher may (with the user's sign-off) sweep on; a degenerate one
   → exit 6 so the launcher escalates instead of auto-starting the sweep. The
   report is written on *both* paths.
3. **A mid-calibration budget stop is a stop, not a loss.** Exit 5, a partial
   report, and spend equal to exactly the judgments that reached disk.
4. **The report the human reads carries its own caveats.** Both label mixes and
   the three §3.3b warnings travel with the numbers, so the artifact cannot be
   misread in isolation as an accuracy measure or a pool-level share.
"""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Callable

import pytest

from bm25tune import cli, extract, judge, pricing, store
from bm25tune.prompts import all_versions

#: The mini fixture's calibration sample is tiny, so `--n 4` (never 280) and a
#: probe that is off unless a test is specifically about it.
CALIB_N = 4
CALIB_SEED = cli.CALIBRATION_SAMPLE_SEED

#: Deliberately larger than the `PRIOR_MEAN_*` the pre-flight uses, so a cap can
#: clear layer 1 and still be tripped by layer 2 — the only way a mid-run stop is
#: reachable at all (mirrors `test_cli.py`).
IN_TOKENS = 2000
OUT_TOKENS = 800
_RATES = pricing.load_rates("openai.gpt-oss-20b-1:0", "ap-southeast-2",
                            "standard")
#: One fake call's cost at the committed rates — recomputed, never hardcoded, so
#: a rate-table edit moves the arithmetic in step instead of silently breaking it.
CALL_USD = _RATES.call_usd(IN_TOKENS, OUT_TOKENS)
PRIOR_CALL_USD = _RATES.call_usd(pricing.PRIOR_MEAN_INPUT_TOKENS,
                                 pricing.PRIOR_MEAN_OUTPUT_TOKENS)

N_VARIANTS = len(all_versions())


# ---------------------------------------------------------------------------
# The one fake: a Bedrock transport that grades by passage, not by prompt digest
# ---------------------------------------------------------------------------
class _CalibConverse:
    """Injected Converse transport: grade chosen by which passage is in the prompt.

    Modeled on `test_cli.py`'s `_FakeConverse` — records every prompt, emits the
    reasoning block **first** (as measured), carries a large `usage` block — but
    the grade is looked up from `grade_by_chunk` via the passage text, which
    appears verbatim in every variant's `{p}` slot. That is what makes a chosen
    distribution identical across all five variants, so the gate verdict is a
    fact of the test rather than of a hash. `pace`/`hook` are the same optional
    seams the sibling file uses to sync the writer or inject a stop.
    """

    def __init__(self, texts: dict[str, str],
                 grade_by_chunk: dict[str, int]) -> None:
        self._texts = texts
        self.grade_by_chunk = grade_by_chunk
        self.calls: list[str] = []
        self.pace: Callable[[], None] | None = None
        self.hook: Callable[[int, str], None] | None = None

    def _grade_for(self, prompt: str) -> int:
        for chunk_id, text in self._texts.items():
            if text and text in prompt:
                return self.grade_by_chunk[chunk_id]
        raise AssertionError("prompt carries no known calibration passage")

    def __call__(self, **kwargs: object) -> dict:
        if self.pace is not None:
            self.pace()
        messages = kwargs["messages"]  # type: ignore[index]
        prompt = messages[0]["content"][0]["text"]
        self.calls.append(prompt)
        if self.hook is not None:
            self.hook(len(self.calls), prompt)
        grade = self._grade_for(prompt)
        return {
            "output": {"message": {"role": "assistant", "content": [
                {"reasoningContent": {"reasoningText": {"text": "weighing it"}}},
                {"text": f"##final score: {grade}"},
            ]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": IN_TOKENS, "outputTokens": OUT_TOKENS,
                      "totalTokens": IN_TOKENS + OUT_TOKENS},
        }


# ---------------------------------------------------------------------------
# The harness
# ---------------------------------------------------------------------------
class CalibHarness:
    """One tmp calibration: the real CLI over a fake judge, with the ids to check.

    Computes the sampled chunk ids the way `cmd_calibrate` does (rather than
    hardcoding a guess against the fixture) and exposes the PASS/FAIL grade maps
    keyed on those ids, so a fixture change fails a loud assertion here instead of
    silently grading the wrong passages.
    """

    def __init__(self, cfg, converse: _CalibConverse, texts: dict[str, str],
                 sampled_ids: list[str], agent_class: dict[str, str],
                 pass_map: dict[str, int], driver_box: dict) -> None:
        self.cfg = cfg
        self.converse = converse
        self.texts = texts
        self.sampled_ids = sampled_ids
        self.agent_class = agent_class
        self.pass_map = pass_map
        self._driver_box = driver_box

    # -- commands -----------------------------------------------------------
    def calibrate(self, *extra: str) -> int:
        return cli.main(["calibrate", "--n", str(CALIB_N),
                         "--seed", str(CALIB_SEED), "--stability-pairs", "0",
                         "--concurrency", "1", *extra])

    # -- state --------------------------------------------------------------
    @property
    def calibration_dir(self) -> Path:
        return self.cfg.calibration_dir

    def report_json(self) -> dict:
        return json.loads(
            (self.calibration_dir / cli.CALIBRATION_REPORT_JSON).read_text(
                encoding="utf-8"))

    def report_md(self) -> str:
        return (self.calibration_dir / cli.CALIBRATION_REPORT_MD).read_text(
            encoding="utf-8")

    def pace_to_writer(self) -> None:
        """Make each fake call wait for the writer thread — see `test_cli.py`."""
        import time

        def _pace() -> None:
            driver = self._driver_box.get("driver")
            if driver is None:
                return
            deadline = time.monotonic() + 10.0
            while driver._queue.unfinished_tasks and time.monotonic() < deadline:
                time.sleep(0.001)

        self.converse.pace = _pace

    def fail_from(self, index: int, code: str) -> None:
        """Raise a boto3-shaped `code` on the `index`-th call and every one after."""
        def _hook(call_index: int, _prompt: str) -> None:
            if call_index >= index:
                raise _CredError(code)

        self.converse.hook = _hook

    # -- reading what happened ---------------------------------------------
    def log_records(self) -> list[dict]:
        records: list[dict] = []
        for segment in store.iter_segments(self.cfg.log_dir):
            records.extend(store.read_segment(segment).records)
        return records

    def successes(self) -> list[dict]:
        return [r for r in self.log_records() if store.is_success(r)]

    def graded_pairs(self) -> set[tuple[str, str]]:
        """`(prompt_version, chunk_id)` for every successful judgment on disk."""
        return {(str(r["prompt_version"]), str(r["chunk_id"]))
                for r in self.successes()}

    def snapshot_keys(self, prompt_version: str) -> set[str]:
        path = store.cache_snapshot_path(self.cfg.cache_dir, prompt_version)
        keys: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("kind") != store.CACHE_META_KIND:
                keys.add(row["jkey"])
        return keys

    def spent(self) -> float:
        return pricing.CostMeter.load(self.cfg.costs_dir).spent_usd()


class _CredError(Exception):
    """A boto3-shaped error whose `Code` `classify_error` reads off attributes."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code},
                         "ResponseMetadata": {"HTTPStatusCode": 400}}


@pytest.fixture(autouse=True)
def _quiet_logging() -> None:
    """Keep `calibrate`'s re-`setup_logging` (at `calibration/calibrate.log`) from
    muting `caplog` — the `[GATE]` lines these tests assert on must stay visible.
    """
    logging.getLogger().setLevel(logging.INFO)


@pytest.fixture
def calib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
          bm25_config: "object", mini_labeled_path: Path) -> CalibHarness:
    """A tmp calibration wired to the fake Bedrock transport.

    The query file `_topic_context` reads is written from the mini fixture with
    WP1's own loader, so the narratives are the real artifact. The sample is drawn
    exactly as `cmd_calibrate` draws it and its positives/negatives become a PASS
    grade map (all four grades used, positives strictly above negatives → AUC
    1.0). `BedrockJudge`/`JudgePoolDriver` are patched as factories and the driver
    captured, mirroring `test_cli.py`.
    """
    queries = extract.load_keyword_queries(mini_labeled_path)
    extract.write_query_file(
        bm25_config.queries_dir / cli.QUERIES_FULL_BASENAME, queries)

    # `cmd_calibrate` reads the labeled log from `cfg.input_file` (the fixed
    # `INPUT_BASENAME`), not from the fixture's own copy — seed it there.
    bm25_config.input_file.parent.mkdir(parents=True, exist_ok=True)
    bm25_config.input_file.write_bytes(mini_labeled_path.read_bytes())

    hits = extract.load_observed_hits(bm25_config.input_file)
    sample = extract.calibration_sample(hits, n=CALIB_N, seed=CALIB_SEED)
    texts = {h.chunk_id: h.text for h in sample}
    agent_class = {h.chunk_id: h.agent_class for h in sample}
    sampled_ids = [h.chunk_id for h in sample]

    positives = sorted(c for c in sampled_ids
                       if agent_class[c] == "positive")
    negatives = sorted(c for c in sampled_ids
                       if agent_class[c] == "negative")
    assert len(positives) == 2 and len(negatives) == 2, (
        "the PASS map needs exactly two positives and two negatives so all four "
        f"grades are used; fixture gave {agent_class} — update the map if the "
        "fixture changed on purpose")
    # positives -> {3, 2}, negatives -> {1, 0}: modal share 0.25, share>=2 0.50,
    # share=3 0.25, all four grades used, and every positive strictly outranks
    # every negative so the AUC smell test is a clean 1.0. This PASSES the gate.
    pass_map = {positives[0]: 3, positives[1]: 2,
                negatives[0]: 1, negatives[1]: 0}

    converse = _CalibConverse(texts, dict(pass_map))
    real_judge = judge.BedrockJudge

    def _judge_factory(model_id: str, region: str, **kwargs: object):
        return real_judge(model_id, region, converse=converse,
                          sleep=lambda _s: None, rng=random.Random(0), **kwargs)

    monkeypatch.setattr(judge, "BedrockJudge", _judge_factory)

    driver_box: dict = {}
    real_driver = judge.JudgePoolDriver

    def _driver_factory(**kwargs: object):
        driver = real_driver(**kwargs)
        driver_box["driver"] = driver
        return driver

    monkeypatch.setattr(judge, "JudgePoolDriver", _driver_factory)
    return CalibHarness(bm25_config, converse, texts, sampled_ids, agent_class,
                        pass_map, driver_box)


# ---------------------------------------------------------------------------
# Artifacts and billing
# ---------------------------------------------------------------------------
def test_calibrate_writes_the_sample_and_both_reports_and_names_a_winner(
        calib: CalibHarness) -> None:
    """The three artifacts a human then reviews must all appear on a clean pass.

    `cmd_calibrate` is the only producer of `sample-280.jsonl`, `report.md` and
    `report.json`, and the launcher branches on `report.json["winner"]` /
    `["gated"]` without re-parsing the prose. If any of those is missing or the
    winner is not a real prompt version, the human gate has nothing to review and
    a launcher would dereference a null.
    """
    assert calib.calibrate() == cli.EXIT_OK

    sample_path = calib.calibration_dir / cli.CALIBRATION_SAMPLE_BASENAME
    assert sample_path.is_file(), (
        "the sample basename is a constant regardless of --n")
    rows = [json.loads(line) for line in
            sample_path.read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == CALIB_N
    assert {r["chunk_id"] for r in rows} == set(calib.sampled_ids)

    assert (calib.calibration_dir / cli.CALIBRATION_REPORT_MD).is_file()
    report = calib.report_json()
    assert report["gated"] is False
    assert report["winner"] in all_versions()


def test_five_variants_judge_byte_identical_pairs_each_billed_once(
        calib: CalibHarness) -> None:
    """5×N calls, no pair judged twice, spend equal to the calls — the core cost claim.

    Calibration threads one shared meter through five driver runs over the *same*
    persisted sample; the risk is a variant re-judging a pair or a pair leaking
    across variants' caches (topic-level `jkey` embeds the prompt version, so a
    bug there would let one variant's grade satisfy another's cache). Proven from
    the append-only log — the ground truth for spend — not from a counter.
    """
    assert calib.calibrate() == cli.EXIT_OK

    assert len(calib.converse.calls) == N_VARIANTS * CALIB_N, (
        "one call per (variant, pair), no retries and no re-judging")
    graded = calib.graded_pairs()
    assert len(graded) == N_VARIANTS * CALIB_N, "no (variant, pair) billed twice"
    for version in all_versions():
        assert {c for v, c in graded if v == version} == set(calib.sampled_ids), (
            f"{version} must judge exactly the {CALIB_N} sampled pairs")
    assert calib.spent() == pytest.approx(
        N_VARIANTS * CALIB_N * CALL_USD, rel=1e-6)


def test_a_finished_calibration_re_run_makes_no_further_call_or_spend(
        calib: CalibHarness) -> None:
    """Re-running a completed `calibrate` is free — variant judging is cached.

    Resume is "re-run the same command", so a launcher that retries or a human who
    lost the terminal must not re-pay for the whole sample five times over. Both
    runs keep the probe **off**: the probe is cache-bypassing by design, so the
    zero-spend property is a claim about variant judging only — a run with the
    probe on would (correctly) cost the probe's calls again.
    """
    assert calib.calibrate() == cli.EXIT_OK
    calls, spent = len(calib.converse.calls), calib.spent()

    assert calib.calibrate() == cli.EXIT_OK
    assert len(calib.converse.calls) == calls, "a cached re-run calls nobody"
    assert calib.spent() == spent


# ---------------------------------------------------------------------------
# The gate is the exit code
# ---------------------------------------------------------------------------
def test_a_healthy_grade_spread_passes_the_gate_and_recommends_a_judge(
        calib: CalibHarness, caplog: pytest.LogCaptureFixture) -> None:
    """Exit 0 with a `[GATE] PASS` line and every variant listed under `passing`.

    The PASS map is identical across variants, so all five clear the four bounds;
    the launcher's go/no-go is `report.json`, and the operator's live signal is
    the `[GATE] PASS — recommended judge:` line, so both are asserted here.
    """
    with caplog.at_level("INFO"):
        assert calib.calibrate() == cli.EXIT_OK
    assert "[GATE] PASS — recommended judge:" in caplog.text

    report = calib.report_json()
    assert set(report["passing"]) == set(all_versions()), (
        "byte-identical passing grades must pass the gate for every variant")
    assert report["winner"] in report["passing"]


def test_a_degenerate_distribution_gates_the_run_and_still_writes_the_report(
        calib: CalibHarness, caplog: pytest.LogCaptureFixture) -> None:
    """Every pair graded 2 → exit 6, and the report the user escalates with exists.

    A one-grade judge fails modal share, all-grades-used, and the share>=2 ceiling
    at once. The whole point of the gate is that the launcher must NOT auto-start
    the sweep here — exit 6 forces the escalation — but the human still needs the
    artifact, so it is written on the gated path too.
    """
    calib.converse.grade_by_chunk = {c: 2 for c in calib.sampled_ids}

    with caplog.at_level("ERROR"):
        assert calib.calibrate() == cli.EXIT_GATE_FAILED
    assert "[GATE] no variant passed" in caplog.text

    report = calib.report_json()
    assert report["gated"] is True
    assert report["winner"] is None
    assert report["best_effort"] in all_versions()
    assert (calib.calibration_dir / cli.CALIBRATION_REPORT_MD).is_file()


# ---------------------------------------------------------------------------
# The stability probe (cache-bypassing)
# ---------------------------------------------------------------------------
def test_the_stability_probe_re_judges_the_winner_bypassing_the_cache(
        calib: CalibHarness) -> None:
    """The probe's calls are extra, staged apart, and never seed the winner's qrels.

    A cache hit would trivially report 1.000, so the probe runs against a fresh
    empty cache under `stage="calib-probe"` and `snapshot_path=None`. That is what
    is checked: the probe adds exactly its own calls, its records carry the probe
    stage and the winner's version, and the winner's committed qrels snapshot is
    untouched (still the N sampled pairs).
    """
    probe_pairs = 2
    assert calib.calibrate("--stability-pairs", str(probe_pairs)) == cli.EXIT_OK

    assert len(calib.converse.calls) == N_VARIANTS * CALIB_N + probe_pairs
    report = calib.report_json()
    winner = report["winner"]
    probe_records = [r for r in calib.successes()
                     if r.get("stage") == "calib-probe"]
    assert len(probe_records) == probe_pairs
    assert {r["prompt_version"] for r in probe_records} == {winner}

    entries = {v["prompt_version"]: v for v in report["variants"]}
    assert entries[winner]["stability_pairs"] == probe_pairs
    assert entries[winner]["stability_match_rate"] == pytest.approx(1.0)
    for version, entry in entries.items():
        if version != winner:
            assert entry["stability_match_rate"] is None, (
                "the probe covers the gate-passing winner only")
    assert len(calib.snapshot_keys(winner)) == CALIB_N, (
        "the probe must not seed the winner's committed qrels")


# ---------------------------------------------------------------------------
# A mid-calibration budget stop
# ---------------------------------------------------------------------------
def _cap_that_passes_preflight_but_trips_after_the_first_judgment(
        pairs: int) -> float:
    """A cap layer 1 approves for `pairs`, that layer 2 trips on judgment one.

    Same *idea* as `test_cli.py`'s helper — sit the cap between the pre-flight's
    priors-based estimate and the real spend — but tightened for a variant of only
    four pairs. `test_cli.py` has a large pool, so the midpoint of estimate and
    real cost trips comfortably mid-run; here, with the bounded in-flight window,
    a midpoint cap admits all four before the trip lands, leaving the stop between
    variants instead of inside one. So the cap is placed below the two-call
    threshold: the pre-flight for `pairs` (which uses `PRIOR_MEAN_*`) still clears
    it, but the writer trips once it has metered a single real call plus its
    reserve — abandoning the rest of variant one. Computed from the rate table so
    a rate/prior change re-derives it or trips the assertion, never silently
    becoming an exit-4 preflight refusal (a different path with no report).
    """
    preflight_estimate = pairs * PRIOR_CALL_USD
    # The writer trips when `spent + reserve >= cap`; after one metered call both
    # `spent` and the single-worker `reserve` are one `CALL_USD`, so any cap below
    # `2·CALL_USD` trips on judgment one.
    two_call_trip = 2 * CALL_USD
    assert preflight_estimate < two_call_trip, (
        "the priors-based estimate for the whole variant must be cheaper than "
        "two real calls, or no cap can both clear preflight and trip this early")
    return preflight_estimate + (two_call_trip - preflight_estimate) / 2.0


def test_a_midrun_budget_trip_exits_five_and_writes_a_partial_report(
        calib: CalibHarness, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """Exit 5 mid-calibration: a stop, with a partial report and honest spend.

    A cap tripping inside the first variant is *not* a gate failure — it is the
    driver's budget stop, so `calibrate` must propagate exit 5 (resume re-runs the
    same command) rather than exit 6, and still write what it has. The cap is set
    to admit at least one judgment (`_variant_result` on zero grades raises), so
    the partial report has a variant to describe; the trip is layer-2, not a
    per-variant preflight refusal (which would be exit 4 with no report).
    """
    cap = _cap_that_passes_preflight_but_trips_after_the_first_judgment(CALIB_N)
    monkeypatch.setenv("BM25_TUNE_BUDGET_USD", repr(cap))
    calib.pace_to_writer()

    with caplog.at_level("INFO"):
        assert calib.calibrate() == cli.EXIT_BUDGET_STOP
    assert "HARD STOP" in caplog.text

    successes = calib.successes()
    assert 0 < len(successes) < CALIB_N, (
        "the stop must land inside the first variant, or it proves nothing")
    first_variant = all_versions()[0]
    assert {r["prompt_version"] for r in successes} == {first_variant}
    assert {r["chunk_id"] for r in successes} <= set(calib.sampled_ids)
    assert calib.spent() == pytest.approx(len(successes) * CALL_USD, rel=1e-6)

    report = calib.report_json()
    assert len(report["variants"]) >= 1
    assert (calib.calibration_dir / cli.CALIBRATION_REPORT_MD).is_file()


# ---------------------------------------------------------------------------
# The report carries its own caveats
# ---------------------------------------------------------------------------
def test_the_report_carries_both_label_mixes_and_the_caveats(
        calib: CalibHarness) -> None:
    """The artifact must be un-misreadable in isolation (PLAN §3.3b).

    A reader who opens only `report.md` must not be able to read the agent-label
    cross-tab as accuracy, nor compare the sample's share>=2 to the pool's. So the
    three preamble warnings and both label mixes travel *inside* the report, and
    `report.json` carries the machine-readable pool mix a launcher would compare.
    """
    assert calib.calibrate() == cli.EXIT_OK
    md = calib.report_md()

    assert "sample label mix" in md
    assert "pool label mix" in md
    for caveat in ("floor on usability, not the selection criterion",
                   "smell test, not accuracy",
                   "deliberately not the pool"):
        assert caveat in md, f"missing §3.3b caveat: {caveat!r}"

    from bm25tune import calibration as calib_mod
    assert calib.report_json()["pool_label_mix"] == calib_mod.POOL_LABEL_MIX


# ---------------------------------------------------------------------------
# Resume across a credential expiry (cheap, high value)
# ---------------------------------------------------------------------------
def test_a_cred_expiry_mid_calibration_resumes_without_re_billing(
        calib: CalibHarness, caplog: pytest.LogCaptureFixture) -> None:
    """Exit 3, then the same command finishes without paying for a pair twice.

    An expired SSO token is the most likely interruption; the documented recovery
    is to refresh and re-issue the identical command. That is only sound if the
    second run re-bills nothing already on disk — asserted by counting the unique
    (variant, pair) judgments in the append-only log and the total spend, which
    together can only equal 5×N once if no pair was paid for twice.
    """
    calib.pace_to_writer()
    calib.fail_from(3, "ExpiredTokenException")
    with caplog.at_level("ERROR"):
        assert calib.calibrate() == cli.EXIT_CRED_EXPIRY
    assert "[CRED]" in caplog.text
    first = calib.graded_pairs()
    assert 0 < len(first) < N_VARIANTS * CALIB_N, "the stop must land part-way"

    calib.converse.hook = None
    caplog.clear()
    assert calib.calibrate() == cli.EXIT_OK
    graded = calib.graded_pairs()
    assert len(graded) == N_VARIANTS * CALIB_N, (
        "every (variant, pair) judged exactly once across both runs")
    assert first <= graded, "the first run's judgments must survive the resume"
    assert calib.spent() == pytest.approx(
        N_VARIANTS * CALIB_N * CALL_USD, rel=1e-6)
