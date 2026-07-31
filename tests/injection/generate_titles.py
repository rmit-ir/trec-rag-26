#!/usr/bin/env python3
"""Generate one concise Bedrock title for every unique resolved-answer query."""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = (
    REPO_ROOT / "evaluation-results" / "aus-agent"
    / "answers.resolved.jsonl"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "titles.jsonl"
DEFAULT_MODEL = "openai.gpt-oss-20b-1:0"
DEFAULT_REGION = "us-east-1"
SYSTEM_PROMPT = """\
Write a concise, informative title for the supplied user query.
Return only the title: no label, quotation marks, explanation, or Markdown.
Preserve the query's actual subject and requested deliverable.
Use at most 14 words.
"""
TITLE_TOKEN_BUDGETS = (512, 1024, 2048)


class EmptyTitleError(RuntimeError):
    """The model completed a call without a final text content block."""


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield number, json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: invalid JSON") from exc


def unique_queries(path: Path) -> list[dict[str, Any]]:
    """Return exact-text unique queries in first-seen order with their qids."""
    by_query: dict[str, dict[str, Any]] = {}
    for number, row in read_jsonl(path):
        query = row.get("query") or row.get("topic")
        qid = row.get("qid") or row.get("topic_id")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"{path}:{number}: missing query/topic")
        if qid is None or not str(qid).strip():
            raise ValueError(f"{path}:{number}: missing qid/topic_id")
        query = query.strip()
        qid = str(qid).strip()
        if query not in by_query:
            by_query[query] = {"query": query, "qids": [qid]}
        elif qid not in by_query[query]["qids"]:
            by_query[query]["qids"].append(qid)
    return list(by_query.values())


def extract_title(response: dict[str, Any]) -> str:
    content = response.get("output", {}).get("message", {}).get("content", [])
    text = " ".join(
        str(block["text"]).strip()
        for block in content
        if isinstance(block, dict) and block.get("text")
    ).strip()
    text = re.sub(r"^\s*title\s*:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip().strip("\"'`").strip()
    text = " ".join(text.split())
    if not text:
        raise EmptyTitleError("Bedrock returned an empty title")
    if "\n" in text:
        raise RuntimeError("Bedrock returned a multi-line title")
    return text


def generate_title(client: Any, query: str, model: str) -> str:
    last_response: dict[str, Any] | None = None
    for max_tokens in TITLE_TOKEN_BUDGETS:
        last_response = client.converse(
            modelId=model,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{
                "role": "user",
                "content": [{"text": query}],
            }],
            inferenceConfig={
                # GPT-OSS completion tokens include reasoning. A tiny budget
                # can be exhausted before the final text block is emitted.
                "maxTokens": max_tokens,
                "temperature": 0,
            },
        )
        try:
            return extract_title(last_response)
        except EmptyTitleError:
            continue
    stop_reason = (last_response or {}).get("stopReason")
    usage = (last_response or {}).get("usage")
    raise EmptyTitleError(
        "Bedrock returned no final title after token budgets "
        f"{TITLE_TOKEN_BUDGETS}; stopReason={stop_reason!r}, usage={usage!r}")


def load_completed(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    completed: dict[str, dict[str, Any]] = {}
    for number, row in read_jsonl(path):
        query, title = row.get("query"), row.get("title")
        if not isinstance(query, str) or not isinstance(title, str):
            raise ValueError(
                f"{path}:{number}: existing row must contain query and title")
        completed[query] = row
    return completed


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(
                    row, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--model",
        default=os.environ.get("TITLE_BEDROCK_MODEL_ID", DEFAULT_MODEL))
    parser.add_argument(
        "--region",
        default=os.environ.get("TITLE_BEDROCK_REGION", DEFAULT_REGION))
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
            print(f"[{index}/{len(queries)}] already titled", flush=True)
        else:
            print(f"[{index}/{len(queries)}] generating title", flush=True)
            title = generate_title(client, query, args.model)
            row = {
                "query": query,
                "title": title,
                "qids": item["qids"],
                "model": args.model,
            }
        results.append(row)
        atomic_write_jsonl(args.output, results)

    print(f"wrote {len(results)} unique query titles to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
