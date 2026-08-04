#!/usr/bin/env python3
"""Weighted citation precision/recall for the four-run comparison set.

This is the one announced 2026 RAG measure that needs **no** rubrics, nuggets,
or qrels — it asks only "does the cited passage support the sentence that cites
it", so it runs on the unjudged test narratives.

RAGDoll owns the methodology and we use its code for everything that defines the
number: ``SUPPORT_EVAL_PROMPT`` (byte-identical to the TREC 2024 judge prompt,
Thakur et al. arXiv:2504.15205 Figure 1), ``parse_support_label``, and
``support_metric``. Only the *execution* is ours: RAGDoll drives models through
the ``pi`` local-agent binary, which is not installed on this host, so calls go
through the same OpenAI-compatible endpoint the agent runs use.

Judge-identity caveat, stated so nobody reads the table without it: the judge is
``gpt-5.6-luna``, the same model that generated our two runs, while the two
baselines came from ``gpt-5.6-sol``. Support judging is an entailment check
rather than a preference vote, so self-preference is far weaker here than it
would be in a pairwise arena — but it is not zero. Treat a gap smaller than a
point or two as noise.

    PYTHONPATH=src uv run --group aus-agent python \
        tasks/task-comparison/scripts/judge_test119_support.py --every 4 --workers 16
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evaluation/ragdoll/src"))

from ragdoll.support.metrics import support_metric  # noqa: E402
from ragdoll.support.prompts import (  # noqa: E402
    parse_support_label, render_support_prompt)

EVAL_DIR = ROOT / "data/task-comparison/test119-eval"
JUDGE_DIR = EVAL_DIR / "support-judgments"
LABELS = ["ours-semantic", "ours-keyword", "base-agentic-bm25", "base-singlepass"]
SUPPORT_LABEL_SCORES = {"FS": 2, "PS": 1, "NS": 0}


def load_env() -> None:
    import os
    env_file = ROOT / ".env"
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def client():
    import os
    from openai import OpenAI
    return OpenAI(base_url=os.environ["OPENAI_BASE_URL"],
                  api_key=os.environ["OPENAI_API_KEY"],
                  timeout=180.0, max_retries=4)


def pairs_for(row: dict, *, first_only: bool, max_chars: int) -> list[dict]:
    """Every (answer object, cited passage) pair the judge must score.

    An answer object with no citations produces no pair — it is omitted from
    precision and scores 0 for recall, which ``support_metric`` handles from the
    empty ``citations`` list rather than from a judgment.
    """
    out = []
    refs = row["references"]
    for si, item in enumerate(row["answer"]):
        cits = item["citations"][:1] if first_only else item["citations"]
        for ci, citation in enumerate(cits):
            docid = refs[citation] if isinstance(citation, int) else citation
            passage = row["segments"].get(docid)
            if not passage:
                continue
            out.append({
                "task_id": f"{row['run_id']}:{row['qid']}:s{si}:c{ci}",
                "run_id": row["run_id"], "topic_id": row["qid"],
                "sentence_index": si, "citation_index": ci, "docid": docid,
                "statement": item["text"], "citation": passage[:max_chars],
            })
    return out


def judge_one(api, model: str, pair: dict, cache: Path) -> dict:
    path = cache / f"{pair['task_id'].replace(':', '__').replace('/', '_')}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    prompt = render_support_prompt(statement=pair["statement"],
                                   citation=pair["citation"])
    try:
        response = api.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}])
        raw = (response.choices[0].message.content or "").strip()
        label = parse_support_label(raw)
        record = {**{k: pair[k] for k in
                     ("task_id", "run_id", "topic_id", "sentence_index",
                      "citation_index", "docid")},
                  "support_label": label, "raw_output": raw[:400],
                  "status": "completed" if label else "unparsed"}
    except Exception as exc:  # noqa: BLE001 — a dead pair must not kill the run
        record = {**{k: pair[k] for k in
                     ("task_id", "run_id", "topic_id", "sentence_index",
                      "citation_index", "docid")},
                  "support_label": None, "raw_output": f"{type(exc).__name__}: {exc}",
                  "status": "failed"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


def assemble(row: dict, judged: dict[tuple[int, int], str | None],
             *, first_only: bool) -> dict:
    """RAGDoll's assignment shape: one row per (topic, run) with scored citations.

    ``-1`` is RAGDoll's "judge did not return a label" marker; such a sentence
    leaves *both* the numerator and the denominator rather than scoring 0.
    """
    sentences = []
    for si, item in enumerate(row["answer"]):
        cits = item["citations"][:1] if first_only else item["citations"]
        scored = []
        for ci, citation in enumerate(cits):
            docid = (row["references"][citation] if isinstance(citation, int)
                     else citation)
            label = judged.get((si, ci))
            scored.append({"citationID": ci, "reference": docid,
                           "support": SUPPORT_LABEL_SCORES.get(label, -1)})
        sentences.append({"sentenceID": si, "text": item["text"],
                          "citations": scored})
    return {"topic_id": row["qid"], "run_id": row["run_id"], "sentences": sentences}


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--every", type=int, default=1,
                        help="Stratified topic sample: keep every Nth narrative "
                             "in official order (1 = all 119).")
    parser.add_argument("--first-citation-only", action="store_true",
                        help="Judge only each object's first citation (the "
                             "TREC 2024 protocol). Default judges all, so the "
                             "all-judged columns are real too.")
    parser.add_argument("--max-chars", type=int, default=24000,
                        help="Truncate a cited document to this many characters.")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--cache-dir", type=Path, default=JUDGE_DIR)
    args = parser.parse_args()

    runs = {}
    for label in LABELS:
        rows = [json.loads(line) for line in
                (EVAL_DIR / f"{label}.resolved.jsonl").read_text(
                    encoding="utf-8").splitlines() if line.strip()]
        runs[label] = rows

    keep = {row["qid"] for row in runs[LABELS[0]][::args.every]}
    print(f"judging {len(keep)} of {len(runs[LABELS[0]])} narratives "
          f"x {len(LABELS)} runs, "
          f"{'first citation only' if args.first_citation_only else 'all citations'}")

    all_pairs, by_run = [], {}
    for label, rows in runs.items():
        by_run[label] = [r for r in rows if r["qid"] in keep]
        for row in by_run[label]:
            all_pairs.extend(pairs_for(row, first_only=args.first_citation_only,
                                       max_chars=args.max_chars))
    cache = args.cache_dir / args.model
    todo = [p for p in all_pairs
            if not (cache / f"{p['task_id'].replace(':', '__')}.json").exists()]
    print(f"{len(all_pairs)} judge pairs, {len(todo)} not cached")

    api = client()
    done, lock = 0, threading.Lock()

    def work(pair):
        nonlocal done
        record = judge_one(api, args.model, pair, cache)
        with lock:
            done += 1
            if done % 200 == 0:
                print(f"  judged {done}/{len(todo)}", flush=True)
        return record

    if todo:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(work, p) for p in todo]):
                future.result()

    # Reload every judgment (cached + fresh) and score.
    labels_by = {}
    statuses = {}
    for pair in all_pairs:
        path = cache / f"{pair['task_id'].replace(':', '__')}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        key = (pair["run_id"], pair["topic_id"])
        labels_by.setdefault(key, {})[(pair["sentence_index"],
                                       pair["citation_index"])] = record["support_label"]
        statuses.setdefault(pair["run_id"], []).append(record["status"])

    metrics_dir = EVAL_DIR / "support-metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    table = []
    for label in LABELS:
        per_topic = []
        for row in by_run[label]:
            assignment = assemble(
                row, labels_by.get((label, row["qid"]), {}),
                first_only=args.first_citation_only)
            per_topic.append(support_metric(assignment))
        (metrics_dir / f"{label}.jsonl").write_text(
            "".join(json.dumps(m.__dict__) + "\n" for m in per_topic),
            encoding="utf-8")
        counts = {s: statuses[label].count(s) for s in set(statuses[label])}
        table.append({
            "run": label,
            "topics": len(per_topic),
            "wP_first": round(statistics.mean(
                m.weighted_precision_first_citation for m in per_topic), 4),
            "wR_first": round(statistics.mean(
                m.weighted_recall_first_citation for m in per_topic), 4),
            "wP_all": round(statistics.mean(
                m.weighted_precision_all_judged_citations for m in per_topic), 4),
            "wR_all": round(statistics.mean(
                m.weighted_recall_all_judged_citations for m in per_topic), 4),
            "hardP": round(statistics.mean(m.hard_precision for m in per_topic), 4),
            "hardR": round(statistics.mean(m.hard_recall for m in per_topic), 4),
            "judge_status": counts,
        })

    print("\n=== weighted citation support (mean over topics) ===")
    cols = ["run", "topics", "wP_first", "wR_first", "wP_all", "wR_all",
            "hardP", "hardR"]
    width = {c: max(len(c), *(len(str(r[c])) for r in table)) for c in cols}
    print(" | ".join(c.ljust(width[c]) for c in cols))
    print("-+-".join("-" * width[c] for c in cols))
    for row in table:
        print(" | ".join(str(row[c]).ljust(width[c]) for c in cols))
    print("\njudge call status:")
    for row in table:
        print(f"  {row['run']:20s} {row['judge_status']}")

    (metrics_dir / "summary.json").write_text(
        json.dumps(table, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
