#!/usr/bin/env python3
"""Build a scorable version of the official dev rubrics.

The 30 research-rubrics dev topics ship 755 criteria that cannot be fed to a
grader as-is. Two independent problems, both of which silently corrupt a score
rather than announcing themselves:

**1. 98 criteria carry a NEGATIVE weight** (−5 to −1) and one carries 0. These
are penalties — "the response incorrectly defines a theorem" (−5), "contains
messy, unnecessary formulas" (−4). RAGDoll's ``_coerce_criterion`` does
``weight = max(0, min(5, weight)); if weight <= 0: return None``, so handing it
the official file deletes **exactly the criteria that detect bad behaviour**,
13.0% of all criteria and 14.0% of total absolute weight, on all 30 topics. The
resulting score can only be inflated, and nothing in the output says so.

**2. 47 criteria demand output the TREC RAG 2026 contract forbids.** The answer
schema is a list of plain-prose sentences with citation markers: no images, no
Markdown, and at most 1,024 words (``skills/trec-rag-2026-track-guidelines``,
"RAG response length: up to 1,024 words per narrative"). So "includes a
geometric diagram for each theorem" is unsatisfiable by *any* conforming
submission, and grading against it penalizes a system for obeying the rules.
Where a rubric and the guideline conflict, the guideline wins.

This script emits ``data/task-comparison/dev-rubrics-fixed.jsonl`` with every
criterion classified and nothing dropped, so a scorer can honour all three
kinds and a reader can audit the calls:

- ``kind="reward"``   — normal positive criterion, graded, counts in the denominator.
- ``kind="penalty"``  — negative weight; satisfying it SUBTRACTS ``|weight|``.
                        Kept, never deleted.
- ``waived=true``     — unsatisfiable under the output contract; excluded from
                        both numerator and denominator, with ``waived_reason``.

**On the word-count rule specifically**, the naive reading over-waives. "The
response contains at most 2,000 words" is *satisfied* by a conforming
1,024-word answer — it is free points, not a conflict, and every system earns
them equally. Only a criterion that cannot be met at ≤1,024 words is waived.
That distinction is why the classifier looks at the direction of the bound
rather than matching the word "words".

Classification is by rule, not by model, so it is deterministic and reviewable.
Every waiver is written to ``dev-rubrics-waived.md`` for eyeballing — the rules
are conservative but they are still rules, and a wrong waiver silently removes a
criterion we should have been graded on.

    uv run --no-project python \\
        tasks/task-comparison/scripts/fix_dev_rubrics.py
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OFFICIAL = (ROOT / "data/official/trec-rag-2026-data/trec-rag-2026"
            / "development-data/researchrubrics-dev-rubrics"
            / "research-rubrics-dev-rubrics.jsonl")
OUT_JSONL = ROOT / "data/task-comparison/dev-rubrics-fixed.jsonl"
OUT_AUDIT = ROOT / "data/task-comparison/dev-rubrics-waived.md"

WORD_CAP = 1024

# Official axis -> RAGDoll criterion type (ragdoll.rubric.prompts.CRITERION_TYPES).
AXIS_TO_TYPE = {
    "Explicit Criteria": "explicit",
    "Implicit Criteria": "implicit",
    "Synthesis of Information": "synthesis",
    "Communication Quality": "communication",
    "Instruction Following": "instruction",
    "References & Citation Quality": "references",
    "Miscellaneous": "explicit",
}

# A visual artifact cannot exist in a list of prose sentences. Guarded so
# "figure out", "picture of health" and the verb "chart" do not match.
VISUAL = re.compile(
    r"\b(diagram|figures?|images?|illustrations?|pictures?|drawings?|"
    r"screenshots?|flowcharts?|infographics?|visual aids?)\b", re.I)
# Layout the contract forbids: "Do not use Markdown syntax (headings, bullets,
# numbering, bold, fences) or JSON."
MARKDOWN = re.compile(
    r"\b(markdown|bullet(?:ed)? (?:point|list)|numbered list|table format|"
    r"in a table|as a table|tables?\b[^.]{0,40}\b(?:format|column|row)|"
    r"section headers?|headings?|code block|latex|rendered)\b", re.I)
# Citation APPARATUS the contract strips: markers live in `answer[].citations`,
# never in `answer[].text`, so a style guide or a rendered citation list cannot
# appear. Deliberately narrow — "references the EU AI Act", "cites Hebb, 1949"
# and "label each problem with its competition and year" are all satisfiable in
# prose, and 24 of 30 baseline answers fail them for real. Waiving those would
# hide the largest weakness the rubrics found.
CITATION_APPARATUS = re.compile(
    r"\b(?:official format|MLA|APA\b|Chicago(?: style)?|IEEE\b|BibTeX|"
    r"footnotes?|bibliograph|reference list|works cited|"
    r"displays? the citations|citations? (?:are )?(?:displayed|listed))\b", re.I)
# A lower bound above the cap, or a range whose floor exceeds it.
LOWER_BOUND = re.compile(
    r"\b(?:at least|no fewer than|minimum of|more than|exceed(?:s|ing)?|"
    r"longer than)\s+(?:approximately\s+)?([\d,]{3,6})\s*words?\b", re.I)
RANGE_BOUND = re.compile(
    r"\bbetween\s+([\d,]{3,6})\s*(?:and|-|–|to)\s*([\d,]{3,6})\s*words?\b", re.I)


def _int(text: str) -> int:
    return int(text.replace(",", ""))


def waiver_for(text: str) -> str | None:
    """Why this criterion is unsatisfiable under the track contract, or None."""
    if VISUAL.search(text):
        return ("demands a visual artifact; the RAG answer schema is a list of "
                "plain-prose sentences and cannot carry one")
    if CITATION_APPARATUS.search(text):
        return ("demands citation apparatus (a style format, footnotes, or a "
                "rendered reference list); citation markers are carried in "
                "answer[].citations and stripped from answer[].text")
    if MARKDOWN.search(text):
        return ("demands Markdown/layout; the answer contract forbids headings, "
                "bullets, numbering, tables, fences and JSON")
    match = RANGE_BOUND.search(text)
    if match:
        low, high = _int(match.group(1)), _int(match.group(2))
        # A range is only a conflict when even its floor breaks the cap. A
        # 500-2000 band is satisfiable at 1,024; a 1500-3000 band is not.
        if low > WORD_CAP:
            return (f"requires at least {low:,} words; the guideline caps a "
                    f"response at {WORD_CAP:,}")
        if high > WORD_CAP:
            return None  # satisfiable inside the cap — not a conflict
    match = LOWER_BOUND.search(text)
    if match and _int(match.group(1)) > WORD_CAP:
        return (f"requires more than {_int(match.group(1)):,} words; the "
                f"guideline caps a response at {WORD_CAP:,}")
    return None


def convert(record: dict) -> dict:
    criteria = []
    for index, item in enumerate(record["rubrics"]):
        weight = float(item["weight"])
        text = str(item["criterion"]).strip()
        reason = waiver_for(text)
        criteria.append({
            "cid": f"{record['qid']}::c{index:02d}",
            "text": text,
            # RAGDoll's grader reads `text` and its scorer reads `weight`; keep
            # its shape so the grading half is untouched, and carry the sign in
            # `signed_weight` where its clamp cannot reach it.
            "weight": min(5, int(round(abs(weight)))),
            "signed_weight": weight,
            "kind": "penalty" if weight < 0 else "reward",
            "type": AXIS_TO_TYPE.get(item.get("axis", ""), "explicit"),
            "tier": "mandatory" if abs(weight) >= 4 else "optional",
            "axis": item.get("axis"),
            "waived": reason is not None,
            "waived_reason": reason,
        })
    return {
        "qid": record["qid"],
        "query": record.get("query", ""),
        "domain": record.get("domain"),
        "conceptual_breadth": record.get("conceptual_breadth"),
        "logical_nesting": record.get("logical_nesting"),
        "exploration": record.get("exploration"),
        "criteria": criteria,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", type=Path, default=OFFICIAL)
    parser.add_argument("--out", type=Path, default=OUT_JSONL)
    parser.add_argument("--audit", type=Path, default=OUT_AUDIT)
    args = parser.parse_args()

    topics_tsv = (args.official.parents[1] / "topics"
                  / "research-rubrics-topics-dev.tsv")
    queries = {}
    if topics_tsv.exists():
        for line in topics_tsv.read_text(encoding="utf-8").splitlines():
            if line.strip():
                qid, _, text = line.partition("\t")
                queries[qid.strip()] = text.strip()

    records = [json.loads(l) for l in
               args.official.read_text(encoding="utf-8").splitlines() if l.strip()]
    fixed = []
    for record in records:
        converted = convert(record)
        converted["query"] = queries.get(converted["qid"], converted["query"])
        fixed.append(converted)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in fixed),
        encoding="utf-8")

    everything = [c for r in fixed for c in r["criteria"]]
    kinds = collections.Counter(c["kind"] for c in everything)
    waived = [c for c in everything if c["waived"]]
    reasons = collections.Counter(
        c["waived_reason"].split(";")[0] for c in waived)
    scorable = [c for c in everything if not c["waived"]]
    reward_weight = sum(c["signed_weight"] for c in scorable
                        if c["signed_weight"] > 0)
    penalty_weight = sum(-c["signed_weight"] for c in scorable
                         if c["signed_weight"] < 0)

    lines = ["# Waived dev-rubric criteria",
             "",
             "Generated by `tasks/task-comparison/scripts/fix_dev_rubrics.py`. "
             "Each criterion below demands output the TREC RAG 2026 answer "
             "contract forbids, so no conforming submission can satisfy it. "
             "They are excluded from both numerator and denominator rather "
             "than scored as failures.",
             "",
             f"{len(waived)} of {len(everything)} criteria waived "
             f"({len(waived) / len(everything):.1%}), across "
             f"{len({c['cid'].split('::')[0] for c in waived})} of "
             f"{len(fixed)} topics.",
             ""]
    for reason, count in reasons.most_common():
        lines.append(f"- **{count}** — {reason}")
    lines += ["", "## Every waived criterion", "",
              "| cid | w | axis | criterion |", "|---|--:|---|---|"]
    for c in waived:
        text = c["text"].replace("|", "\\|")
        lines.append(f"| `{c['cid']}` | {c['signed_weight']:+.0f} | "
                     f"{c['axis']} | {text[:300]} |")
    args.audit.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {args.out.relative_to(ROOT)}  ({len(fixed)} topics, "
          f"{len(everything)} criteria)")
    print(f"  reward   {kinds['reward']:4d}   penalty {kinds['penalty']:4d} "
          f"(RAGDoll would have deleted every penalty)")
    print(f"  waived   {len(waived):4d}   scorable {len(scorable):4d}")
    print(f"  scorable weight: +{reward_weight:.0f} reward, "
          f"-{penalty_weight:.0f} penalty")
    print(f"wrote {args.audit.relative_to(ROOT)} — review the waivers; a wrong "
          f"one silently removes a criterion we should be graded on")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
