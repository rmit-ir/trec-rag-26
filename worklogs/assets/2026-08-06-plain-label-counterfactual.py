#!/usr/bin/env python3
"""Add visible plain-prose labels without changing a draft's claims."""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any

from aus_agent.providers.openai import OpenAIProvider


SOURCE_RUN = "sol-aus-v2-research-first-pre-repair-dev30-20260806"
TARGET_RUN = "sol-aus-v2-plain-label-low8-20260806"
OUTPUT_DIR = Path("data/outputs/aus_agent_v2")

LABEL_SYSTEM = """\
You are the structural compiler at the end of a plain-prose research pipeline.
Decide whether the original request requires visibly distinct repeated
deliverables or named comparison cases that the complete draft already covers
but does not visibly label.

Examples that qualify are a requested series of posts, multiple lessons,
separate case studies, or a comparison of named pilots/countries. Ordinary
thematic changes do not qualify. Do not impose sections merely because they
would look tidy, and do not add Markdown.

Return one exact JSON object:
{"labels":[{"line":8,"prefix":"Post 2 — Retirement investing:"}]}

Rules:
- A prefix is a short plain-prose label ending in a colon, 2 to 10 words.
- Prefix an existing draft line; never replace, split, delete, or add a line.
- Use only names and deliverable terms stated in the request or already present
  in the chosen line.
- Label every member of a genuinely required repeated set consistently, in
  reading order, or label none of them.
- Do not label more than eight lines.
- Do not use #, *, |, brackets, citations, bullets, or numbering syntax; “Post
  1 — Foundations:” is a prose label and is allowed.
- If visible labels are not required, return {"labels":[]}.
- Return JSON only.
"""


def newest_source(qid: str) -> tuple[Path, dict[str, Any]]:
    """Load the newest completed exact-run artifact for one topic."""
    found: list[tuple[str, Path, dict[str, Any]]] = []
    for path in OUTPUT_DIR.glob("*.output.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (obj.get("metadata", {}).get("run_id") == SOURCE_RUN
                and obj.get("metadata", {}).get("narrative_id") == qid
                and obj.get("trace", {}).get("status") == "completed"):
            found.append((path.name.split(".", 1)[0], path, obj))
    if not found:
        raise RuntimeError(f"no source artifact for {qid}")
    _stamp, path, obj = max(found, key=lambda item: item[0])
    return path, obj


def exact_json(text: str) -> dict[str, Any] | None:
    """Accept a bare JSON object and nothing else."""
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def apply_labels(
    answer: list[dict[str, Any]], response: str,
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    """Prefix allowed lines while preserving their text and citations exactly."""
    parsed = exact_json(response)
    stats = {"proposed": 0, "accepted": 0, "rejected": 0}
    errors: list[str] = []
    if parsed is None or set(parsed) != {"labels"} or not isinstance(
            parsed.get("labels"), list):
        return answer, stats, ["response was not an exact labels JSON object"]
    labels = parsed["labels"]
    if len(labels) > 8:
        return answer, stats, ["more than eight labels proposed"]
    revised = copy.deepcopy(answer)
    seen: set[int] = set()
    for label in labels:
        stats["proposed"] += 1
        if not isinstance(label, dict) or set(label) != {"line", "prefix"}:
            errors.append("label did not contain exactly line and prefix")
            continue
        line = label["line"]
        prefix = label["prefix"]
        if (not isinstance(line, int) or not 1 <= line <= len(answer)
                or line in seen or not isinstance(prefix, str)):
            errors.append(f"invalid or duplicate line {line!r}")
            continue
        prefix = " ".join(prefix.split())
        words = prefix.rstrip(":").split()
        if (not prefix.endswith(":") or not 2 <= len(words) <= 10
                or re.search(r"[#*|\[\]\n\r]", prefix)
                or re.match(r"^\s*(?:[-+] |\d+[.)] )", prefix)):
            errors.append(f"unsafe prefix for line {line}")
            continue
        revised[line - 1]["text"] = prefix + " " + answer[line - 1]["text"]
        seen.add(line)
        stats["accepted"] += 1
    stats["rejected"] = stats["proposed"] - stats["accepted"]
    return revised, stats, errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qid", required=True)
    args = parser.parse_args()
    path, obj = newest_source(args.qid)
    query = str(obj["trace"]["metadata"]["query_source"])
    numbered = "\n".join(
        f"{index}: {item['text']}"
        for index, item in enumerate(obj["answer"], 1))
    packet = (
        "ORIGINAL REQUEST\n" + query.strip()
        + "\n\nCOMPLETE DRAFT, ONE LINE PER SENTENCE\n" + numbered)
    provider = OpenAIProvider("openai.gpt-5.6-sol", max_tokens=2_000)
    provider.start(LABEL_SYSTEM, [])
    provider.add_user_message(packet)
    turn = provider.run_turn()
    raw = str(turn.get("text") or "")
    answer, stats, errors = apply_labels(obj["answer"], raw)

    target = copy.deepcopy(obj)
    target["metadata"]["run_id"] = TARGET_RUN
    target["metadata"]["run_desc"] = (
        f"Plain-prose label counterfactual from {SOURCE_RUN}; claims and "
        "citations immutable.")
    target["answer"] = answer
    target["trace"]["summary"]["plain_labels"] = {
        "source_run_id": SOURCE_RUN,
        "source_path": str(path),
        "system_prompt": LABEL_SYSTEM,
        "user_packet": packet,
        "raw_response": raw,
        "stats": stats,
        "errors": errors,
        "usage": turn.get("usage") or {},
    }
    stamp = path.name.split(".", 1)[0]
    target_path = OUTPUT_DIR / f"{stamp}.plain_label_counterfactual.output.json"
    target_path.write_text(
        json.dumps(target, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "qid": args.qid,
        "source": str(path),
        "target": str(target_path),
        "stats": stats,
        "errors": errors,
        "raw": raw,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
