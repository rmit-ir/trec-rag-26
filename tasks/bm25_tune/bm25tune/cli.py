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
- **The spend ceiling must be exported, never defaulted.** Every subcommand that
  can reach Bedrock or report against the cap calls `cfg.require_budget_usd()`,
  which raises `ConfigError` (exit 1) when `BM25_TUNE_BUDGET_USD` is unset. The
  cap is the user's live decision (PLAN §0), so it is resolved *early* — before
  the pool loads and the cache replays — and the commands that cannot spend
  (`verify-inputs`, `extract-queries`, `search-sweep`, `score`, `stats`,
  `rebuild-cache`, `smoke --search-only`) never call it and run with it unset.
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
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import calibration as calib
from . import extract, metrics, pricing, store
from . import pool as pool_mod
from . import searcher as searcher_mod
from . import stats as stats_mod
from .config import Config, ConfigError
from .logging_setup import get_logger, setup_logging
from .prompts import DEFAULT_PROMPT_VERSION, all_versions, get_prompt

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
#: Empty as of 2026-07-31: `calibrate` (WP6) was the last stub and now has a real
#: implementation (`cmd_calibrate`). Kept as an extension point rather than
#: deleted — the machinery (parser registration, the `NotImplementedYet` exit-2
#: path) is exactly what a future PLAN §5.6 command wants.
STUBS: tuple[Stub, ...] = ()


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
# budget / cost-report / refresh-prices  (WP3b, PLAN §5.7)
# ---------------------------------------------------------------------------
def _load_rates_or_fail(cfg: Config):
    """`load_rates` for the configured model/region/tier, or a clean exit-1.

    Wrapped so the three cost subcommands share one error message: an unknown
    (model, region, tier) is a *stop*, never a fallback rate, because a guessed
    rate would corrupt both the report and the ceiling (PLAN R12).
    """
    from .pricing import UnknownRate, load_rates, warn_if_nonstandard_tier

    try:
        rates = load_rates(cfg.judge_model, cfg.judge_region, cfg.pricing_tier)
    except UnknownRate as exc:
        log.error("[COST] %s", exc)
        return None
    warn_if_nonstandard_tier(rates.tier, log)
    return rates


def cmd_budget(args: argparse.Namespace) -> int:
    """Print spent / cap / remaining from `costs/totals.json` and exit.

    **Makes no API call** — it only reads the durable meter state, which is why
    PLAN §9's standing rule can require every executing agent to run it before
    launching any job that touches Bedrock. Zero spend, so it is safe to run
    from a hook, a script, or reflexively.
    """
    from .pricing import BudgetGuard, CostMeter

    cfg: Config = args.config
    rates = _load_rates_or_fail(cfg)
    if rates is None:
        return EXIT_ERROR
    meter = CostMeter.load(cfg.costs_dir)
    guard = BudgetGuard(meter, cfg.require_budget_usd(), cfg.judge_concurrency,
                        rates=rates)
    status = guard.status()
    log.info("[BUDGET] spent=$%.4f cap=$%.2f remaining=$%.4f "
             "(reserve=$%.4f at concurrency %d)",
             status["spent_usd"], status["cap_usd"], status["remaining_usd"],
             status["reserve_usd"], status["concurrency"])
    log.info("[COST] calls=%d records=%d basis=%s mean_in=%.1f mean_out=%.1f "
             "mean_call=$%.8f max_call=$%.8f",
             status["calls"], status["records"], status["basis"],
             status["mean_input_tokens"], status["mean_output_tokens"],
             status["mean_call_usd"], status["max_call_usd"])
    log.info("[COST] by_stage=%s table=%s tier=%s",
             status["by_stage"] or "{}", rates.table_id, rates.tier)
    if not meter.totals_path.exists():
        log.info("[COST] no %s yet — nothing has been spent on this experiment",
                 meter.totals_path)
    if args.json:
        print(json.dumps({**status, "rate_table_id": rates.table_id,
                          "tier": rates.tier}, indent=2, sort_keys=True))
    return EXIT_OK


def cmd_cost_report(args: argparse.Namespace) -> int:
    """Write `costs.json` + `costs.md` and print the reconciliation verdict.

    Reads the append-only judgment log — the ground-truth spend, including
    `attempt_error` rows, which were billed too — so the report is derived from
    the audit record rather than from whatever the meter happened to have in
    memory. With `--run-id` it emits the run's breakdown alongside the
    experiment-wide roll-up; without one, the roll-up alone.
    """
    from .pricing import (CostMeter, build_cost_report, write_cost_artifacts)

    cfg: Config = args.config
    rates = _load_rates_or_fail(cfg)
    if rates is None:
        return EXIT_ERROR
    meter = CostMeter.load(cfg.costs_dir)

    manifest: dict = {}
    out_dir = cfg.costs_dir
    if args.run_id:
        out_dir = cfg.run_dir(args.run_id)
        manifest_path = out_dir / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.warning("[COST] %s is not valid JSON; per-query/per-cell "
                            "figures will be omitted", manifest_path)
    if args.out_dir:
        out_dir = args.out_dir

    report = build_cost_report(
        cfg.log_dir, meter, cap_usd=cfg.require_budget_usd(),
        run_id=args.run_id,
        cache_hits=int(args.cache_hits
                       if args.cache_hits is not None
                       else (manifest.get("cache") or {}).get("hits", 0) or 0),
        rates=rates, manifest=manifest)
    json_path, md_path = write_cost_artifacts(out_dir, report)

    scope = report.get("run") or report["experiment"]
    log.info("[COST] %s: %d records, %d billed calls, $%.6f",
             args.run_id or "experiment", scope["records"],
             scope["billed_calls"], scope["total_usd"])
    log.info("[COST] usd_per_judged_pair=$%.8f over %d unique jkeys "
             "(prompt-version qualified)", scope["usd_per_judged_pair"],
             scope["judged_pairs"])
    log.info("[COST] cache_hits=%d saved~$%.6f (ESTIMATE) wasted=$%.6f",
             scope["cache"]["hits"],
             scope["cache"]["usd_saved_by_cache_estimate"],
             scope["wasted_usd"]["total_usd"])
    log.info("[BUDGET] spent=$%.4f cap=$%.2f remaining=$%.4f",
             report["budget"]["spent_usd"], report["budget"]["cap_usd"],
             report["budget"]["remaining_usd"])
    rec = report["reconciliation"]
    line = ("[COST] reconciliation: ledger=$%.6f log=$%.6f delta=$%.6f -> %s"
            % (rec["ledger_total_usd"], rec["judgment_log_total_usd"],
               rec["delta_usd"], rec["status"]))
    if rec["status"] == "integrity_error":
        log.error("%s", line)
        log.error("[COST] the ledger claims more spend than the judgment log "
                  "can account for; a crash cannot produce this. Investigate "
                  "%s before spending anything else.", cfg.log_dir)
    else:
        log.info("%s", line)
    log.info("[SUMMARY] wrote %s and %s", json_path, md_path)
    return EXIT_ERROR if rec["status"] == "integrity_error" else EXIT_OK


def cmd_refresh_prices(args: argparse.Namespace) -> int:
    """Re-fetch the AWS Pricing API into a **NEW dated** `prices/` file.

    Never overwrites: a run's figures must stay traceable to the exact table it
    priced against, so a price change becomes a new file plus a manifest field
    rather than a retroactive edit of published numbers (PLAN §5.7).

    **This is the only place `boto3` appears outside `judge.py`, and the import
    is inside the function body** so `pricing.py` and every test stay
    stdlib-only (PLAN §4.1). The Pricing API itself is only served from
    `us-east-1`/`ap-south-1`, which is why the client region differs from the
    region being priced.
    """
    import boto3  # noqa: PLC0415 - lazy by design (PLAN §4.1)

    from . import pricing

    cfg: Config = args.config
    region = args.region or cfg.judge_region
    model_id = args.model_id or cfg.judge_model
    slug = args.slug or _region_slug(region)
    date = args.date or time.strftime("%Y-%m-%d", time.gmtime())
    table_id = f"bedrock-{_model_slug(model_id)}-{slug}-{date}"
    out = pricing.rate_table_path(table_id)
    if out.exists():
        log.error("[COST] %s already exists — refusing to overwrite a committed "
                  "rate table. Published cost figures cite it by id; pass "
                  "--date to write a new dated file instead.", out)
        return EXIT_ERROR

    log.info("[COST] fetching AmazonBedrock prices for region=%s model=%s "
             "via the Pricing API in %s", region, model_id, args.pricing_region)
    client = boto3.client("pricing", region_name=args.pricing_region)
    entries: list[dict] = []
    paginator = client.get_paginator("get_products")
    for page in paginator.paginate(
            ServiceCode="AmazonBedrock",
            Filters=[{"Type": "TERM_MATCH", "Field": "regionCode",
                      "Value": region}]):
        for blob in page["PriceList"]:
            entry = json.loads(blob)
            attrs = entry.get("product", {}).get("attributes", {})
            if args.model_match not in attrs.get("usagetype", ""):
                continue
            entries.append(entry)

    rates: dict[str, dict] = {}
    for entry in entries:
        attrs = entry["product"]["attributes"]
        for term in entry.get("terms", {}).get("OnDemand", {}).values():
            for dim in term.get("priceDimensions", {}).values():
                rates[attrs["usagetype"]] = {
                    "usd_per_unit": dim["pricePerUnit"]["USD"],
                    "unit": dim["unit"],
                    "description": dim.get("description", ""),
                }
    if not rates:
        log.error("[COST] the Pricing API returned no rates matching %r in %s "
                  "— refusing to write an empty rate table", args.model_match,
                  region)
        return EXIT_ERROR

    payload = {
        "rate_table_id": table_id,
        "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": (f"boto3 pricing.get_products(ServiceCode=AmazonBedrock, "
                   f"regionCode={region})"),
        "region": region,
        "model_id": model_id,
        "note": ("usd_per_unit is per 1000 tokens (unit field confirms). Tiers "
                 "parsed from the usagetype suffix."),
        "rates": dict(sorted(rates.items())),
        "raw_price_list": entries,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    log.info("[COST] wrote %s (%d rate entries)", out, len(rates))
    log.info("[COST] to price against it, pass table_id=%s — the default "
             "RATE_TABLE_ID is pinned so a running experiment cannot silently "
             "re-price itself.", table_id)
    return EXIT_OK


def _region_slug(region: str) -> str:
    """`ap-southeast-2` -> `aps2`, matching the committed table's name."""
    parts = region.split("-")
    if len(parts) == 3:
        return f"{parts[0]}{parts[1][0]}{parts[2]}"
    return region.replace("-", "")


def _model_slug(model_id: str) -> str:
    """`openai.gpt-oss-20b-1:0` -> `gpt-oss-20b`, matching the committed name."""
    tail = model_id.split(".", 1)[-1].split(":", 1)[0]
    return tail.rsplit("-", 1)[0] if tail.rsplit("-", 1)[-1].isdigit() else tail


# ---------------------------------------------------------------------------
# search-sweep / smoke  (WP2, PLAN §5.2, §5.5, §5.6, §6.1)
# ---------------------------------------------------------------------------
#: Written next to `pool.jsonl`. PLAN §4.2 gives `pool.jsonl` a `text_sha256`
#: column but no text, and pooled chunks come from the live index — most were
#: never in the labeled input — so *something* has to carry the passages from the
#: searching process to the judging one. Doing it here means `judge-pool`, the
#: multi-hour job, never opens a 1.5 TB mmap or needs a JVM at all: it reads
#: JSONL. The digest in `pool.jsonl` then pins that the text a cached judgment
#: was made on is the text still on disk.
POOL_TEXTS_BASENAME = "pool-texts.jsonl"
POOL_BASENAME = "pool.jsonl"
TRECRUNS_DIRNAME = "trecruns"
MANIFEST_BASENAME = "manifest.json"
SWEEP_LOG_BASENAME = "sweep.log"

#: WP6 (PLAN §3.3). The calibration sample is persisted once and every variant
#: judges the *same* file — a grade-distribution comparison across prompts is
#: only meaningful on identical pairs.
CALIBRATION_SAMPLE_BASENAME = "sample-280.jsonl"
CALIBRATION_REPORT_MD = "report.md"
CALIBRATION_REPORT_JSON = "report.json"
CALIBRATION_LOG_BASENAME = "calibrate.log"
CALIBRATION_SAMPLE_N = 280
CALIBRATION_SAMPLE_SEED = 7
#: Stage label so the calibration spend is its own line in `costs/totals.json`
#: (PLAN §5.7) and never contaminates the sweep's Stage-A/B cost split.
CALIBRATION_STAGE = "calib"

#: Queries `smoke --search-only` falls back to when no query file exists yet.
#: Real-looking multi-word keyword strings, because the point of the smoke test
#: is to prove the *production* path works, and a single-term query would not
#: exercise the multi-term scoring the sweep actually measures.
SMOKE_FALLBACK_QUERIES = (
    "public library print reference collection budget decline",
    "soil moisture sensor irrigation scheduling evapotranspiration",
    "workplace mentoring program retention outcomes evaluation",
)


def _utc_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime())


