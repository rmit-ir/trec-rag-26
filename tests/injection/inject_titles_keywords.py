#!/usr/bin/env python3
"""Inject generated titles and keyword lists into resolved RAG responses."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_ANSWERS = (
    REPO_ROOT / "evaluation-results" / "aus-agent"
    / "answers.resolved.jsonl"
)
DEFAULT_TITLES = SCRIPT_DIR / "titles.jsonl"
DEFAULT_KEYWORDS = SCRIPT_DIR / "keywords.jsonl"
DEFAULT_OUTPUT = SCRIPT_DIR / "answers.injected.jsonl"


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield number, json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: invalid JSON") from exc


def query_for(row: dict[str, Any], path: Path, number: int) -> str:
    query = row.get("query") or row.get("topic")
    if not isinstance(query, str) or not query.strip():
        raise ValueError(f"{path}:{number}: missing query/topic")
    return query.strip()


def load_titles(path: Path) -> dict[str, str]:
    titles: dict[str, str] = {}
    for number, row in read_jsonl(path):
        query = query_for(row, path, number)
        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"{path}:{number}: missing title")
        if query in titles and titles[query] != title.strip():
            raise ValueError(f"{path}:{number}: conflicting title for query")
        titles[query] = title.strip()
    return titles


def load_keywords(path: Path) -> dict[str, list[str]]:
    by_query: dict[str, list[str]] = {}
    for number, row in read_jsonl(path):
        query = query_for(row, path, number)
        keywords = row.get("keywords")
        if (not isinstance(keywords, list)
                or not keywords
                or not all(
                    isinstance(value, str) and value.strip()
                    for value in keywords)):
            raise ValueError(
                f"{path}:{number}: keywords must be a non-empty string list")
        cleaned = [" ".join(value.split()) for value in keywords]
        if query in by_query and by_query[query] != cleaned:
            raise ValueError(
                f"{path}:{number}: conflicting keywords for query")
        by_query[query] = cleaned
    return by_query


def injected_text(title: str, keywords: list[str], answer: str) -> str:
    answer = answer.strip()
    if not answer:
        raise ValueError("answer_text is empty")
    return (
        f"Title: {title}\n"
        f"Keywords: {', '.join(keywords)}\n\n"
        f"{answer}"
    )


def build_rows(
    answers_path: Path,
    titles: dict[str, str],
    keywords: dict[str, list[str]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for number, source in read_jsonl(answers_path):
        query = query_for(source, answers_path, number)
        if query not in titles:
            raise ValueError(
                f"{answers_path}:{number}: no generated title for query")
        if query not in keywords:
            raise ValueError(
                f"{answers_path}:{number}: no generated keywords for query")
        answer = source.get("answer_text")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError(
                f"{answers_path}:{number}: missing answer_text")

        row = dict(source)
        row["answer_text"] = injected_text(
            titles[query], keywords[query], answer)
        # RAGDOLL's rubric grader prefers `answer` over `answer_text`.
        # Keep both representations aligned so it grades the injection.
        row["answer"] = [{"text": row["answer_text"], "citations": []}]
        row["response_length"] = len(row["answer_text"].split())
        row["injection"] = {
            "kind": "title_keywords",
            "title": titles[query],
            "keywords": keywords[query],
        }
        output.append(row)
    return output


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
    parser.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS)
    parser.add_argument("--titles", type=Path, default=DEFAULT_TITLES)
    parser.add_argument("--keywords", type=Path, default=DEFAULT_KEYWORDS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = build_rows(
        args.answers,
        load_titles(args.titles),
        load_keywords(args.keywords),
    )
    atomic_write_jsonl(args.output, rows)
    print(f"wrote {len(rows)} injected RAG responses to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
