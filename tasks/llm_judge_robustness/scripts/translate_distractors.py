#!/usr/bin/env python3
"""Translate generated English distractors with Amazon Translate.

Inputs and resumable outputs use:
    <root>/<category>/<language>/<year>.jsonl

English files are the source of truth. Each translated row preserves the
generation metadata and replaces ``title`` and ``text`` with translated text.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from generate_distractors import DEFAULT_OUTPUT_ROOT, PROMPTS
from cost_tracking import CostRunLogger, DEFAULT_USD_PER_MILLION_CHARACTERS
from translate_queries import (
    DEFAULT_REGION,
    LANGUAGES,
    YEARS,
    atomic_write_jsonl,
    make_client,
    parse_csv_option,
    translate_query,
)


def read_rows(path: Path, *, expected_language: str) -> list[dict[str, Any]]:
    """Read unique distractors and validate their required text fields."""
    if not path.exists():
        raise ValueError(f"missing distractor file: {path}")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            identity = str(row.get("translation_id", row.get("qid", "")))
            if (
                not identity
                or identity in seen
                or not str(row.get("title", "")).strip()
                or not str(row.get("text", "")).strip()
                or str(row.get("language", "")) != expected_language
            ):
                raise ValueError(f"{path}:{line_number}: invalid or duplicate distractor")
            seen.add(identity)
            rows.append(row)
    return rows


def translated_row(
    source: dict[str, Any], *, language_slug: str, title: str, text: str,
) -> dict[str, Any]:
    """Preserve provenance while publishing translated distractor fields."""
    language = LANGUAGES[language_slug]
    return {
        **source,
        "source_language": "en",
        "language": language.code,
        "language_name": language.name,
        "source_title": str(source["title"]),
        "source_text": str(source["text"]),
        "title": title,
        "text": text,
        "translation_service": "amazon-translate",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--years", default="2021,2022,2023")
    parser.add_argument("--categories", default="all")
    parser.add_argument(
        "--languages",
        default="all",
        help="Comma-separated target slugs, or all non-English languages.",
    )
    parser.add_argument("--region", default=os.getenv("AWS_REGION", DEFAULT_REGION))
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--max-requests", type=int, help="Stop after this many TranslateText calls.")
    parser.add_argument(
        "--usd-per-million-characters",
        type=Decimal,
        default=DEFAULT_USD_PER_MILLION_CHARACTERS,
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.max_attempts < 1 or args.usd_per_million_characters < 0:
        parser.error("--max-attempts must be positive and the pricing rate cannot be negative")

    try:
        years = [int(value) for value in parse_csv_option(args.years, map(str, YEARS), "year")]
        categories = parse_csv_option(args.categories, PROMPTS, "category")
        allowed_languages = [slug for slug in LANGUAGES if slug != "english"]
        languages = parse_csv_option(args.languages, allowed_languages, "language")
    except ValueError as error:
        parser.error(str(error))

    sources: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for category in categories:
        for year in years:
            sources[(category, year)] = read_rows(
                args.root / category / "english" / f"{year}.jsonl",
                expected_language="en",
            )
    rows_per_language = sum(len(rows) for rows in sources.values())
    planned_requests = rows_per_language * len(languages) * 2
    planned_characters = sum(
        len(str(row["title"])) + len(str(row["text"]))
        for rows in sources.values() for row in rows
    ) * len(languages)
    print(
        f"Selected {len(categories)} categories, {len(years)} years, "
        f"{len(languages)} target languages; up to {planned_requests} requests "
        f"and {planned_characters} input characters"
    )
    if args.dry_run:
        return 0

    client = make_client(args.region)
    request_count = 0
    with CostRunLogger(
        args.root,
        rate=args.usd_per_million_characters,
        years=years,
        languages=languages,
    ) as run_log:
        for language_slug in languages:
            language = LANGUAGES[language_slug]
            for category in categories:
                for year in years:
                    source_rows = sources[(category, year)]
                    source_by_id = {
                        str(row.get("translation_id", row["qid"])): row for row in source_rows
                    }
                    output_path = args.root / category / language_slug / f"{year}.jsonl"
                    completed_rows = (
                        read_rows(output_path, expected_language=language.code)
                        if output_path.exists() else []
                    )
                    completed = {
                        str(row.get("translation_id", row["qid"])) for row in completed_rows
                    }
                    unknown = completed - set(source_by_id)
                    if unknown:
                        raise ValueError(f"{output_path}: unknown distractor IDs: {sorted(unknown)}")

                    for identity, source in source_by_id.items():
                        if identity in completed:
                            continue
                        if args.max_requests is not None and request_count + 2 > args.max_requests:
                            run_log.status = "partial"
                            print(f"Stopped at --max-requests={args.max_requests}; rerun to resume.")
                            return 0
                        source_title = str(source["title"])
                        source_text = str(source["text"])
                        title = translate_query(
                            client, language, source_title, max_attempts=args.max_attempts
                        )
                        run_log.record_request(source_title)
                        request_count += 1
                        text = translate_query(
                            client, language, source_text, max_attempts=args.max_attempts
                        )
                        run_log.record_request(source_text)
                        request_count += 1
                        completed_rows.append(
                            translated_row(
                                source, language_slug=language_slug, title=title, text=text
                            )
                        )
                        atomic_write_jsonl(output_path, completed_rows)
                        completed.add(identity)
                        print(
                            f"[{category}/{language_slug}/{year}] "
                            f"checkpoint {len(completed_rows)}/{len(source_rows)}"
                        )
    print(f"Complete. Amazon Translate requests: {request_count}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted; completed rows are checkpointed and will resume.", file=sys.stderr)
        raise SystemExit(130)
