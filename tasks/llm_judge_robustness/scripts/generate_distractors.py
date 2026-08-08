#!/usr/bin/env python3
"""Generate prompt-controlled distractor passages for TREC-DL queries."""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import time
import tempfile
from pathlib import Path
from decimal import Decimal
from typing import Any, Callable, Iterable

from translate_queries import (
    DEFAULT_INPUT_ROOT,
    LANGUAGES,
    REPO_ROOT,
    YEARS,
    atomic_write_jsonl,
    parse_csv_option,
    read_checkpoint,
    read_queries,
)

DEFAULT_PROMPT_ROOT = REPO_ROOT / "tasks" / "llm_judge_robustness" / "configs" / "perturbations"
DEFAULT_TRANSLATION_ROOT = (
    REPO_ROOT / "data" / "ragdoll-robustness" / "derived" / "query-translations"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "ragdoll-robustness" / "derived" / "distractors"
DEFAULT_MODEL_ID = "gpt-5.6-terra"
PROMPTS = {
    "related-topic": ("related-topic.txt", "Related Topic", "G_rel"),
    "hypothetical": ("hypothetical.txt", "Hypothetical", "G_hypo"),
    "negation": ("negation.txt", "Negation", "G_neg"),
    "modal-statement": ("modal-statement.txt", "Modal Statement", "G_modal"),
}


def read_evidence(path: Path, minimum_relevance: int = 2) -> dict[tuple[str, str], list[str]]:
    """Collect deduplicated answer-bearing passages for each exact qid/query pair."""
    evidence: dict[tuple[str, str], list[str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"qid", "query", "passage", "relevance"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"{path}: expected columns {sorted(required)}")
        for line_number, row in enumerate(reader, start=2):
            try:
                relevance = int(row["relevance"])
            except (TypeError, ValueError) as error:
                raise ValueError(f"{path}:{line_number}: invalid relevance") from error
            if relevance < minimum_relevance:
                continue
            key = (row["qid"].strip(), row["query"].strip())
            passage = row["passage"].strip()
            values = evidence.setdefault(key, [])
            if passage and passage not in values:
                values.append(passage)
    return evidence


def read_max_relevance(path: Path) -> dict[tuple[str, str], int]:
    """Return the highest available judgment for each exact query variant."""
    maxima: dict[tuple[str, str], int] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for line_number, row in enumerate(reader, start=2):
            try:
                relevance = int(row["relevance"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"{path}:{line_number}: invalid relevance") from error
            key = (row["qid"].strip(), row["query"].strip())
            maxima[key] = max(maxima.get(key, relevance), relevance)
    return maxima


def write_skipped_csv(output_root: Path, rows: list[dict[str, Any]]) -> Path:
    """Atomically record query variants excluded for lacking grade-2+ evidence."""
    destination = output_root / "skipped-no-grade2-evidence.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = ["year", "qid", "translation_id", "query", "maximum_relevance", "reason"]
    fd, temporary_name = tempfile.mkstemp(prefix=".skipped.", suffix=".csv", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        Path(temporary_name).replace(destination)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return destination


def load_query_texts(
    *, year: int, language_slug: str, source_items: list[dict[str, str]], translation_root: Path
) -> dict[str, str]:
    """Resolve English source text or require a complete translated-query checkpoint."""
    if language_slug == "english":
        return {item["translation_id"]: item["query"] for item in source_items}
    path = translation_root / language_slug / f"{year}.jsonl"
    rows = read_checkpoint(path)
    translated = {
        str(row.get("translation_id", row["qid"])): str(row["translated_query"]).strip()
        for row in rows
    }
    expected = {item["translation_id"] for item in source_items}
    if set(translated) != expected:
        missing = sorted(expected - set(translated))
        raise ValueError(f"{path}: incomplete translation checkpoint; missing {len(missing)} rows")
    return translated


def read_distractor_checkpoint(path: Path) -> list[dict[str, Any]]:
    """Load generated rows while rejecting truncated or duplicate identities."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            identity = str(row.get("translation_id", row.get("qid", "")))
            if (
                not identity
                or identity in seen
                or not str(row.get("title", "")).strip()
                or not str(row.get("text", "")).strip()
            ):
                raise ValueError(f"{path}:{line_number}: invalid or duplicate distractor row")
            seen.add(identity)
            rows.append(row)
    return rows


def write_usage_csv(
    output_root: Path, *, input_rate: Decimal | None, output_rate: Decimal | None
) -> Path:
    """Build a cumulative, resume-safe token and optional cost report."""
    fields = [
        "year", "qid", "translation_id", "category", "language", "model_id",
        "input_tokens", "output_tokens", "total_tokens", "input_cost_usd",
        "output_cost_usd", "estimated_cost_usd",
    ]
    report_rows: list[dict[str, Any]] = []
    for path in sorted(output_root.glob("*/*/*.jsonl")):
        for row in read_distractor_checkpoint(path):
            input_tokens = row.get("input_tokens")
            output_tokens = row.get("output_tokens")
            input_cost = (
                Decimal(int(input_tokens)) * input_rate / Decimal(1_000_000)
                if input_tokens is not None and input_rate is not None else None
            )
            output_cost = (
                Decimal(int(output_tokens)) * output_rate / Decimal(1_000_000)
                if output_tokens is not None and output_rate is not None else None
            )
            estimated = (
                input_cost + output_cost
                if input_cost is not None and output_cost is not None else None
            )
            report_rows.append({
                "year": row["year"],
                "qid": row["qid"],
                "translation_id": row.get("translation_id", row["qid"]),
                "category": row["category"],
                "language": row["language"],
                "model_id": row["model_id"],
                "input_tokens": input_tokens if input_tokens is not None else "",
                "output_tokens": output_tokens if output_tokens is not None else "",
                "total_tokens": row.get("total_tokens", ""),
                "input_cost_usd": f"{input_cost:.9f}" if input_cost is not None else "",
                "output_cost_usd": f"{output_cost:.9f}" if output_cost is not None else "",
                "estimated_cost_usd": f"{estimated:.9f}" if estimated is not None else "",
            })
    destination = output_root / "usage.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".usage.", suffix=".csv", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(report_rows)
        Path(temporary_name).replace(destination)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return destination


def render_prompt(template: str, *, query: str, evidence: list[str], language: str) -> str:
    """Fill exactly the placeholders owned by the adapted perturbation prompts."""
    selected = evidence[:3]
    if not selected:
        raise ValueError("cannot generate a distractor without gold answer-bearing evidence")
    evidence_text = "\n\n".join(f"[{index}] {text[:2500]}" for index, text in enumerate(selected, 1))
    rendered = (
        template.replace("{{QUERY}}", query)
        .replace("{{GOLD_EVIDENCE}}", evidence_text)
        .replace("{{OUTPUT_LANGUAGE}}", language)
    )
    leftovers = re.findall(r"{{[^{}]+}}", rendered)
    if leftovers:
        raise ValueError(f"unresolved prompt placeholders: {leftovers}")
    return rendered


def parse_json_response(text: str) -> dict[str, str]:
    """Parse the required title/text object, tolerating only a surrounding code fence."""
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    parsed = json.loads(value)
    if not isinstance(parsed, dict) or set(parsed) != {"title", "text"}:
        raise ValueError("response must be a JSON object containing only title and text")
    title = str(parsed["title"]).strip()
    passage = str(parsed["text"]).strip()
    if not title or not passage:
        raise ValueError("response title and text must be non-empty")
    return {"title": title, "text": passage}


def generate_one(
    client: Any, model_id: str, prompt: str, *, max_attempts: int,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, str], dict[str, int]]:
    """Generate one JSON distractor through the Azure OpenAI-compatible endpoint."""
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "system",
                        "content": "Create the requested distractor and return only the specified JSON object.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content or ""
            result = parse_json_response(text)
            raw_usage = getattr(response, "usage", None)
            usage = {
                key: int(value)
                for key, value in {
                    "input_tokens": getattr(raw_usage, "prompt_tokens", None),
                    "output_tokens": getattr(raw_usage, "completion_tokens", None),
                    "total_tokens": getattr(raw_usage, "total_tokens", None),
                }.items()
                if value is not None
            }
            return result, usage
        except Exception as error:
            if getattr(error, "status_code", None) in {401, 403}:
                raise RuntimeError(
                    "Azure OpenAI credentials were rejected; refresh OPENAI_API_KEY or "
                    "AZURE_OPENAI_API_KEY and rerun to resume"
                ) from error
            if attempt == max_attempts:
                raise
            sleep(min(30.0, 2 ** (attempt - 1) + random.random()))
    raise AssertionError("unreachable")


def make_client() -> Any:
    """Create the repository's Azure-hosted OpenAI-compatible client."""
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass
    if "OPENAI_API_KEY" not in os.environ and os.getenv("AZURE_OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_API_KEY"]
    missing = [name for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL") if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"missing Azure OpenAI configuration: {', '.join(missing)}")
    from openai import OpenAI

    return OpenAI(
        base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"],
        timeout=180.0, max_retries=4,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--translation-root", type=Path, default=DEFAULT_TRANSLATION_ROOT)
    parser.add_argument("--prompt-root", type=Path, default=DEFAULT_PROMPT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--years", default="2021,2022,2023")
    parser.add_argument("--languages", default="english")
    parser.add_argument("--categories", default="all")
    parser.add_argument("--model-id", default=os.getenv("DISTRACTOR_MODEL_ID", DEFAULT_MODEL_ID))
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--max-requests", type=int, help="Stop after this many generated distractors.")
    parser.add_argument("--input-usd-per-million-tokens", type=Decimal)
    parser.add_argument("--output-usd-per-million-tokens", type=Decimal)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.max_attempts < 1:
        parser.error("--max-attempts must be positive")
    if (
        (args.input_usd_per_million_tokens is None)
        != (args.output_usd_per_million_tokens is None)
    ):
        parser.error("provide both input and output token rates, or neither")
    if any(
        rate is not None and rate < 0
        for rate in (args.input_usd_per_million_tokens, args.output_usd_per_million_tokens)
    ):
        parser.error("token rates cannot be negative")

    try:
        years = [int(value) for value in parse_csv_option(args.years, [str(y) for y in YEARS], "year")]
        languages = parse_csv_option(args.languages, LANGUAGES, "language")
        categories = parse_csv_option(args.categories, PROMPTS, "category")
    except ValueError as error:
        parser.error(str(error))

    templates = {
        category: (args.prompt_root / PROMPTS[category][0]).read_text(encoding="utf-8")
        for category in categories
    }
    sources = {year: read_queries(args.input_root / f"trec_dl_{year}.csv") for year in years}
    evidence = {
        year: read_evidence(args.input_root / f"trec_dl_{year}.csv") for year in years
    }
    maxima = {
        year: read_max_relevance(args.input_root / f"trec_dl_{year}.csv") for year in years
    }
    skipped = [
        {
            "year": year,
            "qid": item["qid"],
            "translation_id": item["translation_id"],
            "query": item["query"],
            "maximum_relevance": maxima[year][(item["qid"], item["query"])],
            "reason": "no passage with relevance >= 2",
        }
        for year in years
        for item in sources[year]
        if (item["qid"], item["query"]) not in evidence[year]
    ]
    eligible_count = sum(len(sources[year]) for year in years) - len(skipped)
    planned = eligible_count * len(languages) * len(categories)
    print(
        f"Planned distractors: {planned} from {eligible_count} eligible queries; "
        f"skipping {len(skipped)} without grade-2+ evidence"
    )
    if args.dry_run:
        return 0

    skipped_path = write_skipped_csv(args.output_root, skipped)
    print(f"Wrote skipped-query report: {skipped_path}")

    client = make_client()
    requests = 0
    usage_total: dict[str, int] = {}
    for category in categories:
        _, category_name, generator_label = PROMPTS[category]
        for language_slug in languages:
            language = LANGUAGES[language_slug]
            for year in years:
                source_items = sources[year]
                query_texts = load_query_texts(
                    year=year, language_slug=language_slug, source_items=source_items,
                    translation_root=args.translation_root,
                )
                path = args.output_root / category / language_slug / f"{year}.jsonl"
                rows = read_distractor_checkpoint(path)
                eligible_ids = {
                    item["translation_id"] for item in source_items
                    if (item["qid"], item["query"]) in evidence[year]
                }
                ineligible_rows = [
                    row for row in rows
                    if str(row.get("translation_id", row["qid"])) not in eligible_ids
                ]
                if ineligible_rows:
                    print(
                        f"[{category}/{language_slug}/{year}] removing "
                        f"{len(ineligible_rows)} rows without grade-2+ evidence"
                    )
                    rows = [
                        row for row in rows
                        if str(row.get("translation_id", row["qid"])) in eligible_ids
                    ]
                    atomic_write_jsonl(path, rows)
                accounted_rows = [
                    row for row in rows
                    if all(row.get(key) is not None for key in (
                        "input_tokens", "output_tokens", "total_tokens"
                    ))
                ]
                if len(accounted_rows) != len(rows):
                    print(
                        f"[{category}/{language_slug}/{year}] regenerating "
                        f"{len(rows) - len(accounted_rows)} legacy rows without token usage"
                    )
                    rows = accounted_rows
                    atomic_write_jsonl(path, rows)
                completed = {str(row.get("translation_id", row["qid"])) for row in rows}
                for item in source_items:
                    identity = item["translation_id"]
                    if identity in completed:
                        continue
                    if args.max_requests is not None and requests >= args.max_requests:
                        report = write_usage_csv(
                            args.output_root,
                            input_rate=args.input_usd_per_million_tokens,
                            output_rate=args.output_usd_per_million_tokens,
                        )
                        print(f"Stopped at --max-requests={args.max_requests}; rerun to resume.")
                        print(f"Wrote token report: {report}")
                        return 0
                    gold = evidence[year].get((item["qid"], item["query"]), [])
                    if not gold:
                        continue
                    prompt = render_prompt(
                        templates[category], query=query_texts[identity], evidence=gold,
                        language=language.name,
                    )
                    generated, usage = generate_one(
                        client, args.model_id, prompt, max_attempts=args.max_attempts
                    )
                    for key, value in usage.items():
                        usage_total[key] = usage_total.get(key, 0) + value
                    rows.append({
                        "year": year,
                        "qid": item["qid"],
                        "translation_id": identity,
                        "language": language.code,
                        "language_name": language.name,
                        "category": category_name,
                        "generator_label": generator_label,
                        "query": query_texts[identity],
                        "source_query": item["query"],
                        "title": generated["title"],
                        "text": generated["text"],
                        "model_id": args.model_id,
                        "prompt_file": PROMPTS[category][0],
                        "input_tokens": usage.get("input_tokens"),
                        "output_tokens": usage.get("output_tokens"),
                        "total_tokens": usage.get("total_tokens"),
                    })
                    atomic_write_jsonl(path, rows)
                    requests += 1
                    print(f"[{category}/{language_slug}/{year}] {len(rows)}/{len(source_items)} usage={usage_total}")
    report = write_usage_csv(
        args.output_root,
        input_rate=args.input_usd_per_million_tokens,
        output_rate=args.output_usd_per_million_tokens,
    )
    print(f"Complete. Requests={requests}; usage={usage_total}")
    print(f"Wrote token report: {report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted; completed distractors are checkpointed and will resume.", file=sys.stderr)
        raise SystemExit(130)
