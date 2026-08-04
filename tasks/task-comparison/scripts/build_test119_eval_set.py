#!/usr/bin/env python3
"""Assemble the four-run comparison set for the 119 official test narratives.

Two of ours (``test-semantic-119`` / ``test-keyword-119``, lifted out of
``data/outputs/aus_agent/*.output.json``) and the two organizer baselines that
ship in the data submodule. Everything is emitted in the organizer's
``rag_output_trec_rag_2026.jsonl`` shape, one line per narrative, in official
topic order (``rag2026-0`` … ``rag2026-118``), so every downstream judge sees
the four runs through the identical schema.

Also runs ``validate_rag_output`` over all four and prints the structural stats
that need no LLM at all (word counts, references, citation density, uncited
rate) — those alone answer a surprising amount of "how do we compare".

    PYTHONPATH=src uv run --group aus-agent python \
        tasks/task-comparison/scripts/build_test119_eval_set.py
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from pathlib import Path

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
sys.path.insert(0, str(ROOT / "src"))

from ragrun.outputs import submission_output, validate_rag_output  # noqa: E402

OFFICIAL = ROOT / "data/official/trec-rag-2026-data/trec-rag-2026"
TOPICS_TSV = OFFICIAL / "test-data/trec_rag_2026_queries.tsv"
BASELINE_DIR = OFFICIAL / "baselines/rag"
OUT_DIR = ROOT / "data/task-comparison/test119-eval"

# label -> (kind, source). ``kind`` picks the loader.
RUNS: dict[str, tuple[str, str]] = {
    "ours-semantic": ("aus_agent", "test-semantic-119"),
    "ours-keyword": ("aus_agent", "test-keyword-119"),
    "base-agentic-bm25": (
        "baseline", "gpt-5.6-sol_medium_agentic-search_bm25_output-mode-answer.jsonl"),
    "base-singlepass": (
        "baseline",
        "gpt-5.6-sol_medium_single-pass-rag_first-qwen3-8b-listwise-top100.jsonl"),
}


def load_topics() -> dict[str, str]:
    """narrative_id -> narrative, in the official file's order."""
    topics: dict[str, str] = {}
    for line in TOPICS_TSV.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        qid, _, narrative = line.partition("\t")
        topics[qid.strip()] = narrative.strip()
    return topics


def load_aus_agent(run_id: str) -> dict[str, dict]:
    """Our artifacts, keyed by narrative_id, projected to the strict schema.

    A run_id may legitimately have several artifacts for one narrative (a
    resumed run writes a new timestamp); the newest filename wins, since the
    timestamp prefix sorts chronologically.
    """
    rows: dict[str, tuple[str, dict]] = {}
    for path in sorted(glob.glob(str(ROOT / "data/outputs/aus_agent/*.output.json"))):
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        if obj.get("metadata", {}).get("run_id") != run_id:
            continue
        qid = obj["metadata"]["narrative_id"]
        stamp = Path(path).name.split(".")[0]
        if qid not in rows or stamp > rows[qid][0]:
            rows[qid] = (stamp, submission_output(obj))
    return {qid: row for qid, (_stamp, row) in rows.items()}


def load_baseline(filename: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for line in (BASELINE_DIR / filename).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        rows[obj["metadata"]["narrative_id"]] = obj
    return rows


def word_count(row: dict) -> int:
    """The spec's normative count: sum over answer[].text of whitespace splits."""
    return sum(len(item["text"].split()) for item in row["answer"])


def cited_indices(row: dict) -> set[int]:
    """Reference positions actually cited, normalizing docid-style citations."""
    used: set[int] = set()
    for item in row["answer"]:
        for c in item["citations"]:
            if isinstance(c, str):
                if c in row["references"]:
                    used.add(row["references"].index(c))
            elif type(c) is int and 0 <= c < len(row["references"]):
                used.add(c)
    return used


def stats_for(label: str, rows: dict[str, dict]) -> dict:
    words = [word_count(r) for r in rows.values()]
    refs = [len(r["references"]) for r in rows.values()]
    sents = [len(r["answer"]) for r in rows.values()]
    cites_per_sent, uncited, total_sents = [], 0, 0
    unused_refs = []
    for row in rows.values():
        for item in row["answer"]:
            n = len(item["citations"])
            cites_per_sent.append(n)
            uncited += (n == 0)
            total_sents += 1
        unused_refs.append(len(row["references"]) - len(cited_indices(row)))
    return {
        "run": label,
        "narratives": len(rows),
        "words_mean": round(statistics.mean(words), 1),
        "words_min": min(words),
        "words_max": max(words),
        "over_1024": sum(w > 1024 for w in words),
        "answer_objects_mean": round(statistics.mean(sents), 1),
        "refs_mean": round(statistics.mean(refs), 2),
        "refs_min": min(refs),
        "refs_max": max(refs),
        "citations_per_object_mean": round(statistics.mean(cites_per_sent), 2),
        "uncited_object_rate": round(uncited / total_sents, 4),
        "uncited_objects": uncited,
        "unused_refs_mean": round(statistics.mean(unused_refs), 2),
        "distinct_refs_total": len({d for r in rows.values() for d in r["references"]}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    topics = load_topics()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    all_rows: dict[str, dict[str, dict]] = {}
    table: list[dict] = []
    problems: list[str] = []

    for label, (kind, source) in RUNS.items():
        rows = (load_aus_agent(source) if kind == "aus_agent"
                else load_baseline(source))
        missing = [q for q in topics if q not in rows]
        extra = [q for q in rows if q not in topics]
        if missing:
            problems.append(f"{label}: missing {len(missing)} narratives: {missing[:5]}")
        if extra:
            problems.append(f"{label}: {len(extra)} unknown narrative ids: {extra[:5]}")
        for qid, row in rows.items():
            for err in validate_rag_output(row):
                problems.append(f"{label}/{qid}: {err}")

        path = args.out_dir / f"{label}.jsonl"
        with path.open("w", encoding="utf-8") as stream:
            for qid in topics:  # official order
                if qid in rows:
                    stream.write(json.dumps(rows[qid], ensure_ascii=False) + "\n")
        all_rows[label] = rows
        table.append(stats_for(label, rows))
        print(f"wrote {len(rows):3d} narratives -> {path}")

    print("\n=== validation ===")
    print("clean — every run passes validate_rag_output" if not problems
          else "\n".join(problems[:40]))

    print("\n=== structural comparison (no LLM) ===")
    cols = list(table[0])
    width = {c: max(len(c), *(len(str(r[c])) for r in table)) for c in cols}
    print(" | ".join(c.ljust(width[c]) for c in cols))
    print("-+-".join("-" * width[c] for c in cols))
    for row in table:
        print(" | ".join(str(row[c]).ljust(width[c]) for c in cols))

    print("\n=== reference overlap (Jaccard over cited+listed docids, mean/topic) ===")
    labels = list(all_rows)
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            scores = []
            for qid in topics:
                if qid in all_rows[a] and qid in all_rows[b]:
                    sa = set(all_rows[a][qid]["references"])
                    sb = set(all_rows[b][qid]["references"])
                    if sa or sb:
                        scores.append(len(sa & sb) / len(sa | sb))
            print(f"  {a:20s} vs {b:20s}  {statistics.mean(scores):.4f}")

    (args.out_dir / "structural_stats.json").write_text(
        json.dumps(table, indent=2) + "\n", encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
