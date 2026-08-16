#!/usr/bin/env python3
"""Inject generated query keywords into TREC-DL passages at random sentence boundaries.

Examples:
    uv run --project tasks/llm_judge_robustness python \
        tasks/llm_judge_robustness/scripts/inject_keywords.py

    uv run --project tasks/llm_judge_robustness python \
        tasks/llm_judge_robustness/scripts/inject_keywords.py --overwrite
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import os
import tempfile
from pathlib import Path

from translate_queries import DEFAULT_INPUT_ROOT, REPO_ROOT, YEARS, parse_csv_option

DEFAULT_KEYWORD_ROOT = (
    REPO_ROOT / "data" / "ragdoll-robustness" / "derived" / "query-keywords"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "ragdoll-robustness" / "injected" / "keywords"


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read one gold CSV while retaining its exact declared column order."""
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = {"qid", "query", "pid", "passage", "relevance"}
        if not reader.fieldnames or set(reader.fieldnames) != expected:
            raise ValueError(f"{path}: expected exactly the columns {sorted(expected)}")
        return list(reader.fieldnames), list(reader)


def atomic_write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    """Write the full injected CSV atomically."""
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


def read_keyword_map(path: Path) -> dict[str, list[str]]:
    """Load generated keywords keyed by qid/query identity."""
    if not path.exists():
        raise FileNotFoundError(f"missing keyword checkpoint: {path}")
    rows: dict[str, list[str]] = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            query_id = str(row.get("query_id", "")).strip()
            keywords_json = str(row.get("keywords_json", "")).strip()
            if not query_id or not keywords_json:
                raise ValueError(f"{path}:{line_number}: invalid keyword row")
            keywords = json.loads(keywords_json)
            if not isinstance(keywords, list) or not keywords:
                raise ValueError(f"{path}:{line_number}: keywords_json must decode to a non-empty list")
            rows[query_id] = [str(value).strip() for value in keywords if str(value).strip()]
    return rows


def split_sentences(text: str) -> list[str]:
    """Split passage text into lightweight sentence-like chunks."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    pieces = re.split(r"(?<=[.!?])\s+", cleaned)
    return [piece.strip() for piece in pieces if piece.strip()]


def pick_insert_index(query_id: str, sentence_count: int) -> int:
    """Pick a stable random boundary per query so reruns remain deterministic."""
    if sentence_count <= 1:
        return 0
    digest = hashlib.sha256(query_id.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big")
    rng = random.Random(seed)
    return rng.randint(1, sentence_count - 1)


def inject_keywords(passage: str, query_id: str, keywords: list[str]) -> str:
    """Insert keywords between sentences, or append them to short passages."""
    sentences = split_sentences(passage)
    injection = f"[KEYWORDS: {', '.join(keywords)}]"
    if not sentences:
        return injection
    if len(sentences) == 1:
        return f"{sentences[0]} {injection}"
    index = pick_insert_index(query_id, len(sentences))
    return " ".join([*sentences[:index], injection, *sentences[index:]])


def main() -> int:
    """Parse CLI flags, inject keywords into each year, and write the outputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--keyword-root", type=Path, default=DEFAULT_KEYWORD_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--years", default="2021,2022,2023")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    try:
        years = [int(value) for value in parse_csv_option(args.years, [str(y) for y in YEARS], "year")]
    except ValueError as error:
        parser.error(str(error))

    keyword_map = read_keyword_map(args.keyword_root / "keywords.jsonl")
    for year in years:
        source = args.input_root / f"trec_dl_{year}.csv"
        if not source.exists():
            parser.error(f"input does not exist: {source}")
        destination = args.output_root / f"trec_dl_{year}.csv"
        if destination.exists() and not args.overwrite:
            parser.error(f"output exists; pass --overwrite to replace it: {destination}")

        fields, rows = read_csv_rows(source)
        injected_rows: list[dict[str, str]] = []
        missing = 0
        for row in rows:
            query = row["query"].strip()
            query_id = row["qid"].strip()
            key = query_id
            keywords = keyword_map.get(key)
            if keywords is None:
                digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:8]
                keywords = keyword_map.get(f"{query_id}__{digest}")
            if keywords is None:
                missing += 1
                injected_rows.append(dict(row))
                continue
            injected_rows.append({
                **row,
                "passage": inject_keywords(row["passage"], key, keywords),
            })

        atomic_write_csv(destination, fields, injected_rows)
        print(
            f"[keywords/{year}] injected {len(rows) - missing}/{len(rows)} passages "
            f"({missing} missing keyword entries) -> {destination}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