def _default_run_id(stage: str) -> str:
    """`20260730T120000-stageA` — PLAN §4.2's run-id shape.

    Generated from the clock rather than accepted as required input so the
    documented commands work unmodified; the id is logged and echoed so the
    follow-up `judge-pool --run-id …` can be copy-pasted.
    """
    return f"{_utc_stamp()}-stage{stage}"


def _guard_derived_path(cfg: Config, path: Path, flag: str) -> None:
    """Refuse to let `--fresh`/`--force` near an append-only audit artifact.

    PLAN §5.8: `judgments/log/` and `costs/` are append-only by definition — the
    judgment log is the ground truth for both the qrels and the spend, and the
    ledger is the budget's durable state. A `--fresh` that could rename either
    would destroy already-paid-for work and make the cost reconciliation
    unfalsifiable. Resolved paths are compared, so a crafted `--run-id` such as
    `../../judgments/log` is caught too.
    """
    resolved = path.resolve()
    for protected, tool in ((cfg.log_dir, "rebuild-cache"),
                            (cfg.costs_dir, "cost-report")):
        protected = protected.resolve()
        if resolved == protected or protected in resolved.parents \
                or resolved in protected.parents:
            raise ConfigError(
                f"{flag} refuses to touch {resolved}: {protected} is an "
                "append-only audit record (raw judgments / the cost ledger), "
                f"not a derived artifact. Use `{tool}` instead (PLAN §5.8).")


def _fresh_run_dir(cfg: Config, run_dir: Path) -> Path | None:
    """Rename an existing run dir to `<run_id>.superseded-<UTCts>`.

    Renames rather than deletes, always: the run dir may hold a `sweep.log` that
    is the only surviving evidence behind an earlier judgment call, and PLAN §5.8
    forbids `--fresh` from destroying anything. Returns the new path, or `None`
    if there was nothing to move.
    """
    _guard_derived_path(cfg, run_dir, "--fresh")
    if not run_dir.exists():
        return None
    target = run_dir.with_name(f"{run_dir.name}.superseded-{_utc_stamp()}")
    run_dir.rename(target)
    log.warning("[LOAD] --fresh: renamed %s -> %s (never deleted)", run_dir,
                target)
    return target


def _load_sweep_queries(cfg: Config, args: argparse.Namespace,
                        stage: str) -> list[extract.QueryRec]:
    """Load the stage's persisted query file (PLAN §5.1).

    Stage A reads `subsample-250.jsonl`, Stage B the full `keyword-1063.jsonl`.
    Both are read from disk rather than re-derived from the labeled input and the
    seed, which is the whole reason they are persisted: "what did Stage A sweep"
    must be answered by an artifact, not by trusting that a sampler is still
    deterministic.
    """
    if args.queries is not None:
        path = Path(args.queries)
    else:
        path = cfg.queries_dir / (QUERIES_SUBSAMPLE_BASENAME if stage == "A"
                                  else QUERIES_FULL_BASENAME)
    if not path.is_file():
        raise ConfigError(
            f"query file {path} not found — run `python -m bm25tune "
            "extract-queries` first (it writes both the full set and the "
            "Stage-A subsample)")
    queries = extract.read_query_file(path)
    if not queries:
        raise ConfigError(f"query file {path} is empty")
    if args.limit:
        # Sanity-run knob. Sliced *after* loading and before any search so the
        # subset is a prefix of the persisted, deterministic order — a random
        # subset would make a plumbing check unreproducible.
        queries = queries[:args.limit]
    topics = {q.topic_id for q in queries}
    log.info("[LOAD] %d queries over %d topics from %s", len(queries),
             len(topics), path)
    return queries


def _sweep_configs(args: argparse.Namespace,
                   stage: str) -> list[tuple[float, float]]:
    """The grid cells to sweep: `--configs` if given, else PLAN §6.1's 26.

    Stage B has no default on purpose. Its cells are *the top 3 from Stage A plus
    the baseline*, which is only known once Stage A has been scored — defaulting
    to the full grid would quietly turn a 4-config confirmatory run into a
    26-config one over 1063 queries and blow up the judging pool.
    """
    if args.configs:
        return searcher_mod.parse_configs(args.configs)
    if stage == "B":
        raise ConfigError(
            "Stage B needs an explicit --configs (PLAN §6.1: the top 3 Stage-A "
            "cells plus the 0.9:0.4 baseline), e.g.\n"
            "  --configs 0.7:0.35,0.9:0.5,1.2:0.35,0.9:0.4")
    return searcher_mod.stage_a_grid()


