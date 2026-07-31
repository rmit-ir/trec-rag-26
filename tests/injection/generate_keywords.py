#!/usr/bin/env python3
"""Generate Bedrock keyword lists for every unique resolved-answer query."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

# Import the sibling's tested JSONL/deduplication/checkpoint helpers both when
# invoked as a script and when imported as tests.injection.generate_keywords.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from generate_titles import (  # noqa: E402
    DEFAULT_INPUT,
    DEFAULT_MODEL,
    DEFAULT_REGION,
    atomic_write_jsonl,
    read_jsonl,
    unique_queries,
)

DEFAULT_OUTPUT = SCRIPT_DIR / "keywords.jsonl"
SYSTEM_PROMPT = """\
Extract a comprehensive but concise list of search keywords and short
keyphrases from the supplied user query.

Include the query's named entities, technical terms, methods, standards,
important examples, requested comparisons, and core subject concepts.
Exclude generic task words such as write, explain, response, answer, report,
blog, user, and question unless they are part of a recognized proper name.
Deduplicate case-insensitively and do not invent concepts absent from the query.

Return JSON only, with exactly this shape:
{"keywords":["keyword","short keyphrase"]}
"""
KEYWORD_TOKEN_BUDGETS = (1024, 2048, 4096)
_FENCED_JSON_RE = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


class EmptyKeywordResponse(RuntimeError):
    """The model call contained no final text block."""


class InvalidKeywordResponse(RuntimeError):
    """The model returned final text that was not valid keyword JSON."""


def response_text(response: dict[str, Any]) -> str:
    content = response.get("output", {}).get("message", {}).get("content", [])
    text = " ".join(
        str(block["text"]).strip()
        for block in content
        if isinstance(block, dict) and block.get("text")
    ).strip()
    if not text:
        raise EmptyKeywordResponse("Bedrock returned no keyword text")
    return text


def parse_keywords(text: str) -> list[str]:
    candidate = text.strip()
    fenced = _FENCED_JSON_RE.match(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise InvalidKeywordResponse(
            "Bedrock returned invalid keyword JSON") from exc
    if (not isinstance(payload, dict)
            or set(payload) != {"keywords"}
            or not isinstance(payload["keywords"], list)):
        raise InvalidKeywordResponse(
            "Bedrock keyword JSON must contain only a keywords array")

    keywords: list[str] = []
    seen: set[str] = set()
    for value in payload["keywords"]:
        if not isinstance(value, str) or not value.strip():
            raise InvalidKeywordResponse(
                "Bedrock returned an empty or non-string keyword")
        keyword = " ".join(value.split())
        folded = keyword.casefold()
        if folded not in seen:
            seen.add(folded)
            keywords.append(keyword)
    if not keywords:
        raise InvalidKeywordResponse("Bedrock returned an empty keyword list")
    return keywords


def generate_keywords(client: Any, query: str, model: str) -> list[str]:
    last_response: dict[str, Any] | None = None
    for max_tokens in KEYWORD_TOKEN_BUDGETS:
        last_response = client.converse(
            modelId=model,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{
                "role": "user",
                "content": [{"text": query}],
            }],
            inferenceConfig={
                # GPT-OSS completion tokens include reasoning.
                "maxTokens": max_tokens,
                "temperature": 0,
            },
            # Bedrock forwards OpenAI-specific fields from this object.
            # Keyword extraction is simple, so low effort prevents GPT-OSS
            # from consuming the entire completion budget on reasoning.
            additionalModelRequestFields={"reasoning_effort": "low"},
        )
        try:
            return parse_keywords(response_text(last_response))
        except (EmptyKeywordResponse, InvalidKeywordResponse):
            continue
    stop_reason = (last_response or {}).get("stopReason")
    usage = (last_response or {}).get("usage")
    raise InvalidKeywordResponse(
        "Bedrock returned no valid keyword JSON after token budgets "
        f"{KEYWORD_TOKEN_BUDGETS}; stopReason={stop_reason!r}, usage={usage!r}")


def load_completed(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    completed: dict[str, dict[str, Any]] = {}
    for number, row in read_jsonl(path):
        query, keywords = row.get("query"), row.get("keywords")
        if (not isinstance(query, str)
                or not isinstance(keywords, list)
                or not all(isinstance(value, str) for value in keywords)):
            raise ValueError(
                f"{path}:{number}: existing row must contain query and keywords")
        completed[query] = row
    return completed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--model",
        default=os.environ.get("KEYWORD_BEDROCK_MODEL_ID", DEFAULT_MODEL))
    parser.add_argument(
        "--region",
        default=os.environ.get("KEYWORD_BEDROCK_REGION", DEFAULT_REGION))
    parser.add_argument(
        "--limit", type=int,
        help="generate only the first N unique queries")
    parser.add_argument(
        "--no-resume", action="store_true",
        help="ignore and replace an existing output file")
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")

    queries = unique_queries(args.input)
    if args.limit is not None:
        queries = queries[:args.limit]
    completed = {} if args.no_resume else load_completed(args.output)
    results: list[dict[str, Any]] = []
    client = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
        config=Config(
            read_timeout=120,
            connect_timeout=30,
            retries={"max_attempts": 5, "mode": "adaptive"},
        ),
    )

    for index, item in enumerate(queries, 1):
        query = item["query"]
        if query in completed:
            row = completed[query]
            print(f"[{index}/{len(queries)}] already generated", flush=True)
        else:
            print(f"[{index}/{len(queries)}] generating keywords", flush=True)
            keywords = generate_keywords(client, query, args.model)
            row = {
                "query": query,
                "keywords": keywords,
                "qids": item["qids"],
                "model": args.model,
            }
        results.append(row)
        atomic_write_jsonl(args.output, results)

    print(f"wrote {len(results)} unique query keyword lists to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
