#!/usr/bin/env python3
"""Extract TREC-DL queries and translate them with the Amazon Translate API.

Outputs are resumable JSONL files grouped as ``<language>/<year>.jsonl``.
English is copied locally; every supported target uses ``TranslateText``.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import sys
import tempfile
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_ROOT = REPO_ROOT / "data" / "ragdoll-robustness" / "gold" / "trec-dl"
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "data" / "ragdoll-robustness" / "derived" / "query-translations"
)
DEFAULT_REGION = "ap-southeast-2"
YEARS = (2021, 2022, 2023)
from cost_tracking import CostRunLogger, DEFAULT_USD_PER_MILLION_CHARACTERS


@dataclass(frozen=True)
class Language:
    slug: str
    code: str
    name: str


LANGUAGES = {
    language.slug: language
    for language in (
        Language("english", "en", "English"),
        Language("arabic", "ar", "Arabic"),
        Language("chinese", "zh", "Chinese (Simplified)"),
        Language("russian", "ru", "Russian"),
        Language("hebrew", "he", "Hebrew"),
        Language("hindi", "hi", "Hindi"),
        Language("vietnamese", "vi", "Vietnamese"),
        Language("thai", "th", "Thai"),
        Language("tagalog", "tl", "Tagalog"),
        Language("swahili", "sw", "Swahili"),
        Language("gaeilge", "ga", "Gaeilge (Irish)"),
        Language("amharic", "am", "Amharic"),
    )
}


def read_queries(path: Path) -> list[dict[str, str]]:
    """Read unique qid/query pairs and preserve conflicting source variants."""
    pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    variants: dict[str, set[str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"qid", "query"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"{path}: expected columns {sorted(required)}")
        for line_number, row in enumerate(reader, start=2):
            qid = (row.get("qid") or "").strip()
            query = (row.get("query") or "").strip()
            if not qid or not query:
                raise ValueError(f"{path}:{line_number}: qid and query must be non-empty")
            pair = (qid, query)
            variants.setdefault(qid, set()).add(query)
            if pair not in seen_pairs:
                pairs.append(pair)
                seen_pairs.add(pair)
    result = []
    for qid, query in pairs:
        translation_id = qid
        if len(variants[qid]) > 1:
            digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:8]
            translation_id = f"{qid}__{digest}"
        result.append({"qid": qid, "translation_id": translation_id, "query": query})
    return result


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Replace a checkpoint only after its complete JSONL payload is durable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary_name).replace(path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def read_checkpoint(path: Path) -> list[dict[str, Any]]:
    """Load and validate a prior checkpoint for safe resume."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            qid = str(row.get("qid", ""))
            translation_id = str(row.get("translation_id", qid))
            if (
                not qid
                or not translation_id
                or translation_id in seen
                or not str(row.get("translated_query", "")).strip()
            ):
                raise ValueError(f"{path}:{line_number}: invalid or duplicate translation row")
            seen.add(translation_id)
            rows.append(row)
    return rows


