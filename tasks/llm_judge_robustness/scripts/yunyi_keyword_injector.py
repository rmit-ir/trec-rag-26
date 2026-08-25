#!/usr/bin/env python3
"""Inject query keywords at random intervals, then append Yun Yi text.

Examples:
    uv run --project tasks/llm_judge_robustness python \
        tasks/llm_judge_robustness/scripts/yunyi_keyword_injector.py

    uv run --project tasks/llm_judge_robustness python \
        tasks/llm_judge_robustness/scripts/yunyi_keyword_injector.py --overwrite
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from inject_keywords import (
    DEFAULT_KEYWORD_ROOT,
    atomic_write_csv,
    inject_keywords,
    read_csv_rows,
    read_keyword_map,
)
from inject_yun_yi_text import normalize_text, resolve_injection_text
from translate_queries import DEFAULT_INPUT_ROOT, REPO_ROOT, YEARS, parse_csv_option

DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "data"
    / "ragdoll-robustness"
    / "injected"
    / "yunyi_keyword_injector"
)


def inject_yunyi_keywords(
    passage: str,
    insertion_id: str,
    keywords: list[str],
    yunyi_text: str,
) -> str:
    """Disperse keywords through a passage and append Yun Yi at the end."""
    injection = normalize_text(yunyi_text)
    if not injection:
        raise ValueError("Yun Yi injection text must not be empty")
    keyword_injected = inject_keywords(passage, insertion_id, keywords)
    return f"{keyword_injected} {injection}"


def lookup_keywords(
    keyword_map: dict[str, list[str]], query_id: str, query: str
) -> list[str] | None:
    """Resolve keywords for ordinary and hash-disambiguated query identities."""
    keywords = keyword_map.get(query_id)
    if keywords is not None:
        return keywords
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:8]
    return keyword_map.get(f"{query_id}__{digest}")


def main() -> int:
    """Parse CLI flags and create combined keyword plus Yun Yi CSVs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--keyword-root", type=Path, default=DEFAULT_KEYWORD_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--years", default="2021,2022,2023")
    text_group = parser.add_mutually_exclusive_group()
    text_group.add_argument("--text", help="Yun Yi text; overrides INJECTION_TEXT.")
    text_group.add_argument(
        "--text-file", type=Path, help="UTF-8 file containing Yun Yi text."
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    try:
        years = [
            int(value)
            for value in parse_csv_option(args.years, map(str, YEARS), "year")
        ]
        yunyi_text = normalize_text(
            resolve_injection_text(cli_text=args.text, text_file=args.text_file)
        )
        if not yunyi_text:
            raise ValueError(
                "set INJECTION_TEXT or provide Yun Yi text with --text/--text-file"
            )
        keyword_map = read_keyword_map(args.keyword_root / "keywords.jsonl")
    except (OSError, ValueError) as error:
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
        injected_rows: list[dict[str, str]] = []
        missing = 0
        for row in rows:
            query_id = row["qid"].strip()
            keywords = lookup_keywords(keyword_map, query_id, row["query"].strip())
            if keywords is None:
                missing += 1
                passage = f"{normalize_text(row['passage'])} {yunyi_text}"
            else:
                passage = inject_yunyi_keywords(
                    row["passage"],
                    f"{query_id}\0{row['pid'].strip()}",
                    keywords,
                    yunyi_text,
                )
            injected_rows.append({**row, "passage": passage})

        atomic_write_csv(destination, fields, injected_rows)
        print(
            f"[yunyi_keyword_injector/{year}] injected keywords into "
            f"{len(rows) - missing}/{len(rows)} passages and appended Yun Yi to "
            f"all rows ({missing} missing keyword entries) -> {destination}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
