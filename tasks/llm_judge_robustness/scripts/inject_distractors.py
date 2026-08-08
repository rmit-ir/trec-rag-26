#!/usr/bin/env python3
"""Append generated distractor text to every passage for its matching query."""
from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from generate_distractors import DEFAULT_OUTPUT_ROOT as DEFAULT_DISTRACTOR_ROOT
from generate_distractors import PROMPTS, read_evidence
from translate_queries import DEFAULT_INPUT_ROOT, REPO_ROOT, YEARS, parse_csv_option, read_queries

DEFAULT_INJECTED_ROOT = REPO_ROOT / "data" / "ragdoll-robustness" / "injected" / "distractors"


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read one gold CSV while retaining its exact declared column order."""
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = {"qid", "query", "pid", "passage", "relevance"}
        if not reader.fieldnames or set(reader.fieldnames) != expected:
            raise ValueError(f"{path}: expected exactly the columns {sorted(expected)}")
        return list(reader.fieldnames), list(reader)


def read_distractors(path: Path) -> list[dict[str, Any]]:
    """Read unique, complete English distractor objects."""
    if not path.exists():
        raise ValueError(f"missing distractor checkpoint: {path}")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            identity = str(row.get("translation_id", row.get("qid", "")))
            if (
                not identity or identity in seen
                or not str(row.get("title", "")).strip()
                or not str(row.get("text", "")).strip()
            ):
                raise ValueError(f"{path}:{line_number}: invalid or duplicate distractor")
            seen.add(identity)
            rows.append(row)
    return rows


def compact_passage(title: str, text: str) -> str:
    """Combine generated fields without reintroducing embedded CSV newlines."""
    title_clean = " ".join(title.split()).rstrip(". ")
    text_clean = " ".join(text.split())
    return f"{title_clean}. {text_clean}"


def build_injected_rows(
    *, year: int, category: str, gold_rows: list[dict[str, str]],
    distractors: list[dict[str, Any]], expected_identities: set[str], allow_partial: bool,
) -> list[dict[str, str]]:
    """Validate coverage and suffix every passage belonging to each distractor query."""
    gold_pairs = {(row["qid"].strip(), row["query"].strip()) for row in gold_rows}
    actual_identities = {
        str(row.get("translation_id", row.get("qid", ""))) for row in distractors
    }
    missing = expected_identities - actual_identities
    extra = actual_identities - expected_identities
    if extra or (missing and not allow_partial):
        raise ValueError(
            f"{category}/{year}: distractor coverage mismatch; "
            f"missing={len(missing)}, extra={len(extra)}"
        )
    distractor_by_pair: dict[tuple[str, str], str] = {}
    for row in distractors:
        identity = str(row.get("translation_id", row["qid"]))
        qid = str(row["qid"]).strip()
        source_query = str(row.get("source_query", row.get("query", ""))).strip()
        if (qid, source_query) not in gold_pairs:
            raise ValueError(f"{category}/{year}: distractor {identity} does not match a gold query")
        if int(row.get("year", -1)) != year:
            raise ValueError(f"{category}/{year}: distractor {identity} has wrong year")
        if str(row.get("language", "")) != "en":
            raise ValueError(f"{category}/{year}: distractor {identity} is not English")
        pair = (qid, source_query)
        if pair in distractor_by_pair:
            raise ValueError(f"{category}/{year}: multiple distractors for query pair {pair}")
        distractor_by_pair[pair] = compact_passage(str(row["title"]), str(row["text"]))

    injected: list[dict[str, str]] = []
    for gold in gold_rows:
        pair = (gold["qid"].strip(), gold["query"].strip())
        distractor = distractor_by_pair.get(pair)
        if distractor is None:
            injected.append(dict(gold))
            continue
        passage = " ".join(gold["passage"].split())
        injected.append({
            **gold,
            "passage": f"{passage} {distractor}".strip(),
        })
    return injected


def atomic_write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    """Write the full injected qrels CSV atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        Path(temporary_name).replace(path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--distractor-root", type=Path, default=DEFAULT_DISTRACTOR_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_INJECTED_ROOT)
    parser.add_argument("--years", default="2021,2022,2023")
    parser.add_argument("--categories", default="all")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        years = [int(value) for value in parse_csv_option(args.years, [str(y) for y in YEARS], "year")]
        categories = parse_csv_option(args.categories, PROMPTS, "category")
    except ValueError as error:
        parser.error(str(error))
    for category in categories:
        for year in years:
            gold_path = args.gold_root / f"trec_dl_{year}.csv"
            fields, gold_rows = read_csv_rows(gold_path)
            source_items = read_queries(gold_path)
            evidence = read_evidence(gold_path)
            expected = {
                item["translation_id"] for item in source_items
                if (item["qid"], item["query"]) in evidence
            }
            distractor_path = args.distractor_root / category / "english" / f"{year}.jsonl"
            distractors = read_distractors(distractor_path)
            rows = build_injected_rows(
                year=year, category=category, gold_rows=gold_rows,
                distractors=distractors, expected_identities=expected,
                allow_partial=args.allow_partial,
            )
            output_path = args.output_root / category / f"trec_dl_{year}.csv"
            if output_path.exists() and not args.overwrite:
                parser.error(f"output exists; pass --overwrite to replace it: {output_path}")
            atomic_write_csv(output_path, fields, rows)
            distractor_pairs = {
                (str(row["qid"]).strip(), str(row.get("source_query", row.get("query", ""))).strip())
                for row in distractors
            }
            affected = sum(
                (row["qid"].strip(), row["query"].strip()) in distractor_pairs
                for row in gold_rows
            )
            print(
                f"[{category}/{year}] appended {len(distractors)} distractors to "
                f"{affected}/{len(gold_rows)} passages -> {output_path}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