def translate_query(
    client: Any,
    language: Language,
    text: str,
    *,
    max_attempts: int,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Call TranslateText with bounded retry/backoff and validate its response."""
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.translate_text(
                Text=text,
                SourceLanguageCode="en",
                TargetLanguageCode=language.code,
            )
            translated = str(response.get("TranslatedText", "")).strip()
            if not translated:
                raise ValueError("Amazon Translate returned empty TranslatedText")
            if response.get("SourceLanguageCode") not in (None, "en"):
                raise ValueError(f"unexpected source language: {response['SourceLanguageCode']}")
            if response.get("TargetLanguageCode") not in (None, language.code):
                raise ValueError(f"unexpected target language: {response['TargetLanguageCode']}")
            return translated
        except Exception as error:
            response = getattr(error, "response", {})
            error_code = str(response.get("Error", {}).get("Code", ""))
            if error_code in {
                "ExpiredToken", "ExpiredTokenException", "InvalidClientTokenId",
                "UnrecognizedClientException",
            }:
                raise RuntimeError(
                    f"AWS credentials are invalid or expired ({error_code}); refresh them and rerun "
                    "the same command to resume from the last checkpoint"
                ) from error
            if attempt == max_attempts:
                raise
            sleep(min(30.0, (2 ** (attempt - 1)) + random.random()))
    raise AssertionError("unreachable")


def output_row(
    *, year: int, language: Language, item: dict[str, str], translated: str,
) -> dict[str, Any]:
    """Build the stable artifact schema shared by translated and English rows."""
    return {
        "year": year,
        "qid": item["qid"],
        "translation_id": item["translation_id"],
        "source_language": "en",
        "target_language": language.code,
        "target_language_name": language.name,
        "source_query": item["query"],
        "translated_query": translated,
        "translation_service": None if language.code == "en" else "amazon-translate",
    }


def parse_csv_option(value: str, allowed: Iterable[str], label: str) -> list[str]:
    """Parse comma-separated CLI selections while retaining declared order."""
    allowed_order = list(allowed)
    allowed_set = set(allowed_order)
    selected = allowed_order if value == "all" else [part.strip() for part in value.split(",")]
    unknown = [item for item in selected if item not in allowed_set]
    if unknown:
        raise ValueError(f"unknown {label}: {', '.join(unknown)}")
    return selected


def make_client(region: str) -> Any:
    """Create the Amazon Translate client lazily so extraction needs no boto3 import."""
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass
    import boto3
    from botocore.config import Config

    return boto3.client(
        "translate",
        region_name=region,
        config=Config(read_timeout=300, connect_timeout=30, retries={"max_attempts": 5, "mode": "adaptive"}),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--years", default="2021,2022,2023", help="Comma-separated years, or all.")
    parser.add_argument(
        "--languages", default="all", help=f"Comma-separated slugs, or all: {', '.join(LANGUAGES)}"
    )
    parser.add_argument("--region", default=os.getenv("AWS_REGION", DEFAULT_REGION))
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--max-requests", type=int, help="Stop after this many paid requests (for pilots).")
    parser.add_argument(
        "--usd-per-million-characters",
        type=Decimal,
        default=DEFAULT_USD_PER_MILLION_CHARACTERS,
        help="Estimated standard-translation rate (default: 15.00).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Extract and report without API calls or writes.")
    args = parser.parse_args()
    if args.max_attempts < 1 or args.usd_per_million_characters < 0:
        parser.error("--max-attempts must be positive and the pricing rate cannot be negative")

    try:
        year_names = parse_csv_option(args.years, [str(year) for year in YEARS], "year")
        language_slugs = parse_csv_option(args.languages, LANGUAGES, "language")
    except ValueError as error:
        parser.error(str(error))
    years = [int(year) for year in year_names]
    extracted = {
        year: read_queries(args.input_root / f"trec_dl_{year}.csv") for year in years
    }
    total_queries = sum(len(items) for items in extracted.values())
    print("Extracted " + ", ".join(f"{year}={len(extracted[year])}" for year in years))
    print(f"Selected {len(language_slugs)} languages and {total_queries} source queries")
    if args.dry_run:
        return 0

    needs_translate = any(slug != "english" for slug in language_slugs)
    client = make_client(args.region) if needs_translate else None
    paid_requests = 0
    with CostRunLogger(
        args.output_root,
        rate=args.usd_per_million_characters,
        years=years,
        languages=language_slugs,
    ) as run_log:
        for slug in language_slugs:
            language = LANGUAGES[slug]
            for year in years:
                source_items = extracted[year]
                source_by_id = {item["translation_id"]: item for item in source_items}
                output_path = args.output_root / slug / f"{year}.jsonl"
                rows = read_checkpoint(output_path)
                completed = {str(row.get("translation_id", row["qid"])) for row in rows}
                unknown = completed - set(source_by_id)
                if unknown:
                    raise ValueError(
                        f"{output_path}: checkpoint contains unknown qids: {sorted(unknown)}"
                    )
                pending = [
                    item for item in source_items if item["translation_id"] not in completed
                ]

                if slug == "english":
                    rows.extend(
                        output_row(
                            year=year, language=language, item=item,
                            translated=item["query"],
                        )
                        for item in pending
                    )
                    atomic_write_jsonl(output_path, rows)
                    print(f"[{slug}/{year}] wrote {len(rows)}/{len(source_items)}")
                    continue

                for item in pending:
                    if args.max_requests is not None and paid_requests >= args.max_requests:
                        run_log.status = "partial"
                        print(f"Stopped at --max-requests={args.max_requests}; rerun to resume.")
                        return 0
                    assert client is not None
                    translated = translate_query(
                        client, language, item["query"], max_attempts=args.max_attempts
                    )
                    run_log.record_request(item["query"])
                    rows.append(
                        output_row(
                            year=year, language=language, item=item, translated=translated,
                        )
                    )
                    atomic_write_jsonl(output_path, rows)
                    paid_requests += 1
                    print(
                        f"[{slug}/{year}] checkpoint {len(rows)}/{len(source_items)} "
                        f"(paid requests={paid_requests})"
                    )
    print(f"Complete. Amazon Translate requests: {paid_requests}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted; completed requests are checkpointed and will resume.", file=sys.stderr)
        raise SystemExit(130)
