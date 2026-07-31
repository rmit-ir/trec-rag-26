"""`python -m bm25tune <subcommand>` — the harness driver (PLAN §5.6).

Two subcommands are live in WP1: `verify-inputs` and `extract-queries`. The rest
are registered as stubs that print which work package owns them and exit 2, so
`python -m bm25tune --help` is an accurate map of the harness from day one and a
premature invocation fails with a sentence instead of an ImportError.

Design rules this file obeys, each of which is load-bearing elsewhere:

- **Stdlib-only at import.** Nothing here imports `pyserini` or `boto3` at module
  scope; the WPs that add search and judging import theirs inside the subcommand
  body (PLAN §4.1). That is what keeps `tests/bm25_tune/` runnable in the
  repo-root env, with no JVM and no AWS creds, and skip-free.
- **`verify-inputs` never relaxes an assertion.** It compares the input's sha256
  against the committed `SHA256SUMS` *and* re-derives every PLAN §2.1 count. A
  mismatch means the file changed underneath the experiment; the correct response
  is to stop, not to update the expected number. So the expectations live in one
  frozen table (`EXPECTED_INPUT`) and a failure prints expected-vs-actual for
  every field before exiting non-zero.
- **Exit codes are a contract** (PLAN §5.7): `0` ok, `1` unexpected, `2`
  not-yet-implemented, `3` credential expiry, `4` pre-flight budget refusal, `5`
  mid-run budget stop, `6` calibration gate failure, `130`/`143` signalled drain.
  A launching agent branches on these rather than parsing logs, so the table is
  defined here once and mirrored (not redefined) in the README.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import extract
from .config import Config, ConfigError
from .logging_setup import get_logger, setup_logging
from .prompts import DEFAULT_PROMPT_VERSION, all_versions

log = get_logger("cli")

# -- exit codes (PLAN §5.7's canonical table) --------------------------------
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_IMPLEMENTED = 2
EXIT_CRED_EXPIRY = 3
EXIT_BUDGET_PREFLIGHT = 4
EXIT_BUDGET_STOP = 5
EXIT_GATE_FAILED = 6
EXIT_SIGINT = 130
EXIT_SIGTERM = 143

# -- what `verify-inputs` asserts (PLAN §2.1) --------------------------------
#: The committed input's identity and shape. Every number here was derived from
#: the file itself and cross-checks against PLAN §2.1. **Do not edit a value to
#: make a failing check pass** — a mismatch means the input changed, which
#: invalidates the query set, the qrels, and the published run ids.
EXPECTED_INPUT: dict[str, object] = {
    "sha256": "9bb4bae7184be026cb0139a445b14f2f00db340d1da58f0b8c9b1596341c6c1a",
    "total_rows": 2143,
    "keyword_rows": 1070,
    "topics": 119,
    "unique_pairs": 1063,
    "keyword_hits": 9208,
    "unique_chunk_ids": 8551,
    "unique_topic_chunk_pairs": 8580,
    "prefix_chars_positive": 3890,
    "run_id": "test-keyword-119",
}

#: Filenames PLAN §4.2 fixes for the query artifacts. `subsample-250` keeps its
#: name even though 119 topics x 2 yields 238 rows: it is the *published* name
#: of the Stage-A set and appears in the plan, the manifest, and every log line.
QUERIES_FULL_BASENAME = "keyword-1063.jsonl"
QUERIES_SUBSAMPLE_BASENAME = "subsample-250.jsonl"
SUBSAMPLE_PER_TOPIC = 2
SUBSAMPLE_SEED = 13


class NotImplementedYet(RuntimeError):
    """A subcommand whose owning work package has not landed.

    A named exception rather than a bare `print`+`exit` so the message, the exit
    code, and the WP attribution are produced in exactly one place.
    """


@dataclass(frozen=True)
class Stub:
    """A registered-but-unimplemented subcommand and the WP that owns it."""

    name: str
    work_package: str
    summary: str

    def run(self, args: argparse.Namespace) -> int:
        raise NotImplementedYet(
            f"`{self.name}` is not yet implemented ({self.work_package}). "
            f"Intended behaviour: {self.summary}")


#: PLAN §5.6's remaining subcommands, with the work package that delivers each.
STUBS: tuple[Stub, ...] = (
    Stub("calibrate", "WP6 (needs WP3 + WP3b)",
         "judge the 280-pair calibration sample under all four prompt "
         "variants plus a 50-pair stability probe, then apply the §3.3 "
         "grade-spread gate (exit 6 on failure)"),
    Stub("search-sweep", "WP2",
         "run the k1/b grid over the query set at depth 30, writing TREC run "
         "files and pool.jsonl (search only; no Bedrock)"),
    Stub("judge-pool", "WP3 (+ WP3b for the budget guard)",
         "judge the per-topic pooled union with the Bedrock judge — the long, "
         "fully resumable job"),
    Stub("score", "WP4",
         "compute nDCG@10 (both gain conventions) and the pre-registered "
         "secondaries from the cached qrels into scores.csv/.md"),
    Stub("stats", "WP4",
         "Stage-B paired t / Wilcoxon / bootstrap CIs on the held-out queries "
         "into stats.json"),
    Stub("rebuild-cache", "WP3",
         "force a full rescan of the append-only judgment log into a fresh "
         "cache snapshot"),
    Stub("cost-report", "WP3b",
         "write costs.json/.md plus the experiment-wide roll-up and the "
         "ledger-vs-log reconciliation line"),
    Stub("budget", "WP3b",
         "print spent / cap / remaining from costs/totals.json and exit; makes "
         "no API calls"),
    Stub("refresh-prices", "WP3b",
         "re-fetch the AWS Pricing API into a NEW dated prices/ file (never "
         "overwrites an existing one)"),
    Stub("smoke", "WP2 + WP3",
         "the live end-to-end check: 3 real index queries and 1 real, metered "
         "judgment"),
)


# ---------------------------------------------------------------------------
# verify-inputs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Check:
    """One expected-vs-actual comparison, with why it matters if it fails."""

    field: str
    expected: object
    actual: object
    note: str

    @property
    def ok(self) -> bool:
        return self.expected == self.actual

    def line(self) -> str:
        mark = "ok  " if self.ok else "FAIL"
        return (f"  [{mark}] {self.field}: expected {self.expected!r} "
                f"got {self.actual!r}"
                + ("" if self.ok else f"  <- {self.note}"))


def _input_checks(summary: extract.InputSummary, digest: str,
                  committed: str) -> list[Check]:
    """Build the full check list — checksum, then every PLAN §2.1 count."""
    exp = EXPECTED_INPUT
    checks = [
        Check("sha256(file)", committed, digest,
              "the file on disk is not the one the experiment was designed "
              "against; do not proceed, re-fetch the durable copy"),
        Check("sha256(committed)", exp["sha256"], committed,
              "SHA256SUMS itself changed — the committed checksum no longer "
              "matches the plan's recorded digest"),
        Check("total_rows", exp["total_rows"], summary.total_rows,
              "row count changed, so the input is a different export"),
        Check("keyword_rows", exp["keyword_rows"], summary.keyword_rows,
              "the engine=='keyword' slice changed size; the sweep's query "
              "population is not what was measured"),
        Check("topics", exp["topics"], summary.topics,
              "the official 119-topic set is incomplete or over-complete"),
        Check("unique_pairs", exp["unique_pairs"], summary.unique_pairs,
              "the headline query set is not 1063 pairs; every volume, cost, "
              "and statistics estimate in the plan is keyed to this number"),
        Check("keyword_hits", exp["keyword_hits"], summary.keyword_hits,
              "the observed-hit population changed, invalidating the "
              "calibration strata"),
        Check("unique_chunk_ids", exp["unique_chunk_ids"],
              summary.unique_chunk_ids,
              "chunk identity changed — possibly a re-chunked corpus, which "
              "would make cached judgments refer to different text"),
        Check("unique_topic_chunk_pairs", exp["unique_topic_chunk_pairs"],
              summary.unique_topic_chunk_pairs,
              "the (topic, chunk) space the cache is keyed on changed size"),
        Check("prefix_chars_positive", exp["prefix_chars_positive"],
              summary.prefix_chars_positive,
              "the number of hits carrying a leaked page header changed, so "
              "the judge's input text may differ from what was measured"),
        Check("keyword run_ids", {str(exp["run_id"]): exp["keyword_rows"]},
              summary.run_ids,
              "keyword rows come from more than the one expected run, mixing "
              "query-generation regimes (PLAN §2.2 excludes the others)"),
        Check("prefix_miss", 0, summary.prefix_miss,
              "a hit's prefix_chars disagrees with its text "
              f"({summary.prefix_anomalies}); the slice would either leave a "
              "leaked topical header in the passage or amputate real evidence "
              "from it — inspect before judging anything (PLAN R4)"),
    ]
    return checks


def cmd_verify_inputs(args: argparse.Namespace) -> int:
    """Verify the durable input copy: checksum + every PLAN §2.1 count.

    Runs before every stage (PLAN R8) because the original lived in `/tmp` and
    the durable copy is the experiment's only anchor to it.
    """
    cfg: Config = args.config
    path = cfg.input_file
    if not path.is_file():
        log.error("[LOAD] input not found: %s", path)
        log.error("[LOAD] expected the durable copy of the labeled search log; "
                  "see PLAN §2.1")
        return EXIT_ERROR
    sums_path = cfg.sha256sums_file
    if not sums_path.is_file():
        log.error("[LOAD] SHA256SUMS not found: %s", sums_path)
        return EXIT_ERROR

    committed = extract.read_sha256sums(sums_path).get(path.name, "")
    if not committed:
        log.error("[LOAD] %s has no entry for %s", sums_path, path.name)
        return EXIT_ERROR

    log.info("[LOAD] verifying %s (%.1f MB)", path,
             path.stat().st_size / 1e6)
    digest = extract.sha256_file(path)
    summary = extract.summarize_input(path)
    checks = _input_checks(summary, digest, committed)

    log.info("[SUMMARY] input checks (%d):", len(checks))
    for check in checks:
        (log.info if check.ok else log.error)("%s", check.line())

    failed = [c for c in checks if not c.ok]
    log.info("[SUMMARY] engines=%s", summary.engines)
    log.info("[SUMMARY] agent labels=%s", summary.agent_labels)
    log.info("[SUMMARY] agent reasons=%s", summary.agent_reasons)

    if args.json_out:
        payload = {
            "input_file": str(path),
            "input_sha256": digest,
            "committed_sha256": committed,
            "summary": summary.to_json(),
            "checks": [{"field": c.field, "expected": c.expected,
                        "actual": c.actual, "ok": c.ok} for c in checks],
            "ok": not failed,
        }
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
        log.info("[SUMMARY] wrote %s", args.json_out)

    if failed:
        log.error("[SUMMARY] %d/%d checks FAILED — STOP. Do not relax an "
                  "expectation to make this pass; the input changed and every "
                  "downstream artifact (query set, qrels, cached judgments) "
                  "refers to the old one.", len(failed), len(checks))
        return EXIT_ERROR
    log.info("[SUMMARY] all %d checks passed; sha256=%s", len(checks), digest)
    return EXIT_OK


# ---------------------------------------------------------------------------
# extract-queries
# ---------------------------------------------------------------------------
def cmd_extract_queries(args: argparse.Namespace) -> int:
    """Write `queries/keyword-1063.jsonl` and `queries/subsample-250.jsonl`.

    Both files are persisted rather than re-derived on demand, which is what
    makes Stage A byte-reproducible (PLAN §5.1): later stages read the file, so
    "which queries did we sweep" is answered by an artifact, not by re-running a
    sampler and trusting the seed.
    """
    cfg: Config = args.config
    path = cfg.input_file
    if not path.is_file():
        log.error("[LOAD] input not found: %s (run verify-inputs)", path)
        return EXIT_ERROR

    queries = extract.load_keyword_queries(path)
    topics = sorted({q.topic_id for q in queries})
    log.info("[LOAD] %d unique keyword (topic, query) pairs over %d topics",
             len(queries), len(topics))
    if len(queries) != EXPECTED_INPUT["unique_pairs"]:
        log.error("[LOAD] expected %s unique pairs, got %d — run verify-inputs "
                  "and STOP; the query set defines the whole experiment",
                  EXPECTED_INPUT["unique_pairs"], len(queries))
        return EXIT_ERROR

    subsample = extract.stratified_subsample(
        queries, per_topic=args.per_topic, seed=args.seed)
    sub_topics = sorted({q.topic_id for q in subsample})

    cfg.ensure_dirs(cfg.queries_dir)
    full_path = cfg.queries_dir / QUERIES_FULL_BASENAME
    sub_path = cfg.queries_dir / QUERIES_SUBSAMPLE_BASENAME
    if (full_path.exists() or sub_path.exists()) and not args.force:
        # Rewriting is harmless (the output is deterministic), but refusing
        # keeps the "existing output is never silently replaced" rule of
        # PLAN §5.8 uniform across subcommands.
        log.error("[LOAD] refusing to overwrite existing query files; pass "
                  "--force. Present: %s",
                  ", ".join(str(p) for p in (full_path, sub_path)
                            if p.exists()))
        return EXIT_ERROR

    n_full = extract.write_query_file(full_path, queries)
    n_sub = extract.write_query_file(sub_path, subsample)
    log.info("[LOAD] wrote %s (%d rows, %d topics)", full_path, n_full,
             len(topics))
    log.info("[LOAD] wrote %s (%d rows, %d topics, per_topic=%d seed=%d)",
             sub_path, n_sub, len(sub_topics), args.per_topic, args.seed)

    # Read back and re-derive the tags: cheap, and it pins that the persisted
    # file is what later stages will actually load (a qkey/query mismatch would
    # silently misattribute run files).
    reloaded = extract.read_query_file(sub_path)
    if [r.qkey for r in reloaded] != [r.qkey for r in subsample]:
        log.error("[LOAD] round-trip of %s does not match what was written",
                  sub_path)
        return EXIT_ERROR

    per_topic_counts = {t: sum(1 for q in queries if q.topic_id == t)
                        for t in topics}
    log.info("[SUMMARY] queries/topic min=%d max=%d",
             min(per_topic_counts.values()), max(per_topic_counts.values()))
    log.info("[SUMMARY] subsample sha256=%s", extract.sha256_file(sub_path))
    return EXIT_OK


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """The full `python -m bm25tune` parser, stubs included.

    Stubs are registered so `--help` maps the whole harness (PLAN §5.6) even
    before their work packages land — and so a mistyped subcommand is an
    argparse error rather than a silent no-op.
    """
    parser = argparse.ArgumentParser(
        prog="python -m bm25tune",
        description=("BM25 k1/b tuning on the chunked ClimbMix index with a "
                     "Bedrock LLM judge. See tasks/bm25_tune/PLAN.md."),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--log-file", type=Path, default=None,
                        help="also write the log here (runs/<id>/sweep.log "
                             "for the long jobs)")
    parser.add_argument("--verbose", action="store_true",
                        help="DEBUG-level logging")
    subs = parser.add_subparsers(dest="subcommand", required=True,
                                 metavar="<subcommand>")

    verify = subs.add_parser(
        "verify-inputs",
        help="sha256-check inputs/ against SHA256SUMS and assert the PLAN "
             "§2.1 row/count numbers")
    verify.add_argument("--json-out", type=Path, default=None,
                        help="also write the check results as JSON")
    verify.set_defaults(func=cmd_verify_inputs)

    extract_cmd = subs.add_parser(
        "extract-queries",
        help=f"write queries/{QUERIES_FULL_BASENAME} and "
             f"queries/{QUERIES_SUBSAMPLE_BASENAME}")
    extract_cmd.add_argument("--per-topic", type=int,
                             default=SUBSAMPLE_PER_TOPIC,
                             help="queries per topic in the Stage-A subsample")
    extract_cmd.add_argument("--seed", type=int, default=SUBSAMPLE_SEED,
                             help="subsample seed (PLAN §5.1 fixes 13)")
    extract_cmd.add_argument("--force", action="store_true",
                             help="overwrite existing query files")
    extract_cmd.set_defaults(func=cmd_extract_queries)

    for stub in STUBS:
        sub = subs.add_parser(stub.name,
                              help=f"[{stub.work_package}] {stub.summary}")
        # `--prompt-version` and `--run-id` are accepted now so the launch
        # commands recorded in PLAN §5.6 parse (and fail on the stub message)
        # rather than dying on an unrecognized argument.
        if stub.name in {"judge-pool", "score", "cost-report", "calibrate"}:
            sub.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION,
                             choices=all_versions())
        if stub.name in {"judge-pool", "score", "search-sweep", "cost-report",
                         "stats"}:
            sub.add_argument("--run-id", default=None)
        sub.set_defaults(func=stub.run)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, configure logging, dispatch, and map exceptions to exit codes."""
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.log_file,
                  level=logging.DEBUG if args.verbose else logging.INFO)
    try:
        args.config = Config.from_env()
    except ConfigError as exc:
        log.error("[LOAD] configuration error: %s", exc)
        return EXIT_ERROR
    log.info("[LOAD] %s", args.config.describe())
    try:
        return int(args.func(args))
    except NotImplementedYet as exc:
        log.error("%s", exc)
        return EXIT_NOT_IMPLEMENTED
    except ConfigError as exc:
        log.error("[LOAD] configuration error: %s", exc)
        return EXIT_ERROR
    except extract.ExtractError as exc:
        log.error("[LOAD] %s", exc)
        return EXIT_ERROR
    except KeyboardInterrupt:
        # WP1 has no in-flight work to drain; WP3 replaces this with the
        # §5.8 drain routine, which is why the code is already the 128+SIGINT
        # value the plan's exit-code table promises.
        log.error("[SIGNAL] SIGINT — nothing in flight to drain")
        return EXIT_SIGINT


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
