#!/usr/bin/env python3
"""Convert injected TREC-DL CSVs into RAGDOLL UMBRELA relevance requests.

Input layout:
    <input-root>/<distractor-category>/trec_dl_<year>.csv

Output layout:
    <output-root>/<distractor-category>/<year>.requests.jsonl
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from generate_distractors import PROMPTS
from translate_queries import REPO_ROOT, YEARS, parse_csv_option

DEFAULT_INPUT_ROOT = REPO_ROOT / "data" / "ragdoll-robustness" / "injected" / "distractors"
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "data" / "ragdoll-robustness" / "derived"
    / "ragdoll-inputs" / "distractors"
)
DEFAULT_ORIGINAL_INPUT_ROOT = REPO_ROOT / "data" / "ragdoll-robustness" / "gold" / "trec-dl"
DEFAULT_ORIGINAL_OUTPUT_ROOT = (
    REPO_ROOT / "data" / "ragdoll-robustness" / "derived"
    / "ragdoll-inputs" / "original"
)
REQUIRED_COLUMNS = {"qid", "query", "pid", "passage", "relevance"}


def request_qid(qid: str, query: str, variant_count: int) -> str:
    """Disambiguate a qid only when the source attaches it to multiple query strings."""
    if variant_count == 1:
        return qid
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:8]
    return f"{qid}__{digest}"


def convert_csv(path: Path) -> list[dict[str, Any]]:
    """Group passage rows into RAGDOLL's query-plus-candidates request shape."""
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or set(reader.fieldnames) != REQUIRED_COLUMNS:
            raise ValueError(f"{path}: expected exactly the columns {sorted(REQUIRED_COLUMNS)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path}: no judged passage rows")

    variants: dict[str, set[str]] = defaultdict(set)
    for line_number, row in enumerate(rows, start=2):
        qid = row["qid"].strip()
        query = row["query"].strip()
        pid = row["pid"].strip()
        passage = row["passage"].strip()
        if not qid or not query or not pid or not passage:
            raise ValueError(f"{path}:{line_number}: qid, query, pid, and passage must be non-empty")
        variants[qid].add(query)

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    seen_docids: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    for line_number, row in enumerate(rows, start=2):
        qid = row["qid"].strip()
        query = row["query"].strip()
        pid = row["pid"].strip()
        passage = row["passage"].strip()
        key = (qid, query)
        previous = seen_docids[key].get(pid)
        if previous is not None:
            if previous == passage:
                continue
            raise ValueError(
                f"{path}:{line_number}: pid {pid!r} has conflicting passage text for query {qid!r}"
            )
        seen_docids[key][pid] = passage
        request = grouped.setdefault(
            key,
            {
                "query": {
                    "qid": request_qid(qid, query, len(variants[qid])),
                    "text": query,
                },
                "candidates": [],
            },
        )
        request["candidates"].append({
            "doc": {"docid": pid, "segment": passage}
        })
    return list(grouped.values())


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Publish a complete request file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        Path(temporary_name).replace(path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--categories", default="all")
    parser.add_argument("--years", default="2021,2022,2023")
    parser.add_argument(
        "--original",
        action="store_true",
        help="convert untouched gold TREC-DL CSVs instead of injected distractor CSVs",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        categories = parse_csv_option(args.categories, PROMPTS, "category")
        years = [int(value) for value in parse_csv_option(
            args.years, [str(year) for year in YEARS], "year"
        )]
    except ValueError as error:
        parser.error(str(error))

    if args.original:
        input_root = args.input_root if args.input_root != DEFAULT_INPUT_ROOT else DEFAULT_ORIGINAL_INPUT_ROOT
        output_root = args.output_root if args.output_root != DEFAULT_OUTPUT_ROOT else DEFAULT_ORIGINAL_OUTPUT_ROOT
        for year in years:
            source = input_root / f"trec_dl_{year}.csv"
            destination = output_root / f"{year}.requests.jsonl"
            if not source.exists():
                parser.error(f"input does not exist: {source}")
            if destination.exists() and not args.overwrite:
                parser.error(f"output exists; pass --overwrite to replace it: {destination}")
            requests = convert_csv(source)
            atomic_write_jsonl(destination, requests)
            candidates = sum(len(row["candidates"]) for row in requests)
            print(f"[original/{year}] {len(requests)} queries, {candidates} candidates -> {destination}")
        return 0

    for category in categories:
        for year in years:
            source = args.input_root / category / f"trec_dl_{year}.csv"
            destination = args.output_root / category / f"{year}.requests.jsonl"
            if not source.exists():
                parser.error(f"input does not exist: {source}")
            if destination.exists() and not args.overwrite:
                parser.error(f"output exists; pass --overwrite to replace it: {destination}")
            requests = convert_csv(source)
            atomic_write_jsonl(destination, requests)
            candidates = sum(len(row["candidates"]) for row in requests)
            print(
                f"[{category}/{year}] {len(requests)} queries, {candidates} candidates "
                f"-> {destination}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