def cmd_search_sweep(args: argparse.Namespace) -> int:
    """Run the k1/b grid at depth 30, writing run files and the pool.

    Search only — **no Bedrock, no spend** (PLAN §5.6's stage separation is what
    makes the cheap half freely re-runnable). Idempotent by run file: a config
    whose `trecruns/<cell>.txt` already exists is skipped and its ranking is read
    back for pooling, so a crashed or interrupted sweep resumes with "re-run the
    same command" and re-searches only what is missing.

    One `ChunkSearcher`, warmed once, then configs applied strictly sequentially
    (PLAN §5.2/R9) — the 9.4 s cold start is paid and logged under `[WARMUP]`
    before the first cell is timed.
    """
    cfg: Config = args.config
    stage = args.stage
    run_id = args.run_id or _default_run_id(stage)
    run_dir = cfg.run_dir(run_id)
    if args.fresh:
        _fresh_run_dir(cfg, run_dir)
    _guard_derived_path(cfg, run_dir, "search-sweep --run-id")
    runs_out = run_dir / TRECRUNS_DIRNAME
    cfg.ensure_dirs(run_dir, runs_out)
    # Re-point the log sink at the run's own sweep.log now that the run id is
    # known, so the file a worklog later attaches is the stream the operator
    # watched (PLAN §5.6).
    setup_logging(args.log_file or (run_dir / SWEEP_LOG_BASENAME),
                  level=logging.DEBUG if args.verbose else logging.INFO)
    log.info("[LOAD] search-sweep stage=%s run_id=%s depth=%d run_dir=%s",
             stage, run_id, args.depth, run_dir)

    queries = _load_sweep_queries(cfg, args, stage)
    configs = _sweep_configs(args, stage)
    log.info("[SEARCH] %d configs x %d queries = %d executions at depth %d",
             len(configs), len(queries), len(configs) * len(queries),
             args.depth)

    index_dir = cfg.require_index_dir()
    chunk_searcher = searcher_mod.ChunkSearcher(index_dir, threads=args.threads)
    rankings: dict[str, dict[str, list[tuple[str, float]]]] = {}
    searched = skipped = 0
    search_started = time.monotonic()
    try:
        for k1, b in configs:
            key = searcher_mod.config_key(k1, b)
            run_path = runs_out / searcher_mod.run_file_name(k1, b)
            if run_path.is_file() and not args.force:
                rankings[key] = pool_mod.read_trec_run(run_path)
                skipped += 1
                log.info("[SEARCH] %s already present (%d queries) — skipping; "
                         "pass --force to re-search", run_path,
                         len(rankings[key]))
                continue
            # Warmup is deferred to the first cell that actually searches, so a
            # fully-resumed sweep costs nothing at all.
            chunk_searcher.warmup()
            chunk_searcher.set_config(k1, b)
            result = chunk_searcher.run_config(queries, k=args.depth)
            written = pool_mod.write_trec_run(run_path, result, key,
                                              depth=args.depth)
            log.info("[SEARCH] wrote %s (%d lines)", run_path, written)
            rankings[key] = {q: list(v) for q, v in result.items()}
            searched += 1

        stats = pool_mod.pool_stats(rankings, queries, depth=args.depth)
        pool = pool_mod.build_pool(rankings, queries, depth=args.depth)
        pool_mod.log_pool(stats, pool)

        # Passages already fetched by an earlier invocation are reused rather
        # than re-read: the stored-fields file is ~1 TB, so every fetch is a real
        # disk seek, and a resumed sweep would otherwise pay for the whole pool
        # again to learn nothing new.
        texts = _read_pool_texts(run_dir / POOL_TEXTS_BASENAME)
        if args.fetch_texts:
            chunk_ids = sorted({cid for chunks in pool.values()
                                for cid in chunks})
            missing = [cid for cid in chunk_ids if cid not in (texts or {})]
            if missing:
                fetched = chunk_searcher.fetch_texts(missing)
                texts = {**(texts or {}), **fetched}
                written = extract.write_jsonl(
                    run_dir / POOL_TEXTS_BASENAME,
                    ({"chunk_id": cid, "text": texts[cid]}
                     for cid in sorted(texts)))
                log.info("[POOL] wrote %s (%d chunks, %d newly fetched) — "
                         "judge-pool reads passages from here, so it needs no "
                         "index and no JVM", run_dir / POOL_TEXTS_BASENAME,
                         written, len(fetched))
            else:
                log.info("[POOL] all %d pooled passages already in %s — nothing "
                         "to fetch", len(chunk_ids),
                         run_dir / POOL_TEXTS_BASENAME)
    finally:
        chunk_searcher.close()
    search_seconds = time.monotonic() - search_started

    entries = pool_mod.pool_entries(rankings, queries, depth=args.depth,
                                    texts=texts)
    pool_mod.write_pool(run_dir / POOL_BASENAME, entries)
    log.info("[POOL] wrote %s (%d rows)", run_dir / POOL_BASENAME,
             len(entries))

    manifest = {
        "run_id": run_id,
        "stage": stage,
        "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_sha": _git_sha(),
        "index_dir": str(index_dir),
        "query_count": len(queries),
        "topic_count": len({q.topic_id for q in queries}),
        "subsample_seed": SUBSAMPLE_SEED if stage == "A" else None,
        "subsample_size": len(queries) if stage == "A" else None,
        "grid": [[k1, b] for k1, b in configs],
        "depth": args.depth,
        "pool_stats": stats.to_json(),
        "pool_texts_fetched": 0 if texts is None else len(texts),
        "configs_searched": searched,
        "configs_skipped": skipped,
    }
    if searched:
        # Only a run that searched has a search time to report; a resumed run
        # would otherwise overwrite the real timing with 0.0s.
        manifest["timings"] = {"search_s": round(search_seconds, 1)}
    # A fully-resumed sweep never opens the index, so it knows neither the chunk
    # count nor a warmup time. Writing the unknowns would overwrite the real
    # values the original run recorded — the manifest is supposed to be the run's
    # provenance, so an unmeasured field is omitted rather than nulled.
    if chunk_searcher.num_docs is not None:
        manifest["index_num_docs"] = chunk_searcher.num_docs
    if chunk_searcher.warmup_seconds:
        manifest["warmup_s"] = round(chunk_searcher.warmup_seconds, 1)
    _write_manifest(run_dir, manifest, defaults={
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    log.info("[SUMMARY] stage=%s run_id=%s configs=%d (%d searched, %d "
             "skipped) queries=%d pool=%d pairs over %d topics in %.1fs",
             stage, run_id, len(configs), searched, skipped, len(queries),
             stats.unique_pairs, stats.topics, search_seconds)
    log.info("[SUMMARY] next: python -m bm25tune judge-pool --run-id %s "
             "--prompt-version <pv>", run_id)
    return EXIT_OK


def _read_pool_texts(path: Path) -> dict[str, str] | None:
    """`chunk_id -> text` from an existing `pool-texts.jsonl`, or `None`.

    Read on every sweep, for two reasons. It makes text fetching *incremental*,
    so a resumed sweep re-reads none of the ~1 TB stored-fields file for
    passages it already has. And it means `--no-fetch-texts` does not silently
    blank `pool.jsonl`'s `text_sha256` — those digests pin the passage a cached
    judgment was made on, so writing `null` over them disarms the check.

    Returning `None` for a missing file — rather than `{}` — matters:
    `pool_entries(texts={})` would write `text_sha256: null` for every row, which
    reads as "the passage has no digest" instead of "we did not look".
    """
    if not path.is_file():
        return None
    texts: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        texts[row["chunk_id"]] = row["text"]
    log.info("[POOL] %d passages already present in %s", len(texts), path)
    return texts


def _git_sha() -> str | None:
    """The repo's HEAD sha for the manifest, or `None` outside a checkout.

    Recorded so a published score matrix can be traced to the code that produced
    it. Read from `.git/` directly rather than by shelling out to `git`, which
    keeps the subcommand dependency-free and works when `git` is absent.
    """
    git_dir = Path(__file__).resolve().parents[3] / ".git"
    head = git_dir / "HEAD"
    if not head.is_file():
        return None
    text = head.read_text(encoding="utf-8").strip()
    if text.startswith("ref: "):
        ref = git_dir / text[5:]
        if not ref.is_file():
            packed = git_dir / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if line.endswith(" " + text[5:]):
                        return line.split()[0]
            return None
        return ref.read_text(encoding="utf-8").strip()
    return text or None


def _write_manifest(run_dir: Path, fields: dict,
                    defaults: dict | None = None) -> Path:
    """Merge `fields` into `runs/<id>/manifest.json` (PLAN §7.2).

    **Merges rather than overwrites**, because the manifest is written by three
    different stages — search, judge, score — each of which knows a different
    part of it. A stage that rewrote the file wholesale would erase the others'
    fields, and the manifest's promise is that a run can be audited from it
    alone. Written atomically for the same reason.

    `defaults` are written only if absent — for write-once provenance such as
    `created_utc`, which must keep saying when the run started rather than when it
    was last resumed.
    """
    path = run_dir / MANIFEST_BASENAME
    existing: dict = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("[SUMMARY] %s is not valid JSON; replacing it", path)
    for key, value in (defaults or {}).items():
        existing.setdefault(key, value)
    existing.update(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2, sort_keys=True,
                              default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def cmd_smoke(args: argparse.Namespace) -> int:
    """The live end-to-end check: 3 real index queries (+ 1 metered judgment).

    Exists because nothing else in the harness touches the real pyserini path:
    the offline suite injects a fake searcher (PLAN §7.3), so "does the JVM come
    up, is `JAVA_HOME` right, is the index the one we expect, does
    `doc(id).contents()` actually return text" is only ever answered here.

    `--search-only` is the WP2 half and calls **no** Bedrock API. The judgment
    half is WP3's; it must go through the metered path (`stage: "smoke"`), since
    the §5.7 accounting is only trustworthy if there is no unmetered way to reach
    Bedrock in this codebase.
    """
    cfg: Config = args.config
    index_dir = cfg.require_index_dir()
    if not args.search_only:
        # The judgment half spends, so the ceiling is demanded up front — not
        # after two minutes of JVM warm-up. `--search-only` is free and must keep
        # working with the variable unset, which is why this is conditional.
        cfg.require_budget_usd()
    queries = _smoke_queries(cfg, args.n)
    chunk_searcher = searcher_mod.ChunkSearcher(index_dir,
                                                threads=args.threads)
    try:
        warmup_s = chunk_searcher.warmup()
        chunk_searcher.set_config(*searcher_mod.BASELINE_CONFIG)
        result = chunk_searcher.run_config(queries, k=args.depth)
        top_ids = [ranking[0][0] for ranking in result.values() if ranking]
        texts = chunk_searcher.fetch_texts(top_ids) if top_ids else {}
    finally:
        chunk_searcher.close()

    log.info("[SUMMARY] index=%s num_docs=%s open=%.1fs warmup=%.1fs",
             index_dir, chunk_searcher.num_docs, chunk_searcher.open_seconds,
             warmup_s)
    empty = 0
    for rec in queries:
        ranking = result.get(rec.qkey) or []
        log.info("[SEARCH] %s %r -> %d hits", rec.qkey, rec.query,
                 len(ranking))
        if not ranking:
            empty += 1
            continue
        chunk_id, score = ranking[0]
        text = texts.get(chunk_id, "")
        log.info("[SEARCH]   top: %s score=%.4f parent=%s text=%d chars: %r",
                 chunk_id, score, extract.parent_docid(chunk_id), len(text),
                 text[:160])
        if not text:
            empty += 1
            log.error("[SEARCH]   NO TEXT for %s — `doc(id).contents()` "
                      "returned nothing. `.raw()` is unusable on this index, "
                      "so this breaks the judge's input entirely.", chunk_id)
    if empty:
        log.error("[SUMMARY] smoke FAILED: %d queries returned no hits or no "
                  "stored text", empty)
        return EXIT_ERROR
    log.info("[SUMMARY] search path OK: %d queries, all with hits and stored "
             "text", len(queries))

    if args.search_only:
        log.info("[SUMMARY] --search-only: no Bedrock call made, $0 spent")
        return EXIT_OK
    raise NotImplementedYet(
        "the judgment half of `smoke` is not yet implemented (WP3 + WP3b). "
        "Intended behaviour: one real, metered Converse call recorded with "
        'stage="smoke" so there is no unmetered path to Bedrock (PLAN §5.6). '
        "The search half above passed — re-run with --search-only for the "
        "live check WP2 owns.")


def _smoke_queries(cfg: Config, n: int) -> list[extract.QueryRec]:
    """`n` real queries for the smoke test, spread across topics.

    Prefers the persisted query set so the smoke test exercises exactly the
    strings the sweep will run; falls back to literal keyword queries so `smoke`
    works before `extract-queries` has ever been run (which is when a fresh
    clone most wants to check its JVM and index wiring). Spread across topics,
    not the first `n` rows, because a topic's queries are near-duplicates and
    would all fault in the same postings.
    """
    path = cfg.queries_dir / QUERIES_FULL_BASENAME
    if path.is_file():
        queries = extract.read_query_file(path)
        by_topic: dict[str, extract.QueryRec] = {}
        for rec in queries:
            by_topic.setdefault(rec.topic_id, rec)
        picked = list(by_topic.values())
        step = max(len(picked) // max(n, 1), 1)
        chosen = picked[::step][:n]
        if chosen:
            log.info("[LOAD] %d smoke queries from %s", len(chosen), path)
            return chosen
    log.info("[LOAD] %s not found — using %d built-in smoke queries", path, n)
    return [extract.QueryRec.make(f"smoke-{i}", "smoke test", query, 0)
            for i, query in enumerate(SMOKE_FALLBACK_QUERIES[:n])]


# ---------------------------------------------------------------------------
# judge-pool / rebuild-cache  (WP3, PLAN §5.3, §5.4, §5.6, §5.8)
# ---------------------------------------------------------------------------
#: `--pilot` with no value (PLAN §5.7 fixes the default at 200).
DEFAULT_PILOT_N = 200

#: Fraction of pooled pairs that must have a passage in `pool-texts.jsonl`
#: before judging starts. Not in the plan — `pool-texts.jsonl` is an artifact
#: WP2 added — but a partially fetched sidecar is a *scoring* hazard rather than
#: a judging one: chunks with no text are silently unjudged, which deflates
#: judged@10 for every config uniformly, and by the time that is visible in the
#: report the calls have been paid for. 99 % leaves room for a handful of
#: genuinely empty chunks without tolerating a truncated file.
MIN_POOL_TEXT_COVERAGE = 0.99


def _stage_for_run(run_id: str, manifest: dict) -> str:
    """The `stage` recorded in every judgment record's billing metadata.

    Read from the sweep's own `manifest.json` first, because that is what
    actually produced the pool; the `-stage<X>` suffix of the run id is only a
    fallback. Getting this wrong does not corrupt a judgment (the cache key does
    not include it, deliberately — PLAN §5.3) but it does mis-attribute spend in
    `costs.md`'s per-stage split, which is a figure the report publishes.
    """
    stage = manifest.get("stage")
    if isinstance(stage, str) and stage:
        return stage
    marker = "-stage"
    if marker in run_id:
        tail = run_id.rsplit(marker, 1)[1]
        if tail:
            return tail
    return "?"


def _topic_context(cfg: Config, override: Path | None
                   ) -> dict[str, tuple[str, str]]:
    """`topic_id -> (narrative, representative_keyword)` for prompt rendering.

    The narrative is the judge target for the three narrative-slot variants
    (PLAN §0) and is read from the persisted query file rather than the labeled
    input, so what was judged is traceable to an artifact.

    The keyword is a **representative** one, chosen as the topic's
    lowest-sorting `qkey` so it is deterministic across re-extractions. It only
    reaches a prompt under `umbrela-kw-v1`, whose `query_slot` is `keyword` —
    and there is an unavoidable tension there, flagged loudly at the call site:
    the judgment cache key is topic-level (PLAN §5.3), so a *pooled* run cannot
    hold one judgment per (query, chunk). `umbrela-kw-v1` is a §3.2 calibration
    diagnostic, where pairs carry their own query; using it for `judge-pool`
    means judging every chunk of a topic against one of that topic's 3-16
    queries.
    """
    path = override
    if path is None:
        for basename in (QUERIES_FULL_BASENAME, QUERIES_SUBSAMPLE_BASENAME):
            candidate = cfg.queries_dir / basename
            if candidate.is_file():
                path = candidate
                break
    if path is None:
        raise ConfigError(
            f"no query file under {cfg.queries_dir} — run `python -m bm25tune "
            "extract-queries` first; judge-pool needs the topic narratives it "
            "persists (they are the judge target, PLAN §0)")
    context: dict[str, tuple[str, str]] = {}
    best_qkey: dict[str, str] = {}
    for rec in extract.read_query_file(Path(path)):
        previous = best_qkey.get(rec.topic_id)
        if previous is None or rec.qkey < previous:
            best_qkey[rec.topic_id] = rec.qkey
            context[rec.topic_id] = (rec.topic, rec.query)
    log.info("[LOAD] narratives for %d topics from %s", len(context), path)
    return context


def _load_judge_pairs(cfg: Config, args: argparse.Namespace, run_dir: Path
                      ) -> list["judge_mod.JudgePair"]:
    """Build the `JudgePair` list from WP2's `pool.jsonl` + `pool-texts.jsonl`.

    `judge-pool` deliberately reads **only JSONL**: the passages come from the
    sweep's sidecar, so the multi-hour judging job never opens the 1.5 TB index
    and needs no JVM (PLAN §5.5). It also means the text a judgment was made on
    is an artifact rather than a re-query, which is what makes a cached judgment
    auditable.

    A `text_sha256` in `pool.jsonl` that disagrees with the sidecar is a **hard
    error**, not a warning: it means the two halves of one sweep describe
    different passages, so every judgment made from them would be attributed to
    text that was never sent.

    A *partial* sidecar is a hard error too, below `MIN_POOL_TEXT_COVERAGE` —
    see that constant for why a missing passage is a scoring problem rather than
    a judging one.
    """
    from . import judge as judge_mod

    pool_path = run_dir / POOL_BASENAME
    texts_path = run_dir / POOL_TEXTS_BASENAME
    if not pool_path.is_file():
        raise ConfigError(
            f"{pool_path} not found — run `python -m bm25tune search-sweep "
            f"--stage <A|B> --run-id {run_dir.name}` first (judging consumes "
            "the pool that sweep writes)")
    if not texts_path.is_file():
        raise ConfigError(
            f"{texts_path} not found — the sweep was run with "
            "--no-fetch-texts, so no passages were saved and there is nothing "
            "to send to the judge. Re-run search-sweep without that flag "
            "(already-written run files are skipped, so it only fetches text).")
    entries = pool_mod.read_pool(pool_path)
    texts: dict[str, str] = {}
    for row in extract.iter_rows(texts_path):
        texts[str(row["chunk_id"])] = str(row.get("text") or "")
    log.info("[POOL] %d pooled pairs, %d passage texts from %s", len(entries),
             len(texts), run_dir)

    context = _topic_context(cfg, args.queries)
    pairs: list[judge_mod.JudgePair] = []
    missing_text: list[str] = []
    missing_topic: list[str] = []
    digest_mismatch: list[str] = []
    for entry in entries:
        narrative_keyword = context.get(entry.topic_id)
        if narrative_keyword is None:
            missing_topic.append(entry.topic_id)
            continue
        text = texts.get(entry.chunk_id, "")
        if not text:
            missing_text.append(entry.chunk_id)
            continue
        if entry.text_sha256 and extract.sha256_text(text) != entry.text_sha256:
            digest_mismatch.append(entry.chunk_id)
            continue
        narrative, keyword = narrative_keyword
        pairs.append(judge_mod.JudgePair(
            topic_id=entry.topic_id, chunk_id=entry.chunk_id,
            narrative=narrative, keyword=keyword, passage_text=text))
    if digest_mismatch:
        raise ConfigError(
            f"{len(digest_mismatch)} pooled chunk(s) have a text_sha256 in "
            f"{pool_path} that disagrees with {texts_path} (e.g. "
            f"{digest_mismatch[:3]}). The two halves of one sweep describe "
            "different passages, so judging them would record grades against "
            "text that was never sent. Re-run search-sweep for this run id.")
    if missing_topic:
        raise ConfigError(
            f"{len(missing_topic)} pooled pair(s) name topics absent from the "
            f"query file (e.g. {sorted(set(missing_topic))[:3]}) — the pool and "
            "the query set come from different extractions, so the narratives "
            "would be wrong. Re-run extract-queries and the sweep.")
    if missing_text:
        log.error("[POOL] %d pooled chunk(s) have no stored text and CANNOT be "
                  "judged (e.g. %s) — they will score as unjudged, deflating "
                  "judged@10 for every config", len(missing_text),
                  missing_text[:3])
    if not pairs:
        raise ConfigError(
            f"no judgeable pairs in {pool_path} (every pooled chunk lacked "
            "text or a narrative); nothing would be judged and nothing spent")
    coverage = len(pairs) / len(entries) if entries else 0.0
    if coverage < MIN_POOL_TEXT_COVERAGE and not getattr(
            args, "allow_partial_texts", False):
        raise ConfigError(
            f"only {len(pairs)}/{len(entries)} pooled pairs ({coverage:.1%}) "
            f"have a passage in {texts_path} — under the "
            f"{MIN_POOL_TEXT_COVERAGE:.0%} floor. A truncated or partially "
            "fetched sidecar is not a judging problem, it is a scoring one: "
            "the unjudged chunks silently deflate judged@10 for EVERY config, "
            "which is the metric this experiment tunes on, and the money would "
            "already be spent by the time that showed up. Re-run search-sweep "
            f"for {run_dir.name} (already-written run files are skipped) or "
            "pass --allow-partial-texts if the gap is understood.")
    log.info("[POOL] %d/%d pooled pairs judgeable (%.1f%% text coverage)",
             len(pairs), len(entries), 100.0 * coverage)
    return pairs


def cmd_judge_pool(args: argparse.Namespace) -> int:
    """Judge the pooled pairs with the Bedrock judge — the long, resumable job.

    The whole of WP3 funnels through here, and the order of operations below is
    the safety argument:

    1. **Metering first.** `judge.load_pricing()` runs before a client exists, so
       a missing/incomplete `pricing.py` stops the run instead of judging
       un-metered (PLAN §9: there must be no unmetered path to the model).
    2. **Reconcile the ledger against the log** — the log is authoritative, so a
       crash window heals here rather than silently under-counting the cap.
    3. **Cache consult, then pre-flight.** The estimate counts the calls that
       will actually be made, not the size of the pool; a 95 %-cached resume must
       not be refused on a 20x estimate. A refusal raises `BudgetRefused` →
       exit 4, before anything is spent.
    4. **Signal handlers, then the driver.** Every stop path — cred expiry (3),
       budget (5), SIGINT (130), SIGTERM (143) — and normal completion run the
       *same* `drain_and_checkpoint` (PLAN §5.8).

    Resume is always "re-run the same command": every completed judgment is in
    the cache and will not be re-billed.
    """
    from . import judge as judge_mod
    from .store import (JudgmentCache, JudgmentLog, cache_snapshot_path,
                        rename_superseded)

    cfg: Config = args.config
    try:
        pricing_mod = judge_mod.load_pricing()
    except judge_mod.PricingUnavailable as exc:
        log.error("[BUDGET] %s", exc)
        return EXIT_ERROR
    # Resolved HERE, before the pool is loaded and the cache replayed, for the
    # same reason step 1 loads pricing first: no path to the model may exist that
    # is not bounded by a ceiling the operator set this run. Failing after two
    # minutes of cache replay would also train people to skip reading it.
    cap_usd = cfg.require_budget_usd()

    spec = get_prompt(args.prompt_version)
    run_id = args.run_id or _default_run_id("A")
    run_dir = cfg.run_dir(run_id)
    _guard_derived_path(cfg, run_dir, "judge-pool --run-id")
    manifest: dict = {}
    manifest_path = run_dir / MANIFEST_BASENAME
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("[LOAD] %s is not valid JSON; stage will be derived "
                        "from the run id", manifest_path)
    stage = args.stage or _stage_for_run(run_id, manifest)
    cfg.ensure_dirs(run_dir, cfg.log_dir, cfg.cache_dir, cfg.costs_dir)
    setup_logging(args.log_file or (run_dir / SWEEP_LOG_BASENAME),
                  level=logging.DEBUG if args.verbose else logging.INFO)
    log.info("[LOAD] judge-pool run_id=%s stage=%s prompt_version=%s "
             "concurrency=%d", run_id, stage, spec.version_id,
             args.concurrency or cfg.judge_concurrency)
    if spec.query_slot == "keyword":
        log.warning("[JUDGE] prompt_version=%s puts the KEYWORD query in {q}, "
                    "but the judgment cache key is topic-level (PLAN §5.3): "
                    "every chunk of a topic will be judged against one "
                    "representative query of that topic, not against the query "
                    "that retrieved it. %s is a §3.2 calibration diagnostic; "
                    "prefer a narrative-slot version for a pooled sweep.",
                    spec.version_id, spec.version_id)

    rates = _load_rates_or_fail(cfg)
    if rates is None:
        return EXIT_ERROR
    pairs = _load_judge_pairs(cfg, args, run_dir)
    pool_size = len(pairs)
    if args.pilot:
        pairs = judge_mod.sample_pairs(pairs, args.pilot)
        log.info("[JUDGE] --pilot %d: judging %d of %d pooled pairs, sampled "
                 "evenly across topics (seed 13); their judgments are cached, "
                 "so the pilot costs nothing extra", args.pilot, len(pairs),
                 pool_size)

    snapshot_path = cache_snapshot_path(cfg.cache_dir, spec.version_id)
    if args.fresh:
        # Scoped to the ONE derived artifact judge-pool owns. Not the run dir:
        # that holds `pool.jsonl`, which is this command's *input*. Not the log
        # or the ledger: `rename_superseded` refuses those outright (PLAN §5.8).
        rename_superseded(snapshot_path, log_dir=cfg.log_dir,
                          costs_dir=cfg.costs_dir)
    cache = JudgmentCache.load(cfg.log_dir, prompt_version=spec.version_id,
                               snapshot_path=snapshot_path)
    log.info("[CACHE] %d graded pairs known for %s (snapshot_used=%s, %d "
             "segments, %d records replayed, %d truncated tail(s))",
             len(cache), spec.version_id, cache.stats.snapshot_used,
             cache.stats.segments, cache.stats.records,
             cache.stats.truncated_tails)

    meter = pricing_mod.CostMeter.load(cfg.costs_dir)
    meter.reconcile(cfg.log_dir)
    concurrency = args.concurrency or cfg.judge_concurrency
    guard = pricing_mod.BudgetGuard(meter, cap_usd, concurrency,
                                    rates=rates)
    pending, cache_hits = judge_mod.pending_pairs(pairs, cache,
                                                  spec.version_id)
    estimate = guard.preflight(len(pending), stage=stage)

    log_store = JudgmentLog(cfg.log_dir)
    driver = judge_mod.JudgePoolDriver(
        judge=judge_mod.BedrockJudge(cfg.judge_model, cfg.judge_region,
                                     max_pool_connections=concurrency),
        spec=spec, log_store=log_store, cache=cache, meter=meter, guard=guard,
        rates=rates, pricing_mod=pricing_mod, run_id=run_id, stage=stage,
        concurrency=concurrency, snapshot_path=snapshot_path, run_dir=run_dir)
    spent_before = meter.spent_usd()
    driver.install_signal_handlers()
    try:
        code = driver.run(pairs)
    finally:
        driver.restore_signal_handlers()

    _write_judge_manifest(run_dir, driver, spec, stage, estimate, pool_size,
                          pricing_mod, spent_before)
    if args.pilot:
        basis = pricing_mod.pilot_basis(
            driver.usages, rates, pool_size=pool_size, meter=meter,
            cap_usd=cap_usd)
        log.info("%s", pricing_mod.format_pilot_basis(basis))
        log.info("[SUMMARY] --pilot stops here BY DESIGN (PLAN §5.7): paste the "
                 "[COST] line above into chat and get the full run authorized "
                 "before launching it.")
    log.info("[SUMMARY] cache hits at start: %d/%d; qrels snapshot: %s",
             cache_hits, len(pairs), snapshot_path)
    log.info("[SUMMARY] next: python -m bm25tune score --run-id %s "
             "--prompt-version %s", run_id, spec.version_id)
    return code


def _write_judge_manifest(run_dir: Path, driver, spec, stage: str,
                          estimate: dict, pool_size: int, pricing_mod,
                          spent_before: float) -> None:
    """Merge the judging stage's fields into `runs/<id>/manifest.json`.

    Merged, not written wholesale, because `search-sweep` already put its half
    there and `score` will add a third (PLAN §7.2). The cost block comes from
    WP3b's `manifest_cost_fields` so the manifest and `costs.md` are two
    renderings of one dict rather than two implementations of the same
    arithmetic.
    """
    fields: dict[str, object] = {
        "judge": {
            "prompt_version": spec.version_id,
            "prompt_template_sha256": spec.template_sha256,
            "query_slot": spec.query_slot,
            "model_id": driver.judge.model_id,
            "region": driver.judge.region,
            "max_tokens": driver.judge.max_tokens,
            "temperature": driver.judge.temperature,
            "concurrency": driver.concurrency,
            "pool_size": pool_size,
            **driver.stats.to_json(),
        },
        "cache": {"hits": driver.stats.cache_hits,
                  "entries": len(driver.cache)},
        "budget": {"preflight": estimate},
    }
    try:
        report = pricing_mod.build_cost_report(
            driver.log_store.log_dir, driver.meter,
            cap_usd=driver.guard.cap_usd, run_id=driver.run_id,
            cache_hits=driver.stats.cache_hits, rates=driver.rates)
        fields.update(pricing_mod.manifest_cost_fields(
            report, cap_usd=driver.guard.cap_usd,
            spent_before_usd=spent_before,
            preflight_estimate_usd=estimate.get("est_usd"),
            tripped=driver.stats.trigger == "budget"))
    except Exception:  # noqa: BLE001 - the manifest must never lose the run
        log.exception("[COST] could not build the manifest's cost block; "
                      "regenerate it with `cost-report --run-id %s`",
                      driver.run_id)
    _write_manifest(run_dir, fields)


# ---------------------------------------------------------------------------
# calibrate (WP6 / WP0) — PLAN §3.3
# ---------------------------------------------------------------------------
def _calibration_pairs(cfg: Config, args: argparse.Namespace
                       ) -> tuple[list["judge_mod.JudgePair"],
                                  dict[str, str], Path]:
    """Persist `calibration/sample-280.jsonl` and build its `JudgePair`s.

    Unlike `judge-pool`, calibration reads the **historical** hit text straight
    out of the labeled file (`ObservedHit.text`, already prefix-stripped): the
    sample is drawn from what aus_agent actually saw, so it needs neither the
    sweep's pool nor the 1.5 TB index (PLAN §3.1). Persisted once, so every
    variant judges byte-identical pairs and the sampler's seed is auditable.

    Returns `(pairs, agent_class_by_chunk, sample_path)` — the class map is the
    stratum each pair's chunk belongs to, which the agreement smell test needs
    but the `JudgePair` deliberately does not carry (it is agent metadata, not
    judge input).
    """
    from . import judge as judge_mod

    hits = extract.load_observed_hits(cfg.input_file)
    sample = extract.calibration_sample(hits, n=args.n, seed=args.seed)
    cfg.ensure_dirs(cfg.calibration_dir)
    sample_path = cfg.calibration_dir / CALIBRATION_SAMPLE_BASENAME
    extract.write_jsonl(sample_path, (hit.to_json() for hit in sample))
    log.info("[CALIB] wrote %d/%d requested calibration pairs to %s (seed %d)",
             len(sample), args.n, sample_path, args.seed)

    context = _topic_context(cfg, args.queries)
    pairs: list[judge_mod.JudgePair] = []
    agent_class: dict[str, str] = {}
    missing_topic: list[str] = []
    for hit in sample:
        narrative_keyword = context.get(hit.topic_id)
        if narrative_keyword is None:
            missing_topic.append(hit.topic_id)
            continue
        narrative, keyword = narrative_keyword
        pairs.append(judge_mod.JudgePair(
            topic_id=hit.topic_id, chunk_id=hit.chunk_id,
            narrative=narrative, keyword=keyword, passage_text=hit.text))
        agent_class[hit.chunk_id] = hit.agent_class
    if missing_topic:
        raise ConfigError(
            f"{len(missing_topic)} calibration pair(s) name topics absent from "
            f"the query file (e.g. {sorted(set(missing_topic))[:3]}) — the "
            "sample and the query set come from different extractions. Re-run "
            "`extract-queries` so the narratives match.")
    if not pairs:
        raise ConfigError(
            "no judgeable calibration pairs — every sampled hit lacked a "
            "narrative; nothing would be judged and nothing spent")
    return pairs, agent_class, sample_path


def _judge_variant(cfg: Config, args: argparse.Namespace, spec,
                   pairs: Sequence["judge_mod.JudgePair"], *,
                   rates, pricing_mod, meter, cap_usd: float,
                   concurrency: int) -> int:
    """Judge every calibration pair under one prompt variant; return the exit code.

    A thin wrapper over the same `JudgePoolDriver` `judge-pool` uses — the whole
    point is that calibration bills, meters, checkpoints, resumes, and drains
    through *exactly* the audited path, never a second implementation. The
    shared `meter` is threaded through all five variants so the running total
    (and the budget guard) span the whole calibration, and the `calib` stage
    keeps that spend on its own line in `costs/totals.json`.
    """
    from . import judge as judge_mod
    from .store import (JudgmentCache, JudgmentLog, cache_snapshot_path,
                        rename_superseded)

    snapshot_path = cache_snapshot_path(cfg.cache_dir, spec.version_id)
    if args.fresh:
        rename_superseded(snapshot_path, log_dir=cfg.log_dir,
                          costs_dir=cfg.costs_dir)
    cache = JudgmentCache.load(cfg.log_dir, prompt_version=spec.version_id,
                               snapshot_path=snapshot_path)
    guard = pricing_mod.BudgetGuard(meter, cap_usd, concurrency, rates=rates)
    pending, cache_hits = judge_mod.pending_pairs(pairs, cache, spec.version_id)
    guard.preflight(len(pending), stage=CALIBRATION_STAGE)
    log.info("[CALIB] %s: %d/%d pairs cached, %d to judge", spec.version_id,
             cache_hits, len(pairs), len(pending))

    driver = judge_mod.JudgePoolDriver(
        judge=judge_mod.BedrockJudge(cfg.judge_model, cfg.judge_region,
                                     max_pool_connections=concurrency),
        spec=spec, log_store=JudgmentLog(cfg.log_dir), cache=cache, meter=meter,
        guard=guard, rates=rates, pricing_mod=pricing_mod,
        run_id="calibrate", stage=CALIBRATION_STAGE, concurrency=concurrency,
        snapshot_path=snapshot_path, run_dir=None)
    driver.install_signal_handlers()
    try:
        return driver.run(list(pairs))
    finally:
        driver.restore_signal_handlers()


def _variant_result(cfg: Config, spec, pairs: Sequence["judge_mod.JudgePair"],
                    agent_class: Mapping[str, str], *, rates, pricing_mod
                    ) -> "calib.VariantResult":
    """Read this variant's cached grades back into a `VariantResult` for the gate.

    Reads from the cache snapshot (the log's replayable index), NOT from the
    driver's in-memory state, so a resumed calibration whose grades were written
    on an earlier invocation is scored identically to one judged in a single
    run. Missing grades (a pair the budget stop never reached) are simply absent
    from the histogram, which the `judged` count in the log surfaces separately.
    """
    from .store import JudgmentCache, cache_snapshot_path, jkey

    cache = JudgmentCache.load(
        cfg.log_dir, prompt_version=spec.version_id,
        snapshot_path=cache_snapshot_path(cfg.cache_dir, spec.version_id))
    grades_by_class: dict[str, list[int]] = {}
    counts_by_class: dict[str, dict[int, int]] = {}
    for pair in pairs:
        grade = cache.get(jkey(spec.version_id, pair.topic_id, pair.chunk_id))
        if grade is None:
            continue
        cls = agent_class.get(pair.chunk_id, "unjudged")
        grades_by_class.setdefault(cls, []).append(grade)
    all_grades = [g for gs in grades_by_class.values() for g in gs]
    for cls, gs in grades_by_class.items():
        counts_by_class[cls] = calib.counts_from_grades(gs)

    cost = _variant_cost_from_log(cfg, spec.version_id, rates, pricing_mod)
    return calib.VariantResult(
        prompt_version=spec.version_id,
        gate=calib.evaluate_gate(calib.counts_from_grades(all_grades)),
        agreement=calib.agent_agreement(grades_by_class),
        counts_by_class=counts_by_class,
        parse_failures=cost["parse_failures"], calls=cost["calls"],
        input_tokens=cost["input_tokens"], output_tokens=cost["output_tokens"],
        cost_usd=cost["cost_usd"])


def _variant_cost_from_log(cfg: Config, version_id: str, rates, pricing_mod
                           ) -> dict:
    """Sum this variant's billed calls / tokens / cost straight from the log.

    The judgment log is the ground truth for spend (PLAN §5.3), so the report's
    per-variant cost is summed here rather than carried out of the driver — a
    resumed calibration then reports the *total* cost of a variant across every
    invocation that judged it, not just the last one.
    """
    calls = parse_failures = input_tokens = output_tokens = 0
    cost_usd = 0.0
    for record in pricing_mod.iter_log_records(cfg.log_dir):
        if record.get("prompt_version") != version_id:
            continue
        if record.get("stage") != CALIBRATION_STAGE:
            continue
        usage = record.get("usage")
        if usage:
            calls += 1
            input_tokens += int(usage.get("inputTokens") or 0)
            output_tokens += int(usage.get("outputTokens") or 0)
        cost = record.get("cost")
        if cost:
            cost_usd += float(cost.get("usd") or 0.0)
        if record.get("error") == "parse_failure":
            parse_failures += 1
    return {"calls": calls, "parse_failures": parse_failures,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cost_usd": cost_usd}


def _stability_probe(cfg: Config, args: argparse.Namespace, spec,
                     pairs: Sequence["judge_mod.JudgePair"], *,
                     rates, pricing_mod, meter, cap_usd: float,
                     concurrency: int) -> tuple[float | None, int]:
    """Re-judge N pairs of the winner, **bypassing the cache**, return match rate.

    PLAN §3.3: the probe measures whether the judge is stable at temperature 0.
    It MUST NOT consult the cache — a cache hit would trivially report 1.000 —
    so it runs against a *fresh, empty* `JudgmentCache` and writes to a probe
    stage (`calib-probe`) so its records never seed the winner's qrels snapshot.
    The comparison is against the winner's committed grades, read from that
    snapshot before the probe runs.
    """
    from . import judge as judge_mod
    from .store import (JudgmentCache, JudgmentLog, cache_snapshot_path, jkey)

    n = min(args.stability_pairs, len(pairs))
    if n <= 0:
        return None, 0
    probe_pairs = judge_mod.sample_pairs(list(pairs), n)
    committed = JudgmentCache.load(
        cfg.log_dir, prompt_version=spec.version_id,
        snapshot_path=cache_snapshot_path(cfg.cache_dir, spec.version_id))
    baseline = {p.chunk_id: committed.get(
        jkey(spec.version_id, p.topic_id, p.chunk_id)) for p in probe_pairs}

    guard = pricing_mod.BudgetGuard(meter, cap_usd, concurrency, rates=rates)
    guard.preflight(len(probe_pairs), stage="calib-probe")
    # A fresh empty cache and snapshot_path=None: nothing is read from or written
    # to the winner's qrels, so the re-judge is genuinely fresh and cannot
    # pollute the calibration the report is about to declare the winner.
    probe_cache = JudgmentCache(prompt_version=spec.version_id)
    driver = judge_mod.JudgePoolDriver(
        judge=judge_mod.BedrockJudge(cfg.judge_model, cfg.judge_region,
                                     max_pool_connections=concurrency),
        spec=spec, log_store=JudgmentLog(cfg.log_dir), cache=probe_cache,
        meter=meter, guard=guard, rates=rates, pricing_mod=pricing_mod,
        run_id="calibrate", stage="calib-probe", concurrency=concurrency,
        snapshot_path=None, run_dir=None)
    log.info("[CALIB] stability probe: re-judging %d pair(s) of %s "
             "(cache-bypassing)", len(probe_pairs), spec.version_id)
    driver.install_signal_handlers()
    try:
        driver.run(probe_pairs)
    finally:
        driver.restore_signal_handlers()

    matches = compared = 0
    for pair in probe_pairs:
        before = baseline.get(pair.chunk_id)
        after = probe_cache.get(jkey(spec.version_id, pair.topic_id,
                                     pair.chunk_id))
        if before is None or after is None:
            continue
        compared += 1
        if before == after:
            matches += 1
    rate = matches / compared if compared else None
    log.info("[CALIB] stability: %d/%d exact matches (rate=%s)", matches,
             compared, f"{rate:.3f}" if rate is not None else "n/a")
    return rate, compared


def cmd_calibrate(args: argparse.Namespace) -> int:
    """WP6/WP0 judge calibration: the mandatory gate before any sweep spend.

    The order below is the safety argument, mirroring `judge-pool` (PLAN §5.7):

    1. **Pricing, then the cap, before anything is judged.** No path to the model
       may exist that is not bounded by the operator-set ceiling
       (`BM25_TUNE_BUDGET_USD`, no default — PLAN §0). One shared `CostMeter`
       spans all five variants and the probe, so the budget guard sees the whole
       calibration's spend, not each variant's in isolation.
    2. **Judge every registered variant on the same persisted sample.** Each runs
       through the audited `JudgePoolDriver`, so calibration bills, checkpoints,
       resumes, and drains through exactly the path the sweep uses.
    3. **Decide, then probe the winner.** The gate (`calib.decide`) picks the
       lowest-modal-share passing variant; only then is the stability probe run,
       and only on that winner (PLAN §3.3), so the ~50 extra calls are not spent
       on variants that failed the gate anyway.
    4. **Write the report, then set the exit code from the gate.** Exit 6 when no
       variant passes, so the launching agent escalates to the user rather than
       auto-starting the sweep (PLAN §3.3 fallback). The report is written on
       *both* paths — a gated calibration still produces the artifact the user
       reviews.

    Resume is "re-run the same command": every completed judgment is cached and
    will not be re-billed; the sample file and its seed are pinned.
    """
    from . import judge as judge_mod

    cfg: Config = args.config
    try:
        pricing_mod = judge_mod.load_pricing()
    except judge_mod.PricingUnavailable as exc:
        log.error("[BUDGET] %s", exc)
        return EXIT_ERROR
    cap_usd = cfg.require_budget_usd()
    rates = _load_rates_or_fail(cfg)
    if rates is None:
        return EXIT_ERROR

    cfg.ensure_dirs(cfg.calibration_dir, cfg.log_dir, cfg.cache_dir,
                    cfg.costs_dir)
    setup_logging(args.log_file or (cfg.calibration_dir /
                                    CALIBRATION_LOG_BASENAME),
                  level=logging.DEBUG if args.verbose else logging.INFO)
    concurrency = args.concurrency or cfg.judge_concurrency
    log.info("[CALIB] calibrating %d variants at concurrency %d, cap $%.2f",
             len(all_versions()), concurrency, cap_usd)

    pairs, agent_class, sample_path = _calibration_pairs(cfg, args)
    sample_mix = Counter(agent_class.values())

    meter = pricing_mod.CostMeter.load(cfg.costs_dir)
    meter.reconcile(cfg.log_dir)

    results: list[calib.VariantResult] = []
    stop_code = EXIT_OK
    for version_id in all_versions():
        spec = get_prompt(version_id)
        if spec.query_slot == "keyword":
            log.warning("[CALIB] %s puts the KEYWORD query in {q}; on the "
                        "topic-level cache key every chunk of a topic is judged "
                        "against one representative query (PLAN §5.3). It is a "
                        "§3.2 diagnostic — measured here, not a sweep judge.",
                        version_id)
        code = _judge_variant(cfg, args, spec, pairs, rates=rates,
                              pricing_mod=pricing_mod, meter=meter,
                              cap_usd=cap_usd, concurrency=concurrency)
        results.append(_variant_result(cfg, spec, pairs, agent_class,
                                       rates=rates, pricing_mod=pricing_mod))
        for line in calib.gate_log_lines(results[-1]):
            log.info("%s", line)
        if code in (EXIT_BUDGET_STOP, EXIT_CRED_EXPIRY, EXIT_SIGINT,
                    EXIT_SIGTERM):
            # A stop mid-calibration is not a gate failure: report what we have
            # and propagate the driver's code so resume semantics hold.
            log.error("[CALIB] variant %s stopped (exit %d) — writing a partial "
                      "report and stopping; re-run to resume", version_id, code)
            stop_code = code
            break

    decision = calib.decide(results)
    if stop_code == EXIT_OK and decision.winner is not None \
            and args.stability_pairs > 0:
        winner_spec = get_prompt(decision.winner)
        rate, probed = _stability_probe(
            cfg, args, winner_spec, pairs, rates=rates,
            pricing_mod=pricing_mod, meter=meter, cap_usd=cap_usd,
            concurrency=concurrency)
        results = [
            calib.VariantResult(
                **{**vars(r), "stability_match_rate": rate,
                   "stability_pairs": probed})
            if r.prompt_version == decision.winner else r
            for r in results]
        decision = calib.decide(results)

    _write_calibration_report(cfg, results, decision, sample_path=sample_path,
                              n_pairs=len(pairs), sample_mix=sample_mix)

    if stop_code != EXIT_OK:
        return stop_code
    if decision.gated:
        log.error("[GATE] no variant passed — exit %d. The sweep must NOT "
                  "launch. Review %s and confirm with the user (PLAN §3.3).",
                  EXIT_GATE_FAILED,
                  cfg.calibration_dir / CALIBRATION_REPORT_MD)
        return EXIT_GATE_FAILED
    log.info("[GATE] PASS — recommended judge: %s. Review %s and confirm the "
             "prompt version before launching the sweep (PLAN §3.3).",
             decision.winner, cfg.calibration_dir / CALIBRATION_REPORT_MD)
    return EXIT_OK


def _write_calibration_report(cfg: Config,
                              results: Sequence["calib.VariantResult"],
                              decision: "calib.Decision", *, sample_path: Path,
                              n_pairs: int, sample_mix: Mapping[str, int]
                              ) -> None:
    """Render `calibration/report.{md,json}` — the artifacts the user reviews.

    Both are written from the same `results`: the markdown is what a human reads,
    the JSON is what a launching agent branches on without re-parsing prose.
    """
    md = calib.render_report_md(
        results, decision, run_id="calibrate", sample_path=str(sample_path),
        n_pairs=n_pairs, sample_label_mix=dict(sample_mix),
        model_id=cfg.judge_model, region=cfg.judge_region)
    md_path = cfg.calibration_dir / CALIBRATION_REPORT_MD
    md_path.write_text(md, encoding="utf-8")

    payload = {
        "run_id": "calibrate",
        "sample_path": str(sample_path),
        "n_pairs": n_pairs,
        "sample_label_mix": dict(sample_mix),
        "pool_label_mix": dict(calib.POOL_LABEL_MIX),
        "winner": decision.winner,
        "best_effort": decision.best_effort,
        "gated": decision.gated,
        "passing": list(decision.passing),
        "ranked": list(decision.ranked),
        "rationale": decision.rationale,
        "variants": [{
            "prompt_version": r.prompt_version,
            "passed": r.gate.passed,
            "counts": r.gate.counts,
            "modal_grade": r.gate.modal_grade,
            "modal_share": r.gate.modal_share,
            "share_ge2": r.gate.share_ge2,
            "share_eq3": r.gate.share_eq3,
            "entropy": r.gate.entropy,
            "pool_share_ge2": r.pool_share_ge2,
            "failed_conditions": [{"name": c.name, "observed": c.observed,
                                   "direction": c.direction, "bound": c.bound}
                                  for c in r.gate.failures],
            "auc": r.agreement.auc,
            "mean_by_class": r.agreement.mean_by_class,
            "n_by_class": r.agreement.n_by_class,
            "stability_match_rate": r.stability_match_rate,
            "stability_pairs": r.stability_pairs,
            "calls": r.calls,
            "parse_failures": r.parse_failures,
            "cost_usd": r.cost_usd,
        } for r in results],
    }
    json_path = cfg.calibration_dir / CALIBRATION_REPORT_JSON
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True),
                         encoding="utf-8")
    log.info("[CALIB] wrote %s and %s", md_path, json_path)


def cmd_rebuild_cache(args: argparse.Namespace) -> int:
    """Full rescan of the append-only judgment log into fresh cache snapshots.

    The cache is *always* rebuildable from the log — that is the point of the
    split (PLAN §5.3) — so this is the answer to a lost, stale, or corrupt
    snapshot, and the tool `--fresh` names when someone points it at
    `judgments/log/`. It reads the log and writes only snapshots: **no Bedrock,
    no spend, nothing destroyed**.

    One streaming pass fans out by `prompt_version`, so rebuilding all four
    variants costs one read of a log that embeds every passage's full text
    rather than four.
    """
    from .store import cache_snapshot_path, rebuild_all

    cfg: Config = args.config
    caches = rebuild_all(cfg.log_dir)
    if not caches:
        log.info("[CACHE] no judgments in %s — nothing to rebuild (this is "
                 "expected before the first judge-pool run)", cfg.log_dir)
        return EXIT_OK
    wanted = ({args.prompt_version} if args.only_prompt_version
              else set(caches))
    written = 0
    for version in sorted(caches):
        cache = caches[version]
        if version not in wanted:
            log.info("[CACHE] %s: %d graded pairs (not written; "
                     "--only-prompt-version selected %s)", version,
                     len(cache), args.prompt_version)
            continue
        path = cache.snapshot(cache_snapshot_path(cfg.cache_dir, version))
        written += 1
        log.info("[CACHE] %s: %d graded pairs, %d records, %d failures -> %s",
                 version, len(cache), cache.stats.records,
                 cache.stats.failures, path)
        if cache.stats.truncated_tails:
            log.warning("[LOG-TAIL] %s: %d segment(s) ended in a truncated "
                        "line (an interrupted write); the pairs they described "
                        "are simply re-judgable", version,
                        cache.stats.truncated_tails)
    log.info("[SUMMARY] rebuilt %d snapshot(s) from %d log segment(s) in %s",
             written, max((c.stats.segments for c in caches.values()),
                          default=0), cfg.log_dir)
    return EXIT_OK


# ---------------------------------------------------------------------------
# score / stats  (WP4, PLAN §5.5, §5.6, §6.4)
# ---------------------------------------------------------------------------
SCORES_CSV_BASENAME = "scores.csv"
SCORES_MD_BASENAME = "scores.md"
SCORES_PER_QUERY_BASENAME = "scores-per-query.csv"
STATS_JSON_BASENAME = "stats.json"

#: The cell every candidate is tested against (PLAN §0: pyserini's default, and
#: **[measured]** score-identical to the hosted server aus_agent actually used).
BASELINE_CONFIG_NAME = "k1_0.9__b_0.4"


def _qrels_path(cfg: Config, prompt_version: str,
                override: Path | None) -> Path:
    """Where the qrels for `prompt_version` live (PLAN §4.2).

    Resolved through `store.cache_snapshot_path` so the filename is defined in
    exactly one place — scoring against a *differently named* file than the one
    `judge-pool` writes would silently score an older label set.
    """
    if override is not None:
        return Path(override)
    from .store import cache_snapshot_path

    return cache_snapshot_path(cfg.cache_dir, prompt_version)


def _load_qkeys_for_scoring(cfg: Config, args: argparse.Namespace,
                            runs: "Sequence[metrics.RunFile]") -> list[str]:
    """The query set every config is scored over — identical for all of them.

    Taken from the persisted query file when one is available, because an
    aggregate over "whatever each run file happened to contain" is not comparable
    across configs and the difference does not show up in the output. Falls back
    to the union of the run files' qkeys (a `--limit`ed plumbing sweep has no
    matching query file).
    """
    if args.queries is not None:
        keys = stats_mod.load_qkeys(Path(args.queries))
        log.info("[LOAD] %d qkeys from %s", len(keys), args.queries)
        return keys
    union = sorted({qkey for run in runs for qkey in run.rankings})
    for basename in (QUERIES_FULL_BASENAME, QUERIES_SUBSAMPLE_BASENAME):
        path = cfg.queries_dir / basename
        if not path.is_file():
            continue
        keys = stats_mod.load_qkeys(path)
        covered = [k for k in keys if k in set(union)]
        if len(covered) == len(keys) and keys:
            log.info("[LOAD] scoring over the %d queries in %s", len(keys),
                     path)
            return keys
        log.info("[LOAD] %s covers %d/%d of its queries in the run files — not "
                 "using it as the score query set", path, len(covered),
                 len(keys))
    log.info("[LOAD] scoring over the %d qkeys present in the run files",
             len(union))
    return union


def cmd_score(args: argparse.Namespace) -> int:
    """Score every grid cell against the pooled qrels → `scores.csv` + `.md`.

    Reads only the cache snapshot and the run files — **no Bedrock, no index,
    no spend** — so re-scoring is free and a budget-truncated or partially
    judged run still produces an honest matrix (PLAN §5.7 layer 3). The
    per-config `judged@10` column is what makes it honest: unjudged chunks score
    gain 0, so a config whose top-10 is under-judged is penalized for coverage
    rather than for ranking.

    The **full** matrix is always written — every cell, both gain conventions,
    all pre-registered secondaries, and the exploratory `gp10`/`p10_bin2`
    precision columns (PLAN §7.4). Reporting only the winner would make the sweep
    unfalsifiable; the neighbouring cells are the evidence that a peak is a peak
    and not noise. Every metric in `metrics.METRIC_NAMES` is computed in this one
    pass and persisted, so choosing a different objective later — maximizing
    `gp10` instead of `ndcg10_exp`, say — is a re-read of `scores.csv`, not a
    re-judge and a re-sweep.
    """
    cfg: Config = args.config
    if not args.run_id:
        log.error("[LOAD] score needs --run-id (the run whose trecruns/ and "
                  "manifest.json are being scored)")
        return EXIT_ERROR
    run_dir = cfg.run_dir(args.run_id)
    out_dir = Path(args.out_dir) if args.out_dir else run_dir
    setup_logging(args.log_file or (run_dir / SWEEP_LOG_BASENAME),
                  level=logging.DEBUG if args.verbose else logging.INFO)

    qrels_path = _qrels_path(cfg, args.prompt_version, args.qrels)
    if not qrels_path.is_file():
        log.error("[CACHE] no qrels at %s — run `judge-pool --run-id %s "
                  "--prompt-version %s` first (or pass --qrels)", qrels_path,
                  args.run_id, args.prompt_version)
        return EXIT_ERROR
    qrels = metrics.load_qrels(qrels_path, args.prompt_version)
    log.info("[CACHE] %s: %d judged (topic, chunk) pairs over %d topics, "
             "grades %s", qrels_path, qrels.n_judged(), len(qrels.topics),
             qrels.distribution())

    runs = metrics.load_run_dir(run_dir / TRECRUNS_DIRNAME)
    log.info("[LOAD] %d run files from %s", len(runs),
             run_dir / TRECRUNS_DIRNAME)
    qkeys = _load_qkeys_for_scoring(cfg, args, runs)
    if not qkeys:
        log.error("[LOAD] no queries to score")
        return EXIT_ERROR

    scored = metrics.score_all(runs, qrels, qkeys)
    for line in metrics.summary_lines(scored):
        log.info("%s", line)

    cfg.ensure_dirs(out_dir)
    csv_path = metrics.write_scores_csv(out_dir / SCORES_CSV_BASENAME, scored)
    md_path = out_dir / SCORES_MD_BASENAME
    md_path.write_text(metrics.render_scores_md(
        scored, run_id=args.run_id, prompt_version=args.prompt_version,
        qrels=qrels, query_set=str(args.queries or "persisted query set"),
        n_queries=len(qkeys)), encoding="utf-8")
    per_query_path = metrics.write_per_query_csv(
        out_dir / SCORES_PER_QUERY_BASENAME, scored)
    log.info("[SUMMARY] wrote %s, %s, %s", csv_path, md_path, per_query_path)

    coverage = [s.judged_at_10_mean for s in scored
                if s.judged_at_10_mean is not None]
    worst = min(coverage) if coverage else None
    if worst is not None and worst < 0.999:
        # Not an error: PLAN §5.7 layer 3 explicitly wants a budget-truncated
        # run to remain scoreable. But it must be loud, because the shortfall
        # looks exactly like a ranking loss in the matrix.
        log.warning("[SUMMARY] judged@10 dips to %.3f — unjudged chunks score "
                    "gain 0, so part of the spread below is coverage, not "
                    "ranking. Finish judging before drawing a conclusion.",
                    worst)

    if scored:
        best = scored[0]
        log.info("[SUMMARY] best %s: %s=%s (topic-mean %s) over %d queries",
                 metrics.PRIMARY_METRIC, best.config,
                 f"{best.primary:.4f}" if best.primary is not None else "na",
                 f"{best.by_topic.get(metrics.PRIMARY_METRIC):.4f}"
                 if best.by_topic.get(metrics.PRIMARY_METRIC) is not None
                 else "na", best.n_queries)
        log.info("[SUMMARY] absolute values are deflated by the topic-level "
                 "ideal DCG — only differences between cells are meaningful "
                 "(PLAN §5.5); see the caveat at the top of %s", md_path)
        # The primary stays `ndcg10_exp`, but the whole point of computing the
        # secondaries in the same pass is that a different objective needs no
        # re-run — so name each one's argmax cell here rather than making the
        # next reader re-sort scores.csv to find it.
        for name in metrics.METRIC_NAMES:
            if name == metrics.PRIMARY_METRIC:
                continue
            ranked = [s for s in scored if s.by_query.get(name) is not None]
            if not ranked:
                continue
            # `scored` is already sorted deterministically (by primary, then
            # config name), and `max` keeps the first maximum — so a tie on this
            # metric resolves to the better primary, reproducibly.
            top = max(ranked, key=lambda s: s.by_query[name])
            log.info("[SUMMARY] best %s: %s=%.4f%s", name, top.config,
                     top.by_query[name],
                     "" if name in metrics.PRE_REGISTERED_METRICS
                     else " (secondary/exploratory, not pre-registered)")

    _write_manifest(run_dir, {
        "scored_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prompt_version": args.prompt_version,
        "qrels_file": str(qrels_path),
        "qrels_judged_pairs": qrels.n_judged(),
        "qrels_grade_distribution": {str(k): v
                                     for k, v in qrels.distribution().items()},
        "score_query_count": len(qkeys),
        "score_configs": [s.config for s in scored],
        "primary_metric": metrics.PRIMARY_METRIC,
        "scores": {s.config: {"n_queries": s.n_queries,
                              "judged_at_10": s.judged_at_10_mean,
                              **{name: s.by_query.get(name)
                                 for name in metrics.METRIC_NAMES}}
                   for s in scored},
    })
    return EXIT_OK


def _per_config_query_values(scored: "Sequence[metrics.ConfigScore]"
                             ) -> dict[str, dict[str, dict[str, float]]]:
    """`{config: {metric: {qkey: value}}}`, skipping undefined values.

    `None` means the metric is undefined for that topic (no judged-relevant
    chunk at all — see `metrics.py`), not that the config scored zero. Feeding a
    0.0 into a paired test would manufacture a delta of exactly 0 for a query
    where nothing was measurable, diluting the effect towards nothing.
    """
    out: dict[str, dict[str, dict[str, float]]] = {}
    for score in scored:
        by_metric: dict[str, dict[str, float]] = {}
        for name in metrics.METRIC_NAMES:
            values = {q.qkey: q.metrics[name] for q in score.per_query
                      if q.metrics.get(name) is not None}
            by_metric[name] = values  # type: ignore[assignment]
        out[score.config] = by_metric
    return out


def cmd_stats(args: argparse.Namespace) -> int:
    """Stage-B paired tests on the held-out queries → `stats.json` (PLAN §6.4).

    Reads run files and the qrels; **no Bedrock, no spend.** Three things here
    are the difference between a result and a claim:

    1. The confirmatory tests run on the **held-out** queries — the full query
       file minus the *persisted* Stage-A subsample, by set difference (825 =
       1063 - 238). The candidates were selected on that subsample, so a p-value
       computed over all 1063 is a selection artifact; it is still reported, and
       labeled descriptive.
    2. **Bonferroni** across the candidate-vs-baseline comparisons.
    3. A **topic-level** paired test alongside every query-level one, because a
       topic's queries are correlated. Where the two disagree, PLAN §6.4 makes
       the topic-level result the headline, and each result's `headline_note`
       says which case it is in.
    """
    cfg: Config = args.config
    if not args.run_id:
        log.error("[LOAD] stats needs --run-id (the Stage-B run to test)")
        return EXIT_ERROR
    run_dir = cfg.run_dir(args.run_id)
    out_dir = Path(args.out_dir) if args.out_dir else run_dir
    setup_logging(args.log_file or (run_dir / SWEEP_LOG_BASENAME),
                  level=logging.DEBUG if args.verbose else logging.INFO)

    qrels_path = _qrels_path(cfg, args.prompt_version, args.qrels)
    if not qrels_path.is_file():
        log.error("[CACHE] no qrels at %s — run judge-pool first (or pass "
                  "--qrels)", qrels_path)
        return EXIT_ERROR
    qrels = metrics.load_qrels(qrels_path, args.prompt_version)

    # Run files may span two runs: PLAN §5.6's signature takes a second run id
    # so a baseline swept in an earlier run can be tested against candidates
    # swept in a later one without re-running the search.
    runs: list[metrics.RunFile] = []
    seen: set[str] = set()
    for run_id in [args.run_id] + ([args.run_id_b] if args.run_id_b else []):
        for run in metrics.load_run_dir(cfg.run_dir(run_id) / TRECRUNS_DIRNAME):
            if run.config in seen:
                log.info("[LOAD] %s already loaded from an earlier --run-id; "
                         "keeping the first", run.config)
                continue
            seen.add(run.config)
            runs.append(run)
    log.info("[LOAD] %d configs across run(s) %s", len(runs),
             [args.run_id] + ([args.run_id_b] if args.run_id_b else []))

    full_path = Path(args.queries) if args.queries \
        else cfg.queries_dir / QUERIES_FULL_BASENAME
    sub_path = Path(args.subsample) if args.subsample \
        else cfg.queries_dir / QUERIES_SUBSAMPLE_BASENAME
    for path, what in ((full_path, "full query file"),
                       (sub_path, "Stage-A subsample file")):
        if not path.is_file():
            log.error("[LOAD] %s not found: %s — run `extract-queries`; the "
                      "held-out set is a SET DIFFERENCE against the persisted "
                      "subsample, never recomputed from the seed (PLAN §6.4)",
                      what, path)
            return EXIT_ERROR
    full_qkeys = stats_mod.load_qkeys(full_path)
    sub_qkeys = stats_mod.load_qkeys(sub_path)
    held_out = stats_mod.held_out_qkeys(full_qkeys, sub_qkeys)
    log.info("[LOAD] held-out = %d of %d queries (%d in the Stage-A subsample "
             "%s)", len(held_out), len(full_qkeys), len(sub_qkeys), sub_path)

    scored = metrics.score_all(runs, qrels, full_qkeys)
    per_config = _per_config_query_values(scored)
    baseline = args.baseline
    if baseline not in per_config:
        log.error("[LOAD] baseline config %r not among the run files %s — pass "
                  "--baseline", baseline, sorted(per_config))
        return EXIT_ERROR
    candidates = (list(args.candidates) if args.candidates
                  else [s.config for s in scored if s.config != baseline])
    unknown = [c for c in candidates if c not in per_config]
    if unknown:
        log.error("[LOAD] candidate config(s) %s not among the run files %s",
                  unknown, sorted(per_config))
        return EXIT_ERROR
    log.info("[SUMMARY] baseline=%s candidates=%s", baseline, candidates)
    if len(candidates) != stats_mod.N_COMPARISONS:
        # PLAN §6.4 pre-registers exactly 3 candidate-vs-baseline comparisons.
        # The correction still uses the actual count (that is the honest test),
        # but a differing count means the analysis is not the pre-registered
        # one and the report must say so.
        log.warning("[SUMMARY] %d candidates, not the %d PLAN §6.4 "
                    "pre-registers — the Bonferroni divisor follows the actual "
                    "count (alpha=%.4f), but this is no longer the "
                    "pre-registered analysis and the report must say so",
                    len(candidates), stats_mod.N_COMPARISONS,
                    stats_mod.FAMILY_ALPHA / max(len(candidates), 1))

    topics = {q.qkey: q.topic_id for s in scored for q in s.per_query}
    report = stats_mod.build_report(
        run_id=args.run_id, baseline=baseline, candidates=candidates,
        metrics=list(args.metrics) if args.metrics
        else list(metrics.METRIC_NAMES),
        prompt_version=args.prompt_version, per_config=per_config,
        held_out=held_out, full=full_qkeys, topics=topics,
        resamples=args.bootstrap, seed=args.seed)
    for line in stats_mod.summary_lines(report, metric=metrics.PRIMARY_METRIC):
        log.info("%s", line)

    cfg.ensure_dirs(out_dir)
    path = out_dir / STATS_JSON_BASENAME
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(report.to_json(), indent=2, sort_keys=True,
                              default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
    log.info("[SUMMARY] wrote %s (%d confirmatory, %d descriptive tests)",
             path, len(report.confirmatory), len(report.descriptive))
    _write_manifest(run_dir, {
        "stats_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stats": {
            "baseline": baseline,
            "candidates": candidates,
            "held_out_n": len(held_out),
            "full_n": len(full_qkeys),
            "alpha_bonferroni": report.alpha_bonferroni,
            "bootstrap_resamples": report.bootstrap_resamples,
            "bootstrap_seed": report.bootstrap_seed,
        },
    })
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

    # -- WP2: search-sweep / smoke (PLAN §5.2, §5.5, §6.1) -------------------
    sweep = subs.add_parser(
        "search-sweep",
        help="run the k1/b grid over the query set at depth 30, writing TREC "
             "run files and pool.jsonl (search only; no Bedrock)")
    sweep.add_argument("--stage", required=True, choices=("A", "B"),
                       help="A = the 26-cell grid over the subsample; B = "
                            "explicit --configs over the full query set")
    sweep.add_argument("--run-id", default=None,
                       help="run id (default: <UTCts>-stage<stage>)")
    sweep.add_argument("--configs", nargs="+", default=None,
                       metavar="K1:B",
                       help="cells to sweep, e.g. 0.9:0.4,1.2:0.75 "
                            "(required for Stage B)")
    sweep.add_argument("--depth", type=int, default=searcher_mod.DEFAULT_DEPTH,
                       help="hits retrieved per query (PLAN §5.5 fixes 30)")
    sweep.add_argument("--threads", type=int,
                       default=searcher_mod.DEFAULT_THREADS,
                       help="threads handed to batch_search (JVM-side fan-out)")
    sweep.add_argument("--queries", type=Path, default=None,
                       help="override the stage's query file")
    sweep.add_argument("--limit", type=int, default=None,
                       help="sweep only the first N queries (plumbing checks)")
    sweep.add_argument("--force", action="store_true",
                       help="re-search configs whose run file already exists")
    sweep.add_argument("--fresh", action="store_true",
                       help="rename an existing run dir aside first; never "
                            "touches judgments/log/ or costs/ (PLAN §5.8)")
    sweep.add_argument("--no-fetch-texts", dest="fetch_texts",
                       action="store_false",
                       help="skip fetching pooled chunk text (judge-pool then "
                            "has no passages to send)")
    sweep.set_defaults(func=cmd_search_sweep, fetch_texts=True)

    smoke = subs.add_parser(
        "smoke",
        help="the live end-to-end check: 3 real index queries and 1 real, "
             "metered judgment")
    smoke.add_argument("--search-only", action="store_true",
                       help="run only the search half (WP2); makes no Bedrock "
                            "call and spends nothing")
    smoke.add_argument("-n", type=int, default=3,
                       help="how many real queries to issue")
    smoke.add_argument("--depth", type=int, default=searcher_mod.DEFAULT_DEPTH,
                       help="hits per query")
    smoke.add_argument("--threads", type=int,
                       default=searcher_mod.DEFAULT_THREADS,
                       help="threads handed to batch_search")
    smoke.set_defaults(func=cmd_smoke)

    # -- WP3: judge-pool / rebuild-cache (PLAN §5.3, §5.4, §5.6, §5.8) -------
    judge_cmd = subs.add_parser(
        "judge-pool",
        help="judge the per-topic pooled union with the Bedrock judge — the "
             "long, fully resumable, metered job")
    judge_cmd.add_argument("--run-id", default=None,
                           help="the sweep run whose pool.jsonl is judged "
                                "(default: <UTCts>-stageA)")
    judge_cmd.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION,
                           choices=all_versions(),
                           help="which frozen rubric to judge under; it is a "
                                "cache-key component, so a different version "
                                "re-judges (and re-bills) the pool")
    judge_cmd.add_argument("--pilot", type=int, nargs="?", default=None,
                           const=DEFAULT_PILOT_N,
                           help="judge only N pooled pairs (sampled evenly "
                                "across topics, seed 13) and print the "
                                "MEASURED cost basis, then stop; bare --pilot "
                                f"means {DEFAULT_PILOT_N}")
    judge_cmd.add_argument("--concurrency", type=int, default=None,
                           help="worker threads (default: "
                                "BM25_TUNE_JUDGE_CONCURRENCY)")
    judge_cmd.add_argument("--stage", default=None,
                           help="stage label for the cost split (default: the "
                                "sweep manifest's, else the run id's suffix)")
    judge_cmd.add_argument("--queries", type=Path, default=None,
                           help="query file supplying the topic narratives "
                                f"(default: queries/{QUERIES_FULL_BASENAME})")
    judge_cmd.add_argument("--fresh", action="store_true",
                           help="rename this prompt version's qrels snapshot "
                                "aside first; NEVER touches judgments/log/ or "
                                "costs/ (PLAN §5.8) and never the run dir, "
                                "which holds this command's input pool")
    judge_cmd.add_argument("--allow-partial-texts", action="store_true",
                           help="judge even when under "
                                f"{MIN_POOL_TEXT_COVERAGE:.0%} of pooled "
                                "chunks have a passage in pool-texts.jsonl; "
                                "the missing ones score as unjudged, which "
                                "deflates judged@10 for every config")
    judge_cmd.set_defaults(func=cmd_judge_pool)

    rebuild_cmd = subs.add_parser(
        "rebuild-cache",
        help="force a full rescan of the append-only judgment log into fresh "
             "cache snapshots (reads the log only; spends nothing)")
    rebuild_cmd.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION,
                             choices=all_versions(),
                             help="with --only-prompt-version, the single "
                                  "version to snapshot")
    rebuild_cmd.add_argument("--only-prompt-version", action="store_true",
                             help="write only --prompt-version's snapshot "
                                  "(default: every version present in the log)")
    rebuild_cmd.set_defaults(func=cmd_rebuild_cache)

    # -- WP3b: budget / cost-report / refresh-prices (PLAN §5.7) -------------
    budget_cmd = subs.add_parser(
        "budget",
        help="print spent / cap / remaining from costs/totals.json and exit "
             "(makes NO API call)")
    budget_cmd.add_argument("--json", action="store_true",
                            help="also print the status as JSON on stdout")
    budget_cmd.set_defaults(func=cmd_budget)

    cost_cmd = subs.add_parser(
        "cost-report",
        help="write costs.json/.md plus the experiment-wide roll-up and the "
             "ledger-vs-log reconciliation line")
    cost_cmd.add_argument("--run-id", default=None,
                          help="scope the per-run breakdown to this run "
                               "(the roll-up is always experiment-wide)")
    cost_cmd.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION,
                          choices=all_versions(),
                          help="accepted for launch-command symmetry; the "
                               "report splits by prompt version regardless")
    cost_cmd.add_argument("--cache-hits", type=int, default=None,
                          help="cache-hit count for the US$-saved ESTIMATE "
                               "(default: the run manifest's cache.hits)")
    cost_cmd.add_argument("--out-dir", type=Path, default=None,
                          help="where costs.json/.md go (default: the run dir, "
                               "or costs/ for an experiment-wide report)")
    cost_cmd.set_defaults(func=cmd_cost_report)

    prices_cmd = subs.add_parser(
        "refresh-prices",
        help="re-fetch the AWS Pricing API into a NEW dated prices/ file "
             "(never overwrites an existing one)")
    prices_cmd.add_argument("--date", default=None,
                            help="date suffix for the new file "
                                 "(default: today, UTC)")
    prices_cmd.add_argument("--region", default=None,
                            help="region being priced (default: the judge "
                                 "region)")
    prices_cmd.add_argument("--model-id", default=None,
                            help="model id recorded in the file (default: the "
                                 "judge model)")
    prices_cmd.add_argument("--model-match", default="gpt-oss-20b",
                            help="substring a usagetype must contain to be "
                                 "kept")
    prices_cmd.add_argument("--pricing-region", default="us-east-1",
                            help="where the Pricing API itself is called "
                                 "(it is not served from every region)")
    prices_cmd.add_argument("--slug", default=None,
                            help="region slug in the filename "
                                 "(default: derived, e.g. aps2)")
    prices_cmd.set_defaults(func=cmd_refresh_prices)

    # -- WP4: score / stats (PLAN §5.5, §5.6, §6.4) --------------------------
    score_cmd = subs.add_parser(
        "score",
        help="score every grid cell against the cached qrels into "
             "scores.csv/.md (reads the cache only; spends nothing)")
    score_cmd.add_argument("--run-id", required=True,
                           help="the run whose trecruns/ are scored")
    score_cmd.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION,
                           choices=all_versions(),
                           help="which qrels snapshot to score against; a "
                                "snapshot from another version is REFUSED, not "
                                "silently mixed")
    score_cmd.add_argument("--qrels", type=Path, default=None,
                           help="override the qrels path (default: "
                                "judgments/cache/qrels-<prompt-version>.jsonl)")
    score_cmd.add_argument("--queries", type=Path, default=None,
                           help="score over exactly this query file's qkeys "
                                "(default: the persisted query file the run "
                                "covers)")
    score_cmd.add_argument("--out-dir", type=Path, default=None,
                           help="where scores.csv/.md go (default: the run dir)")
    score_cmd.set_defaults(func=cmd_score)

    stats_cmd = subs.add_parser(
        "stats",
        help="paired t / Wilcoxon / bootstrap CIs on the HELD-OUT queries into "
             "stats.json (reads run files + qrels; spends nothing)")
    stats_cmd.add_argument("--run-id", required=True,
                           help="the Stage-B run holding the candidate runs")
    stats_cmd.add_argument("--run-id-b", default=None,
                           help="a second run to pull configs from (e.g. the "
                                "baseline swept in an earlier run); the first "
                                "run wins on a config collision")
    stats_cmd.add_argument("--baseline", default=BASELINE_CONFIG_NAME,
                           help="the config every candidate is compared to")
    stats_cmd.add_argument("--candidates", nargs="+", default=None,
                           metavar="CONFIG",
                           help="candidate config names (default: every other "
                                "config present; PLAN §6.4 pre-registers 3)")
    stats_cmd.add_argument("--metrics", nargs="+", default=None,
                           metavar="METRIC",
                           help=f"metrics to test (default: all of "
                                f"{', '.join(metrics.METRIC_NAMES)})")
    stats_cmd.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION,
                           choices=all_versions(),
                           help="which qrels snapshot to score against")
    stats_cmd.add_argument("--qrels", type=Path, default=None,
                           help="override the qrels path")
    stats_cmd.add_argument("--queries", type=Path, default=None,
                           help="the FULL query file (default: "
                                f"queries/{QUERIES_FULL_BASENAME})")
    stats_cmd.add_argument("--subsample", type=Path, default=None,
                           help="the persisted Stage-A subsample subtracted to "
                                "get the held-out set (default: "
                                f"queries/{QUERIES_SUBSAMPLE_BASENAME}); it is "
                                "read from disk, NEVER recomputed from the seed")
    stats_cmd.add_argument("--bootstrap", type=int,
                           default=stats_mod.BOOTSTRAP_RESAMPLES,
                           help="bootstrap resamples (PLAN §6.4 fixes 10000)")
    stats_cmd.add_argument("--seed", type=int,
                           default=stats_mod.BOOTSTRAP_SEED,
                           help="bootstrap seed (PLAN §6.4 fixes 13)")
    stats_cmd.add_argument("--out-dir", type=Path, default=None,
                           help="where stats.json goes (default: the run dir)")
    stats_cmd.set_defaults(func=cmd_stats)

    calib_cmd = subs.add_parser(
        "calibrate",
        help="WP6/WP0 judge calibration: judge the 280-pair sample under every "
             "registered prompt variant, apply the §3.3 grade-spread gate "
             "(exit 6 on failure), and write calibration/report.md")
    calib_cmd.add_argument(
        "--n", type=int, default=CALIBRATION_SAMPLE_N,
        help=f"calibration sample size (PLAN §3.1 fixes {CALIBRATION_SAMPLE_N})")
    calib_cmd.add_argument(
        "--seed", type=int, default=CALIBRATION_SAMPLE_SEED,
        help=f"sampler seed (PLAN §3.1 fixes {CALIBRATION_SAMPLE_SEED})")
    calib_cmd.add_argument(
        "--stability-pairs", type=int, default=calib.STABILITY_PROBE_PAIRS,
        help="pairs re-judged (cache-bypassing) to measure the winner's "
             f"stability (PLAN §3.3 fixes {calib.STABILITY_PROBE_PAIRS}); "
             "0 disables the probe")
    calib_cmd.add_argument(
        "--concurrency", type=int, default=None,
        help="worker threads (default: BM25_TUNE_JUDGE_CONCURRENCY)")
    calib_cmd.add_argument(
        "--queries", type=Path, default=None,
        help=f"query file supplying the topic narratives (default: "
             f"queries/{QUERIES_FULL_BASENAME})")
    calib_cmd.add_argument(
        "--fresh", action="store_true",
        help="rename each variant's qrels snapshot aside first; NEVER touches "
             "judgments/log/ or costs/ (PLAN §5.8)")
    calib_cmd.set_defaults(func=cmd_calibrate)

    for stub in STUBS:
        sub = subs.add_parser(stub.name,
                              help=f"[{stub.work_package}] {stub.summary}")
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
    except store.ProtectedPathError as exc:
        # `--fresh` aimed at judgments/log/ or costs/ (PLAN §5.8). A refusal, not
        # a crash: the message names `rebuild-cache` as the tool wanted.
        log.error("[CACHE] %s", exc)
        return EXIT_ERROR
    except store.LogCorruption as exc:
        # A malformed *interior* log line. Fatal by design — the log is the
        # source of truth for both the qrels and the money, so skipping a line
        # would under-count spend and silently drop paid-for judgments.
        log.error("[LOG-TAIL] %s", exc)
        return EXIT_ERROR
    except pricing.BudgetRefused as exc:
        # Layer 1 (PLAN §5.7): refused BEFORE anything was spent. Distinct from
        # exit 5 so a launching agent can tell "never started" from "stopped
        # part-way, partial results are scoreable" without parsing the log.
        log.error("%s", exc)
        log.error("[BUDGET] nothing was spent. Raise BM25_TUNE_BUDGET_USD only "
                  "after diagnosing why the estimate is high (PLAN R11).")
        return EXIT_BUDGET_PREFLIGHT
    except pricing.BudgetExceeded as exc:
        # A `BudgetExceeded` reaching here means it escaped the writer thread's
        # drain (PLAN §5.7 layer 3) — still exit 5, so resume semantics hold.
        log.error("%s", exc)
        log.error("[BUDGET] HARD STOP — re-run the same command to resume; "
                  "every completed judgment is cached and will not be "
                  "re-billed.")
        return EXIT_BUDGET_STOP
    except pricing.LedgerIntegrityError as exc:
        log.error("[COST] %s", exc)
        return EXIT_ERROR
    except KeyboardInterrupt:
        # WP1 has no in-flight work to drain; WP3 replaces this with the
        # §5.8 drain routine, which is why the code is already the 128+SIGINT
        # value the plan's exit-code table promises.
        log.error("[SIGNAL] SIGINT — nothing in flight to drain")
        return EXIT_SIGINT


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
