"""What WP1's CLI surface defends: the experiment's anchor to its input.

The labeled search log originally lived in `/tmp`. Everything downstream — the
query set, the qrels, the cached judgments, the published run ids — refers to one
specific 47 MB file, and `verify-inputs` is the only thing that proves the file on
disk is still that one (PLAN R8). So the two properties tested here are:

1. **A changed input is loud and fatal.** Both a checksum mismatch and a
   row-count mismatch must fail. The plan is explicit that the response is to
   STOP, never to relax an expectation — a "fixed" assertion would let the
   experiment continue against a different corpus while every artifact kept
   claiming provenance from the old one.
2. **`extract-queries` output is durable and reproducible.** It writes the files
   later stages *read* instead of re-deriving, so it must not clobber an existing
   set silently, and re-running must produce identical bytes.

Also covered: the exit-code contract (a launching agent branches on these rather
than parsing logs, PLAN §5.7) and the stubs, which must fail with a sentence
naming their work package rather than an ImportError.

Everything here runs against a tmp data dir seeded with the 6-row fixture, so no
test can touch the real `data/bm25-tune/`.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

import pytest

from bm25tune import cli
from bm25tune.cli import (EXIT_ERROR, EXIT_NOT_IMPLEMENTED, EXIT_OK,
                          EXPECTED_INPUT, build_parser, main)
from bm25tune.config import Config


@pytest.fixture(autouse=True)
def _quiet_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep `main()`'s logging setup from re-adding handlers to the root logger.

    `setup_logging` is idempotent for its own handlers, but pytest's `caplog`
    attaches to the root logger too; pinning the level here keeps the captured
    output readable without suppressing the ERROR lines the tests assert on.
    """
    logging.getLogger().setLevel(logging.INFO)


def _run(args: list[str], data_dir: Path,
         monkeypatch: pytest.MonkeyPatch) -> int:
    """Invoke `main()` with `BM25_TUNE_DATA_DIR` pointed at a tmp dir."""
    monkeypatch.setenv("BM25_TUNE_DATA_DIR", str(data_dir))
    return main(args)


@pytest.fixture
def seeded_data_dir(tmp_path: Path, mini_labeled_path: Path,
                    write_sha256sums: Callable[[Path], Path]) -> Path:
    """A tmp data dir holding the fixture under the real input's filename.

    Named as the real input (`trec-rag26-test119-search-labeled.jsonl`) because
    `Config.input_file` is what the CLI resolves — the point is to exercise the
    real path-resolution code, not to bypass it.
    """
    inputs = tmp_path / "inputs"
    inputs.mkdir(parents=True)
    target = inputs / "trec-rag26-test119-search-labeled.jsonl"
    target.write_bytes(mini_labeled_path.read_bytes())
    write_sha256sums(target)
    return tmp_path


