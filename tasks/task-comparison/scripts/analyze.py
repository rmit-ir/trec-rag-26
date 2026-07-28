"""Build the retrieval-backend comparison from aus_agent run outputs.

Reads data/outputs/aus_agent/*.output.json for the four comparison run-ids
(cmp-dense / cmp-keyword / cmp-ssr / cmp-lucene), and for each (backend, topic)
extracts the agent's search trajectory: every query it issued, how many docs
came back, how many were zero-result or failed, how many it committed, and the
final answer size. Emits a per-topic cross-backend matrix + the full query
trajectories as JSON and Markdown.

Usage:
    python data/task-comparison/analyze.py
"""
import json
import glob
import os
from collections import defaultdict

ROOT = "/scratch/fast/kun/projects/trec-rag-26"
OUT_DIR = f"{ROOT}/data/outputs/aus_agent"
DEST = f"{ROOT}/data/task-comparison"

RUNID_TO_BACKEND = {
    "cmp-dense": "dense(semantic)",
    "cmp-keyword": "keyword(BM25-OR)",
    "cmp-ssr": "ssr(GCL-Boolean)",
    "cmp-lucene": "lucene(Boolean)",
}
BACKEND_ORDER = ["dense(semantic)", "keyword(BM25-OR)", "ssr(GCL-Boolean)",
                 "lucene(Boolean)"]


def load_runs():
    """Return {topic: {backend: record}} for completed comparison runs."""
    by_topic = defaultdict(dict)
    for path in glob.glob(f"{OUT_DIR}/*.output.json"):
        try:
            d = json.load(open(path))
        except (OSError, json.JSONDecodeError):
            continue
        meta = d.get("metadata", {})
        run_id = meta.get("run_id")
        if run_id not in RUNID_TO_BACKEND:
            continue
        trace = d.get("trace", {})
        if trace.get("status") not in ("completed", "budget_exhausted"):
            continue
        backend = RUNID_TO_BACKEND[run_id]
        topic = str(meta.get("narrative_id"))
        steps = trace.get("steps", [])
        searches = []
        for s in steps:
            if s.get("type") != "tool_call" or s.get("tool_name") != "search":
                continue
            args = s.get("arguments", {})
            rdocs = s.get("returned_docids") or []
            searches.append({
                "query": args.get("query"),
                "engine": args.get("search_engine"),
                "n": len(rdocs),
                "failed": bool(s.get("failed")),
            })
        all_docids = set()
        for s in steps:
            for did in (s.get("returned_docids") or []):
                all_docids.add(did)
        rec = {
            "status": trace.get("status"),
            "n_searches": len(searches),
            "n_zero": sum(1 for x in searches if x["n"] == 0 and not x["failed"]),
            "n_failed": sum(1 for x in searches if x["failed"]),
            "n_unique_docids": len(all_docids),
            "n_committed": len(d.get("references", [])),
            "answer_chars": len(d.get("answer", "")),
            "duration_ms": trace.get("duration_ms"),
            "queries": [x["query"] for x in searches],
            "searches": searches,
        }
        # keep the latest if duplicated (a topic re-run)
        by_topic[topic][backend] = rec
    return by_topic


def fmt_matrix(by_topic):
    lines = []
    topics = sorted(by_topic, key=lambda t: int(t.split("-")[-1]))
    hdr = ("| topic | backend | status | #search | #zero | #fail | "
           "#uniqDoc | #commit | ans.chars |")
    sep = "|---|---|---|--:|--:|--:|--:|--:|--:|"
    lines += [hdr, sep]
    for t in topics:
        for b in BACKEND_ORDER:
            r = by_topic[t].get(b)
            if not r:
                lines.append(f"| {t} | {b} | — | | | | | | |")
                continue
            lines.append(
                f"| {t} | {b} | {r['status']} | {r['n_searches']} | "
                f"{r['n_zero']} | {r['n_failed']} | {r['n_unique_docids']} | "
                f"{r['n_committed']} | {r['answer_chars']} |")
    return "\n".join(lines)


def fmt_trajectories(by_topic):
    lines = []
    topics = sorted(by_topic, key=lambda t: int(t.split("-")[-1]))
    for t in topics:
        lines.append(f"\n## {t}\n")
        for b in BACKEND_ORDER:
            r = by_topic[t].get(b)
            if not r:
                lines.append(f"### {b}: (no completed run)\n")
                continue
            lines.append(f"### {b}  —  {r['n_searches']} searches, "
                         f"{r['n_committed']} committed, "
                         f"{r['n_zero']} zero, {r['n_failed']} failed")
            for s in r["searches"]:
                tag = ("FAIL" if s["failed"]
                       else ("0" if s["n"] == 0 else str(s["n"])))
                lines.append(f"   - ({tag}) {s['query']}")
            lines.append("")
    return "\n".join(lines)


def main():
    by_topic = load_runs()
    n_runs = sum(len(v) for v in by_topic.values())
    print(f"loaded {n_runs} completed runs across {len(by_topic)} topics")
    for t in sorted(by_topic, key=lambda t: int(t.split('-')[-1])):
        present = [b.split('(')[0] for b in BACKEND_ORDER if b in by_topic[t]]
        print(f"  {t}: {present}")

    matrix = fmt_matrix(by_topic)
    traj = fmt_trajectories(by_topic)
    with open(f"{DEST}/comparison_matrix.md", "w") as f:
        f.write("# Retrieval-backend comparison — 10 topics x 4 backends\n\n")
        f.write(matrix + "\n\n# Full search trajectories\n" + traj)
    with open(f"{DEST}/comparison.json", "w") as f:
        json.dump(by_topic, f, indent=2, ensure_ascii=False)
    print(f"\nwrote {DEST}/comparison_matrix.md and comparison.json")
    print("\n" + matrix)


if __name__ == "__main__":
    main()
