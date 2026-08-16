#!/usr/bin/env python3
"""Extract unique TREC-DL queries and ask Azure GPT-5.6-Terra for key phrases."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from cost_tracking import estimate_cost_usd
from translate_queries import DEFAULT_INPUT_ROOT, REPO_ROOT, YEARS, atomic_write_jsonl

DEFAULT_MODEL_ID = "gpt-5.6-terra"
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "data" / "ragdoll-robustness" / "derived" / "query-keywords"
)


@dataclass(frozen=True)
class QueryItem:
    year: int
    qid: str
    query: str
    query_id: str


def discover_years(input_root: Path) -> list[int]:
    """Find the TREC-DL source files we actually support for this pipeline."""
    years: list[int] = []
    for path in sorted(input_root.glob("trec_dl_*.csv")):
        match = re.fullmatch(r"trec_dl_(\d{4})\.csv", path.name)
        if match and int(match.group(1)) in YEARS:
            years.append(int(match.group(1)))
    if not years:
        raise FileNotFoundError(
            f"{input_root}: no supported trec_dl_YYYY.csv files found for years {YEARS}"
        )
    return years


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
        query_id = qid
        if len(variants[qid]) > 1:
            digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:8]
            query_id = f"{qid}__{digest}"
        result.append({"qid": qid, "query_id": query_id, "query": query})
    return result


def load_unique_queries(input_root: Path, years: list[int]) -> list[QueryItem]:
    """Collect unique query texts across years while keeping provenance for each one."""
    by_query: dict[str, QueryItem] = {}
    for year in years:
        for item in read_queries(input_root / f"trec_dl_{year}.csv"):
            normalized = item["query"].strip()
            if normalized not in by_query:
                by_query[normalized] = QueryItem(
                    year=year,
                    qid=item["qid"],
                    query=item["query"],
                    query_id=item["query_id"],
                )
    return list(by_query.values())


def atomic_write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    """Atomically replace a CSV file only after its full payload is written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        Path(temporary_name).replace(path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def read_checkpoint(path: Path) -> list[dict[str, Any]]:
    """Load an existing keyword checkpoint and reject truncated rows."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            query_id = str(row.get("query_id", ""))
            if (
                not query_id
                or query_id in seen
                or not str(row.get("keywords_json", "")).strip()
            ):
                raise ValueError(f"{path}:{line_number}: invalid or duplicate keyword row")
            seen.add(query_id)
            rows.append(row)
    return rows


def parse_json_response(text: str) -> dict[str, list[str]]:
    """Parse the model response as a strict JSON object with a keywords array."""
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    parsed = json.loads(value)
    if not isinstance(parsed, dict) or set(parsed) != {"keywords"}:
        raise ValueError("response must be a JSON object containing only keywords")
    keywords = parsed["keywords"]
    if not isinstance(keywords, list):
        raise ValueError("keywords must be a JSON array")
    cleaned: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        item = str(keyword).strip()
        if item and item not in seen:
            cleaned.append(item)
            seen.add(item)
    if not cleaned:
        raise ValueError("keywords array must contain at least one non-empty item")
    return {"keywords": cleaned}


def generate_one(
    client: Any,
    model_id: str,
    query: str,
    *,
    max_attempts: int,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Generate keywords for one query through the Azure OpenAI-compatible endpoint."""
    system_prompt = (
        "Extract concise search keywords and key phrases from the user's query. "
        "Return only the requested JSON object."
    )
    user_prompt = (
        "Write 3 to 8 keywords or short key phrases that capture the query's intent.\n"
        "Rules:\n"
        "- Preserve named entities, acronyms, and important numbers.\n"
        "- Keep phrases short, ideally 1 to 5 words.\n"
        "- Do not add explanations, punctuation-only items, or duplicates.\n"
        "- Return JSON exactly in this shape: {\"keywords\": [\"...\"]}\n\n"
        f"Query:\n{query}"
    )
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
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
        base_url=os.environ["OPENAI_BASE_URL"],
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=180.0,
        max_retries=4,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--years", default="all", help="Comma-separated years, or all.")
    parser.add_argument("--model-id", default=os.getenv("KEYWORD_MODEL_ID", DEFAULT_MODEL_ID))
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--max-requests", type=int, help="Stop after this many model calls.")
    parser.add_argument("--input-usd-per-million-tokens", type=Decimal)
    parser.add_argument("--output-usd-per-million-tokens", type=Decimal)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
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

    available_years = discover_years(args.input_root)
    years = available_years if args.years == "all" else [int(value) for value in args.years.split(",")]
    missing_years = sorted(set(years) - set(available_years))
    if missing_years:
        parser.error(
            f"requested years are not present under {args.input_root}: {', '.join(map(str, missing_years))}"
        )

    source_items = load_unique_queries(args.input_root, years)
    print(f"Collected {len(source_items)} unique queries from years {', '.join(map(str, years))}")
    if args.dry_run:
        return 0

    output_path = args.output_root / "keywords.jsonl"
    rows = [] if args.overwrite else read_checkpoint(output_path)
    completed = {str(row.get("query_id", "")) for row in rows}
    if args.overwrite and output_path.exists():
        print(f"Overwriting existing checkpoint: {output_path}")
    pending = [item for item in source_items if item.query_id not in completed]
    print(f"Pending queries: {len(pending)}")

    client = make_client()
    requests = 0
    usage_total: dict[str, int] = {}
    for item in pending:
        if args.max_requests is not None and requests >= args.max_requests:
            print(f"Stopped at --max-requests={args.max_requests}; rerun to resume.")
            break
        generated, usage = generate_one(
            client, args.model_id, item.query, max_attempts=args.max_attempts
        )
        for key, value in usage.items():
            usage_total[key] = usage_total.get(key, 0) + value
        rows.append(
            {
                "year": item.year,
                "qid": item.qid,
                "query_id": item.query_id,
                "query": item.query,
                "keywords_json": json.dumps(generated["keywords"], ensure_ascii=False),
                "model_id": args.model_id,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "keyword_count": len(generated["keywords"]),
            }
        )
        atomic_write_jsonl(output_path, rows)
        requests += 1
        print(f"[{requests}/{len(pending)}] {item.year}/{item.query_id} usage={usage_total}")

    report_rows = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = Decimal("0")
    for row in rows:
        input_tokens = row.get("input_tokens")
        output_tokens = row.get("output_tokens")
        input_cost = (
            estimate_cost_usd(int(input_tokens), args.input_usd_per_million_tokens)
            if input_tokens is not None and args.input_usd_per_million_tokens is not None
            else None
        )
        output_cost = (
            estimate_cost_usd(int(output_tokens), args.output_usd_per_million_tokens)
            if output_tokens is not None and args.output_usd_per_million_tokens is not None
            else None
        )
        estimated = input_cost + output_cost if input_cost is not None and output_cost is not None else None
        if input_tokens is not None:
            total_input_tokens += int(input_tokens)
        if output_tokens is not None:
            total_output_tokens += int(output_tokens)
        if estimated is not None:
            total_cost += estimated
        report_rows.append(
            {
                "year": row["year"],
                "qid": row["qid"],
                "query_id": row["query_id"],
                "model_id": row["model_id"],
                "input_tokens": input_tokens if input_tokens is not None else "",
                "output_tokens": output_tokens if output_tokens is not None else "",
                "total_tokens": row.get("total_tokens", ""),
                "input_cost_usd": f"{input_cost:.9f}" if input_cost is not None else "",
                "output_cost_usd": f"{output_cost:.9f}" if output_cost is not None else "",
                "estimated_cost_usd": f"{estimated:.9f}" if estimated is not None else "",
            }
        )
    if report_rows:
        atomic_write_csv(args.output_root / "usage.csv", report_rows, [
            "year",
            "qid",
            "query_id",
            "model_id",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "input_cost_usd",
            "output_cost_usd",
            "estimated_cost_usd",
        ])
        (args.output_root / "_cost-total.json").write_text(
            json.dumps(
                {
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "successful_requests": len(rows),
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "estimated_cost_usd": float(total_cost),
                    "note": "Estimate before free tier, credits, taxes, or account-specific pricing.",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Wrote token report: {args.output_root / 'usage.csv'}")
        print(f"Updated cumulative cost summary: {args.output_root / '_cost-total.json'}")
    print(f"Complete. Requests={requests}; usage={usage_total}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted; completed keyword rows are checkpointed and will resume.", file=sys.stderr)
        raise SystemExit(130)