# ---------------------------------------------------------------------------
# verify-inputs
# ---------------------------------------------------------------------------
def test_verify_inputs_fails_on_a_checksum_mismatch(
        seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """A file whose bytes changed must fail, with the STOP instruction logged.

    This is the check that catches a re-exported, re-chunked, or truncated input.
    Passing it while the bytes differ would mean every cached judgment silently
    refers to text that is no longer there.
    """
    target = (seeded_data_dir / "inputs" /
              "trec-rag26-test119-search-labeled.jsonl")
    target.write_bytes(target.read_bytes() + b'{"engine": "semantic"}\n')
    with caplog.at_level(logging.INFO):
        code = _run(["verify-inputs"], seeded_data_dir, monkeypatch)
    assert code == EXIT_ERROR
    assert "sha256(file)" in caplog.text
    assert "Do not relax an expectation" in caplog.text


def test_verify_inputs_fails_on_a_row_count_mismatch(
        seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """The count assertions must fire independently of the checksum.

    The fixture is only 6 rows, so a self-consistent inputs dir built from it has
    a *valid* checksum and wrong counts — which is exactly the case a
    checksum-only check would wave through. Both layers are needed: the checksum
    catches a changed file, the counts catch a file that is internally different
    from the one the plan measured.
    """
    with caplog.at_level(logging.INFO):
        code = _run(["verify-inputs"], seeded_data_dir, monkeypatch)
    assert code == EXIT_ERROR
    assert "sha256(file): expected" in caplog.text
    # The count checks reported the fixture's real numbers, not the plan's.
    assert "total_rows: expected 2143 got 6" in caplog.text
    assert "unique_pairs: expected 1063 got 3" in caplog.text


def test_verify_inputs_reports_every_check_not_just_the_first_failure(
        seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """All checks run and are recorded, so one investigation sees the whole picture.

    Short-circuiting on the first failure would send an operator chasing a
    checksum when the real story is "this is a different export" — visible only
    from the pattern across all twelve checks.
    """
    out = tmp_path / "checks.json"
    code = _run(["verify-inputs", "--json-out", str(out)], seeded_data_dir,
                monkeypatch)
    assert code == EXIT_ERROR
    payload = json.loads(out.read_text())
    assert payload["ok"] is False
    assert len(payload["checks"]) == 12
    failed = {c["field"] for c in payload["checks"] if not c["ok"]}
    assert {"total_rows", "keyword_rows", "unique_pairs"} <= failed
    assert payload["summary"]["engines"] == {"keyword": 4, "semantic": 2}


def test_verify_inputs_passes_when_expectations_match_the_file(
        seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With expectations set to the fixture's real shape, every check passes.

    Proves the checks are satisfiable rather than structurally broken — a
    verifier that can only ever fail would be indistinguishable from one that
    works, since the real input is the only thing it is ever pointed at.
    """
    target = (seeded_data_dir / "inputs" /
              "trec-rag26-test119-search-labeled.jsonl")
    from bm25tune.extract import sha256_file

    monkeypatch.setitem(EXPECTED_INPUT, "sha256", sha256_file(target))
    monkeypatch.setitem(EXPECTED_INPUT, "total_rows", 6)
    monkeypatch.setitem(EXPECTED_INPUT, "keyword_rows", 4)
    monkeypatch.setitem(EXPECTED_INPUT, "topics", 2)
    monkeypatch.setitem(EXPECTED_INPUT, "unique_pairs", 3)
    monkeypatch.setitem(EXPECTED_INPUT, "keyword_hits", 7)
    monkeypatch.setitem(EXPECTED_INPUT, "unique_chunk_ids", 6)
    monkeypatch.setitem(EXPECTED_INPUT, "unique_topic_chunk_pairs", 6)
    monkeypatch.setitem(EXPECTED_INPUT, "prefix_chars_positive", 3)
    # The fixture deliberately contains the R4 outlier, so relax only that one.
    from bm25tune import extract as extract_mod

    monkeypatch.setattr(
        extract_mod, "prefix_anomaly", lambda text, n: None)
    assert _run(["verify-inputs"], seeded_data_dir, monkeypatch) == EXIT_OK


def test_verify_inputs_reports_a_missing_input_rather_than_crashing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """An absent input yields a one-line error and exit 1, not a traceback.

    `verify-inputs` is the first command anyone runs on a fresh clone or a new
    server, where the rsync'd `data/` may genuinely be missing — a stack trace
    there teaches nothing about what to do next.
    """
    (tmp_path / "inputs").mkdir()
    with caplog.at_level(logging.INFO):
        code = _run(["verify-inputs"], tmp_path, monkeypatch)
    assert code == EXIT_ERROR
    assert "input not found" in caplog.text


def test_verify_inputs_fails_when_sha256sums_has_no_entry(
        seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """A sums file that does not mention the input is a failure, not a pass.

    Treating a missing entry as "nothing to check" would turn the strongest
    guarantee in the pipeline into a no-op the moment someone regenerated
    `SHA256SUMS` for a different filename.
    """
    (seeded_data_dir / "inputs" / "SHA256SUMS").write_text(
        "0" * 64 + "  some-other-file.jsonl\n")
    with caplog.at_level(logging.INFO):
        code = _run(["verify-inputs"], seeded_data_dir, monkeypatch)
    assert code == EXIT_ERROR
    assert "no entry for" in caplog.text


# ---------------------------------------------------------------------------
# extract-queries
# ---------------------------------------------------------------------------
@pytest.fixture
def relaxed_pair_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the pair-count guard at the fixture's 3 pairs instead of 1063.

    `extract-queries` refuses to write a query set that is not the expected size
    — a guard worth having, and one every test using the 6-row fixture has to
    retarget rather than remove.
    """
    monkeypatch.setitem(EXPECTED_INPUT, "unique_pairs", 3)


def test_extract_queries_writes_both_artifacts(
        seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
        relaxed_pair_count: None) -> None:
    """Both the full set and the Stage-A subsample land on disk, as JSONL rows.

    Later stages read these files rather than re-deriving them, which is what
    makes Stage A reproducible (PLAN §5.1). If only one were written — or written
    empty — the failure would surface as an empty sweep hours later.
    """
    assert _run(["extract-queries"], seeded_data_dir, monkeypatch) == EXIT_OK
    queries = seeded_data_dir / "queries"
    full = queries / "keyword-1063.jsonl"
    sub = queries / "subsample-250.jsonl"
    assert full.is_file() and sub.is_file()
    rows = [json.loads(line) for line in full.read_text().splitlines()]
    assert len(rows) == 3
    assert set(rows[0]) == {"topic_id", "topic", "query", "qkey", "k_orig"}
    # 2 topics x per_topic=2, but topic B has only one query.
    assert len(sub.read_text().splitlines()) == 3


def test_extract_queries_is_byte_reproducible(
        seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
        relaxed_pair_count: None) -> None:
    """Re-running with the same seed produces identical bytes.

    The published Stage-A result names a specific 238-query draw. Byte-identical
    re-derivation is the difference between "seed 13" being a reproducibility
    claim and being a decoration.
    """
    assert _run(["extract-queries"], seeded_data_dir, monkeypatch) == EXIT_OK
    sub = seeded_data_dir / "queries" / "subsample-250.jsonl"
    first = sub.read_bytes()
    assert _run(["extract-queries", "--force"], seeded_data_dir,
                monkeypatch) == EXIT_OK
    assert sub.read_bytes() == first


def test_extract_queries_refuses_to_clobber_without_force(
        seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
        relaxed_pair_count: None,
        caplog: pytest.LogCaptureFixture) -> None:
    """An existing query set is never replaced silently (PLAN §5.8).

    Overwriting happens to be harmless *here* because the output is
    deterministic — but the rule has to be uniform across subcommands, because
    the same reflex applied to a run dir or a cache snapshot destroys
    already-paid-for work.
    """
    assert _run(["extract-queries"], seeded_data_dir, monkeypatch) == EXIT_OK
    with caplog.at_level(logging.INFO):
        code = _run(["extract-queries"], seeded_data_dir, monkeypatch)
    assert code == EXIT_ERROR
    assert "--force" in caplog.text


def test_extract_queries_stops_when_the_pair_count_is_unexpected(
        seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """A query set of the wrong size must not be written at all.

    1063 pairs is the number every volume, cost, and power estimate is keyed to.
    Writing 900 (or 1100) would produce a perfectly well-formed file that
    silently changes the experiment — so the guard fires before anything reaches
    disk.
    """
    with caplog.at_level(logging.INFO):
        code = _run(["extract-queries"], seeded_data_dir, monkeypatch)
    assert code == EXIT_ERROR
    assert "run verify-inputs and STOP" in caplog.text
    assert not (seeded_data_dir / "queries").exists()


def test_extract_queries_seed_changes_the_draw(
        seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
        relaxed_pair_count: None) -> None:
    """`--seed` must actually reach the sampler.

    A flag that is parsed but ignored is worse than no flag: the worklog would
    record a seed that had no effect, making the recorded provenance false rather
    than merely incomplete.

    Swept over several seeds rather than compared across a chosen pair, because
    the fixture's only multi-query topic has just two queries — so any *single*
    pair of seeds has a ~50 % chance of drawing the same one and would make this
    test a coin flip. Observing more than one distinct outcome across the sweep is
    the property that actually distinguishes "seed is used" from "seed is
    ignored".
    """
    draws = set()
    for seed in range(6):
        for path in (seeded_data_dir / "queries").glob("*.jsonl"):
            path.unlink()
        assert _run(["extract-queries", "--per-topic", "1", "--seed", str(seed),
                     "--force"], seeded_data_dir, monkeypatch) == EXIT_OK
        rows = [json.loads(line) for line in
                (seeded_data_dir / "queries" /
                 "subsample-250.jsonl").read_text().splitlines()]
        draws.add(tuple(r["qkey"] for r in rows
                        if r["topic_id"] == "rag2026-900"))
    assert len(draws) > 1, (
        f"every seed drew the same query from a 2-query topic ({draws}); "
        "--seed is not reaching stratified_subsample")


# ---------------------------------------------------------------------------
# Stubs and the exit-code contract
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", [stub.name for stub in cli.STUBS])
def test_unimplemented_subcommands_exit_2_naming_their_work_package(
        name: str, seeded_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """A premature invocation says which WP owns it and exits 2.

    WP1 lands first and the other packages arrive in parallel, so these commands
    *will* be typed early. Exit 2 is distinct from every real failure code in
    PLAN §5.7, so a launching agent can tell "not built yet" from "budget
    refused" without reading the log.
    """
    with caplog.at_level(logging.INFO):
        code = _run([name], seeded_data_dir, monkeypatch)
    assert code == EXIT_NOT_IMPLEMENTED
    assert "not yet implemented" in caplog.text
    assert "WP" in caplog.text


def test_exit_codes_match_the_plans_canonical_table() -> None:
    """The exit-code values are a contract with the launching agent.

    PLAN §5.7 declares this table the single canonical list, and the README and
    drain routine mirror it. A renumbering would silently change what a wrapper
    script concludes: exit 3 means "refresh SSO creds and re-run", exit 5 means
    "a budget stop happened, investigate a bug" — opposite responses.
    """
    assert (cli.EXIT_OK, cli.EXIT_ERROR, cli.EXIT_NOT_IMPLEMENTED) == (0, 1, 2)
    assert cli.EXIT_CRED_EXPIRY == 3
    assert cli.EXIT_BUDGET_PREFLIGHT == 4
    assert cli.EXIT_BUDGET_STOP == 5
    assert cli.EXIT_GATE_FAILED == 6
    assert (cli.EXIT_SIGINT, cli.EXIT_SIGTERM) == (130, 143)


def test_every_plan_subcommand_is_registered() -> None:
    """`--help` must map the whole harness, implemented or not (PLAN §5.6).

    The alternative — adding subcommands as they land — means a mistyped or
    not-yet-built command produces an argparse error indistinguishable from a
    typo, and `--help` understates what the harness is for.
    """
    parser = build_parser()
    actions = [a for a in parser._actions if hasattr(a, "choices")
               and a.dest == "subcommand"]
    registered = set(actions[0].choices)
    expected = {"verify-inputs", "extract-queries", "calibrate",
                "search-sweep", "judge-pool", "score", "stats",
                "rebuild-cache", "cost-report", "budget", "refresh-prices",
                "smoke"}
    assert registered == expected


def test_judge_pool_accepts_the_flags_the_plans_launch_command_uses() -> None:
    """The documented launch command must parse today, even against a stub.

    PLAN §5.6 records a verbatim `judge-pool --run-id … --prompt-version …`
    invocation that goes into the worklog and into chat. If those flags were only
    added with WP3, the recorded command would fail with an
    "unrecognized arguments" error rather than the informative stub message.
    """
    args = build_parser().parse_args(
        ["judge-pool", "--run-id", "20260730T120000-stageA",
         "--prompt-version", "facet-v1"])
    assert args.run_id == "20260730T120000-stageA"
    assert args.prompt_version == "facet-v1"


def test_an_unknown_prompt_version_is_rejected_by_the_parser() -> None:
    """`--prompt-version` is constrained to the registry.

    A typo'd version would otherwise become a fresh cache namespace, re-judging
    and re-billing the entire pool while writing results under a name no report
    refers to. Catching it in argparse costs nothing.
    """
    with pytest.raises(SystemExit):
        build_parser().parse_args(["judge-pool", "--prompt-version", "nope"])


def test_a_bad_env_var_is_a_clean_error_not_a_traceback(
        seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """Config errors map to exit 1 with the offending variable named.

    These are set by hand in a launch command (or by a stale shell), so the
    message has to be enough to fix the export without reading the source.
    """
    monkeypatch.setenv("BM25_TUNE_PRICING_TIER", "premium")
    with caplog.at_level(logging.INFO):
        code = _run(["verify-inputs"], seeded_data_dir, monkeypatch)
    assert code == EXIT_ERROR
    assert "BM25_TUNE_PRICING_TIER" in caplog.text


def test_log_file_option_writes_the_run_log(
        seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    """`--log-file` produces the file a worklog later attaches verbatim.

    PLAN §5.6 requires the run's `sweep.log` to be the same stream the operator
    watched on the console. Copies of these files are the only surviving evidence
    behind an experiment worklog's judgment calls, so the sink has to work for the
    short commands too, not just the multi-hour ones.
    """
    logfile = tmp_path / "nested" / "run.log"
    _run(["--log-file", str(logfile), "verify-inputs"], seeded_data_dir,
         monkeypatch)
    text = logfile.read_text()
    assert "[LOAD]" in text and "[SUMMARY]" in text


def test_config_describe_is_logged_so_a_run_is_explainable(
        seeded_data_dir: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """Every invocation logs its resolved settings, flagging what was overridden.

    A run whose judge region, concurrency, or budget came from a stale exported
    variable is otherwise indistinguishable in the log from one using the
    defaults — and that difference changes what the cost accounting means.
    """
    monkeypatch.setenv("BM25_TUNE_JUDGE_CONCURRENCY", "4")
    monkeypatch.delenv("BM25_TUNE_BUDGET_USD", raising=False)
    with caplog.at_level(logging.INFO):
        _run(["verify-inputs"], seeded_data_dir, monkeypatch)
    assert "concurrency=4" in caplog.text
    assert "BM25_TUNE_JUDGE_CONCURRENCY" in caplog.text
    # `<unset>`, never the approved figure: this line is the operator's evidence
    # of what bounds the run, so printing a cap nobody exported would be a lie in
    # the very record used to reconstruct what happened.
    assert "budget=<unset>" in caplog.text

    caplog.clear()
    monkeypatch.setenv("BM25_TUNE_BUDGET_USD", "50.0")
    with caplog.at_level(logging.INFO):
        _run(["verify-inputs"], seeded_data_dir, monkeypatch)
    assert "budget=$50.00" in caplog.text
    assert "BM25_TUNE_BUDGET_USD" in caplog.text


def test_config_defaults_match_the_plan(monkeypatch: pytest.MonkeyPatch,
                                        tmp_path: Path) -> None:
    """The unset-env defaults are the plan's values (PLAN §4.1).

    These are the numbers a run uses when nobody exports anything, which is the
    common case. A drifted default — especially the judge model id or region —
    would silently change what was judged, and the bare model id is itself
    load-bearing: an `au.*`/`us.*` profile prefix raises ValidationException.
    """
    for var in ("BM25_TUNE_DATA_DIR", "BM25_TUNE_INDEX_DIR",
                "BM25_TUNE_JUDGE_MODEL", "BM25_TUNE_JUDGE_REGION",
                "BM25_TUNE_JUDGE_CONCURRENCY", "BM25_TUNE_BUDGET_USD",
                "BM25_TUNE_PRICING_TIER"):
        monkeypatch.delenv(var, raising=False)
    cfg = Config.from_env()
    assert cfg.judge_model == "openai.gpt-oss-20b-1:0"
    assert cfg.judge_region == "ap-southeast-2"
    assert cfg.judge_concurrency == 16
    # The ONE var with no default (2026-07-31): the cap must be exported per run,
    # because a ceiling inherited from a constant is a ceiling nobody re-confirmed
    # — and money is the one resource the harness cannot roll back.
    assert cfg.budget_usd is None
    assert cfg.pricing_tier == "standard"
    assert cfg.index_dir is None
    assert cfg.data_dir.parts[-2:] == ("data", "bm25-tune")
    assert cfg.overridden == ()


def test_require_index_dir_fails_fast_with_the_export_to_run(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An unset or unreadable index gets a message, not a pyserini stack trace.

    The index is ~1.5 TB under another user's home (PLAN R7), so "unset" and
    "not mounted / no read permission" are both routine — and the JVM's failure
    mode for either is opaque. Non-search subcommands must not pay for this at
    all, which is why it is an explicit call rather than validation at import.
    """
    from bm25tune.config import ConfigError

    monkeypatch.delenv("BM25_TUNE_INDEX_DIR", raising=False)
    with pytest.raises(ConfigError, match="export BM25_TUNE_INDEX_DIR"):
        Config.from_env().require_index_dir()

    missing = tmp_path / "not-there"
    monkeypatch.setenv("BM25_TUNE_INDEX_DIR", str(missing))
    with pytest.raises(ConfigError, match="is not a directory"):
        Config.from_env().require_index_dir()

    missing.mkdir()
    assert Config.from_env().require_index_dir() == missing


def test_importing_the_package_pulls_in_no_heavy_dependency() -> None:
    """No `bm25tune` module may import pyserini or boto3 at module scope.

    This is the constraint that keeps this whole suite runnable in the root env
    with no JVM, no AWS creds, and — critically — **no `importorskip`**, so the
    suite stays skip-free and `scripts/test.sh` needs no new dep group (PLAN
    §4.1/§7.3). A violation would not fail visibly here; it would fail on CI, or
    worse, turn these tests into silent skips.

    Measured in a subprocess, not by inspecting this process's `sys.modules`: the
    full suite already imports `boto3` for `tests/systems/test_aus_agent.py`, so
    an in-process check reports whatever ran earlier and passes or fails on test
    ordering rather than on anything about `bm25tune`.
    """
    import subprocess
    import sys

    task_root = Path(__file__).resolve().parents[2] / "tasks" / "bm25_tune"

    probe = (
        "import sys;"
        "sys.path.insert(0, %r);"
        "import bm25tune, bm25tune.cli, bm25tune.config, bm25tune.extract,"
        " bm25tune.logging_setup, bm25tune.prompts;"
        "bad=[m for m in ('pyserini','boto3','numpy','scipy','torch')"
        " if m in sys.modules];"
        "print(','.join(bad))" % str(task_root)
    )
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                          text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    leaked = proc.stdout.strip()
    assert leaked == "", (
        f"{leaked} imported at module scope; move the import inside the "
        "function that needs it (PLAN §4.1 import discipline)")
