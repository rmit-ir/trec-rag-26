#!/usr/bin/env python3
"""Append each row's query text to the end of its passage.

Examples:
    uv run --project tasks/llm_judge_robustness python \
        tasks/llm_judge_robustness/scripts/query_injector.py

    uv run --project tasks/llm_judge_robustness python \
        tasks/llm_judge_robustness/scripts/query_injector.py --overwrite
"""
from __future__ import annotations

import argparse
from pathlib import Path

from inject_keywords import atomic_write_csv, read_csv_rows
from inject_yun_yi_text import normalize_text
from translate_queries import DEFAULT_INPUT_ROOT, REPO_ROOT, YEARS, parse_csv_option

DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "data"
    / "ragdoll-robustness"
    / "injected"
    / "query"
)


def inject_query(passage: str, query: str) -> str:
    """Append one normalized query to a normalized passage."""
    normalized_query = normalize_text(query)
    if not normalized_query:
        raise ValueError("query text must not be empty")
    normalized_passage = normalize_text(passage)
    return f"{normalized_passage} {normalized_query}".strip()


def main() -> int:
    """Parse CLI flags and build query-appended TREC-DL CSVs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--years", default="2021,2022,2023")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    try:
        years = [
            int(value)
            for value in parse_csv_option(
                args.years, [str(year) for year in YEARS], "year"
            )
        ]
    except ValueError as error:
        parser.error(str(error))

    for year in years:
        source = args.input_root / f"trec_dl_{year}.csv"
        if not source.exists():
            parser.error(f"input does not exist: {source}")
        destination = args.output_root / f"trec_dl_{year}.csv"
        if destination.exists() and not args.overwrite:
            parser.error(
                f"output exists; pass --overwrite to replace it: {destination}"
            )

        fields, rows = read_csv_rows(source)
        injected_rows = [
            {**row, "passage": inject_query(row["passage"], row["query"])}
            for row in rows
        ]
        atomic_write_csv(destination, fields, injected_rows)
        print(
            f"[query/{year}] appended each query to "
            f"{len(injected_rows)} passages -> {destination}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
