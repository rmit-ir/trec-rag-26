"""CLI for a cached complete-answer candidate-union experiment.

The eight default source runs are already paid, complete, and fully graded. A
live invocation therefore spends only on one extractive selector per topic; it
does not repeat retrieval or generation. The mandatory budget preflight checks
the same cross-system ledger as the optimization goal before every topic.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


_SRC_ROOT = Path(__file__).resolve().parents[2]
_HERE = Path(__file__).resolve().parent
_SYSTEMS_ROOT = _SRC_ROOT / "systems"
for value in (str(_SRC_ROOT), str(_SYSTEMS_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from ragrun.outputs import data_dir  # noqa: E402
from systems.aus_agent_v2.candidate_union import (  # noqa: E402
    build_candidate_union_packet,
    candidate_union_request,
)
from systems.aus_agent_v2.pipeline import run_candidate_union_one  # noqa: E402
from systems.aus_agent_v2.run import DEFAULT_TOPICS, load_topics  # noqa: E402


ROOT = Path(__file__).resolve().parents[3]
GOAL_STATUS = ROOT / "tasks/task-comparison/scripts/goal_status.py"
DEFAULT_SOURCE_RUNS = [
    "sol-aus-v2-research-first-pre-repair-dev30-20260806",
    "v2-dev30-default",
    "sol-aus-v2-research-first-dev30-20260806",
    "sol-aus-v2-adaptive-dev30-20260806",
    "v2-dev30-minimal",
    "sol-dev30-effort-max",
    "sol-dev30-tools",
    "sol-dev30-finish-the-claim",
]
DEFAULT_ANCHOR_RUN = DEFAULT_SOURCE_RUNS[0]


def _load_goal_status() -> ModuleType:
    """Load the authoritative local spend ledger without shell parsing."""
    spec = importlib.util.spec_from_file_location(
        "aus_v2_goal_status_for_union", GOAL_STATUS)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load budget monitor at {GOAL_STATUS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tracked_spend_usd() -> float:
    """Return generation plus judge spend under the optimization ledger."""
    monitor = _load_goal_status()
    agent_usd, _priced, _unpriced, _by_system = monitor.agent_spend()
    judge_usd, _unknown = monitor.judge_spend(monitor.rows())
    return float(agent_usd + judge_usd)


def load_complete_candidates(
    qid: str,
    run_ids: list[str],
    index: dict[tuple[str, str], tuple[Path, dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], list[Path]]:
    """Resolve exactly one terminal artifact per requested run and topic."""
    if index is None:
        index = index_complete_candidates(run_ids)
    outputs: list[dict[str, Any]] = []
    paths: list[Path] = []
    for run_id in run_ids:
        match = index.get((run_id, qid))
        if match is None:
            raise RuntimeError(
                f"qid {qid} run {run_id!r} has no unique complete artifact")
        path, output = match
        paths.append(path)
        outputs.append(output)
    return outputs, paths


def index_complete_candidates(
    run_ids: list[str],
) -> dict[tuple[str, str], tuple[Path, dict[str, Any]]]:
    """Scan source artifacts once and reject ambiguous run/topic pairs."""
    wanted = set(run_ids)
    found: dict[str, list[tuple[Path, dict[str, Any]]]] = {
        run_id: [] for run_id in run_ids
    }
    for path in data_dir().glob("outputs/*/*.output.json"):
        try:
            output = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        metadata = output.get("metadata") or {}
        run_id = str(metadata.get("run_id") or "")
        if run_id not in wanted:
            continue
        if (output.get("trace") or {}).get("status") != "completed":
            continue
        found[run_id].append((path, output))
    index: dict[tuple[str, str], tuple[Path, dict[str, Any]]] = {}
    duplicates: list[tuple[str, str]] = []
    for run_id, matches in found.items():
        for path, output in matches:
            qid = str(output.get("metadata", {}).get("narrative_id") or "")
            key = (run_id, qid)
            if key in index:
                duplicates.append(key)
            else:
                index[key] = (path, output)
    if duplicates:
        rendered = ", ".join(
            f"{run_id}/{qid}" for run_id, qid in sorted(set(duplicates)))
        raise RuntimeError(
            "multiple complete candidate artifacts found for: " + rendered)
    return index


def finished_topics(run_id: str) -> set[str]:
    """Find cached union topics safe to skip on an interrupted batch."""
    done: set[str] = set()
    for path in data_dir().glob("outputs/aus_agent_v2/*.output.json"):
        try:
            output = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if output.get("metadata", {}).get("run_id") != run_id:
            continue
        if output.get("trace", {}).get("status") == "completed":
            done.add(str(output.get("metadata", {}).get("narrative_id") or ""))
    return done


def main() -> int:
    """Prepare exact packets offline or run budget-gated selector calls."""
    parser = argparse.ArgumentParser(
        description="citation-preserving complete-answer candidate union")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--qid", help="one topic id from the topics TSV")
    source.add_argument("--all", action="store_true", help="all topics")
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    parser.add_argument(
        "--candidate-run", action="append", dest="candidate_runs",
        help="source run id; anonymous order is derived from qid")
    parser.add_argument("--anchor-run", default=DEFAULT_ANCHOR_RUN)
    parser.add_argument("--backend", default="openai")
    parser.add_argument("--model", default="openai.gpt-5.6-sol")
    parser.add_argument("--run-id", default="sol-research-candidate-union-dev30")
    parser.add_argument("--run-desc")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument(
        "--budget-cap", type=float, default=300.0,
        help="absolute tracked optimization cap; checked before every call")
    parser.add_argument(
        "--per-topic-reserve-usd", type=float, default=10.0,
        help="conservative reserve required below the cap before one selector")
    parser.add_argument(
        "--prepare-only", action="store_true",
        help="make exact packets and no provider calls")
    parser.add_argument(
        "--packet-output", type=Path,
        help="optional JSONL destination for --prepare-only packets")
    args = parser.parse_args()

    candidate_runs = args.candidate_runs or list(DEFAULT_SOURCE_RUNS)
    if len(candidate_runs) != len(set(candidate_runs)):
        parser.error("--candidate-run values must be unique")
    if args.anchor_run not in candidate_runs:
        parser.error("--anchor-run must be one of the candidate runs")
    if args.budget_cap <= 0 or args.per_topic_reserve_usd <= 0:
        parser.error("budget cap and per-topic reserve must be positive")

    topics = dict(load_topics(args.topics))
    if args.qid:
        if args.qid not in topics:
            parser.error(f"qid {args.qid!r} not found in {args.topics}")
        jobs = [(args.qid, topics[args.qid])]
    else:
        jobs = list(topics.items())
    if args.skip_existing and not args.prepare_only:
        done = finished_topics(args.run_id)
        jobs = [job for job in jobs if job[0] not in done]

    candidate_index = index_complete_candidates(candidate_runs)
    packet_rows: list[str] = []
    failures = 0
    for qid, query in jobs:
        outputs, paths = load_complete_candidates(
            qid, candidate_runs, candidate_index)
        if args.prepare_only:
            packet = build_candidate_union_packet(
                query, outputs, expected_qid=qid,
                anchor_run_id=args.anchor_run)
            request = candidate_union_request(packet)
            row = {
                "qid": qid,
                "source_runs": candidate_runs,
                "source_paths": [str(path.relative_to(ROOT)) for path in paths],
                "request_chars": len(request),
                "packet": packet,
            }
            packet_rows.append(json.dumps(row, ensure_ascii=False))
            print(json.dumps({
                "qid": qid,
                "request_chars": len(request),
                "candidate_items": sum(
                    len(candidate["items"])
                    for candidate in packet["candidates"]),
                "anchor_words": sum(
                    item["word_count"]
                    for candidate in packet["candidates"]
                    if candidate["anchor"]
                    for item in candidate["items"]),
            }), flush=True)
            continue

        spent = tracked_spend_usd()
        if spent + args.per_topic_reserve_usd > args.budget_cap:
            raise SystemExit(
                f"budget gate: ${spent:.2f} tracked + "
                f"${args.per_topic_reserve_usd:.2f} reserve exceeds "
                f"${args.budget_cap:.2f} cap; no provider call made")
        print(
            f"=== {qid}: tracked ${spent:.2f}; reserve "
            f"${args.per_topic_reserve_usd:.2f} ===",
            flush=True,
        )
        try:
            summary = run_candidate_union_one(
                qid=qid,
                narrative=query,
                run_id=args.run_id,
                run_desc=args.run_desc,
                model_id=args.model,
                backend=args.backend,
                candidate_outputs=outputs,
                anchor_run_id=args.anchor_run,
            )
            print(json.dumps({
                "qid": qid,
                "accepted": summary["accepted"],
                "fallback": summary["fallback"],
                "words": summary["words"],
                "output": str(summary["paths"]["output"]),
            }), flush=True)
        except Exception as exc:  # keep a batch resumable and visible
            failures += 1
            print(
                f"FAILED {qid}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )

    if args.prepare_only and args.packet_output:
        args.packet_output.parent.mkdir(parents=True, exist_ok=True)
        args.packet_output.write_text(
            "\n".join(packet_rows) + ("\n" if packet_rows else ""),
            encoding="utf-8",
        )
        print(f"wrote {len(packet_rows)} packets to {args.packet_output}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
