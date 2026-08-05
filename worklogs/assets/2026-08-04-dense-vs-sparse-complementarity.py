#!/usr/bin/env python3
"""Are the dense and sparse retrievers bringing back complementary documents?

Result 8 of `worklogs/2026-08-04-test119-vs-official-baselines.md`. Unlike the
cited-reference Jaccard in Result 2, this reads the **trajectories**
(`data/outputs/aus_agent/*.trajectory.json`), so it compares what each retriever
actually returned rather than what the generator later chose to cite.

`test-semantic-119` and `test-keyword-119` are single-engine runs — every one of
their ~1,070 `search` tool calls passes `search_engine="semantic"` and
`"keyword"` respectively — but the agent *writes its own query* for each engine,
so the disjointness measured here is end-to-end pipeline complementarity, not a
controlled A/B of two ranking functions over identical queries. Read it as "what
would fusing these two runs buy", which is the operational question.

Needs the archived eval tree restored for the support/arena halves (see
`~/local_large/trec-rag-26/ARCHIVE-MANIFEST-2026-08-04.md`); the retrieval half
reads only `data/outputs/`, which is not archived away.

    uv run --no-project python \
        worklogs/assets/2026-08-04-dense-vs-sparse-complementarity.py
"""
from __future__ import annotations

import collections
import glob
import json
import math
import statistics as st
from pathlib import Path

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
EVAL = ROOT / "data/task-comparison/test119-eval"
SUPPORT = EVAL / "support-judgments/gpt-5.6-luna"
METRICS = EVAL / "support-metrics"
ARENA = EVAL / "arena-judgments/gpt-5.6-luna"
DENSE, SPARSE = "test-semantic-119", "test-keyword-119"
LABEL = {DENSE: "ours-semantic", SPARSE: "ours-keyword"}
OPPONENT = "base-agentic-bm25"


def corr(xs, ys) -> float:
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    return num / den if den else float("nan")


def load_trajectories() -> tuple[dict, dict]:
    """Retrieved docids and search-engine usage per run, from the trajectories."""
    retrieved: dict[str, dict[str, list[str]]] = collections.defaultdict(dict)
    engines: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    queries: dict[str, list[str]] = collections.defaultdict(list)
    for path in sorted(glob.glob(str(ROOT / "data/outputs/aus_agent/*.output.json"))):
        meta = json.load(open(path, encoding="utf-8")).get("metadata", {})
        run = meta.get("run_id")
        if run not in (DENSE, SPARSE):
            continue
        traj = json.load(open(path.replace(".output.json", ".trajectory.json"),
                              encoding="utf-8"))
        retrieved[run][meta["narrative_id"]] = traj.get("retrieved_docids") or []
        for msg in traj.get("raw_messages", []):
            if isinstance(msg, dict) and msg.get("name") == "search":
                args = json.loads(msg["arguments"])
                engines[run][args.get("search_engine")] += 1
                queries[run].append(args.get("query", ""))
    for run in (DENSE, SPARSE):
        print(f"  {LABEL[run]:14s} engines={dict(engines[run])}"
              f"  {len(queries[run])} queries, mean {st.mean(len(q.split()) for q in queries[run]):.1f} words"
              f"  {len(retrieved[run])} topics")
    return retrieved, queries


def section_retrieval(retrieved) -> list[str]:
    qids = sorted(retrieved[DENSE], key=lambda q: int(q.split("-")[1]))
    jac, ovl, uniq_d, uniq_s, lift = [], [], [], [], []
    for q in qids:
        d, s = set(retrieved[DENSE][q]), set(retrieved[SPARSE][q])
        inter, union = len(d & s), len(d | s)
        jac.append(inter / union if union else 0.0)
        ovl.append(inter / min(len(d), len(s)) if min(len(d), len(s)) else 0.0)
        uniq_d.append(len(d - s) / len(d) if d else 0.0)
        uniq_s.append(len(s - d) / len(s) if s else 0.0)
        lift.append(union / max(len(d), len(s)) if max(len(d), len(s)) else 0.0)
    print("\n=== retrieved sets ===")
    print(f"  docs/topic: dense {st.mean(len(retrieved[DENSE][q]) for q in qids):.1f},"
          f" sparse {st.mean(len(retrieved[SPARSE][q]) for q in qids):.1f}")
    print(f"  Jaccard   mean {st.mean(jac):.4f}  median {st.median(jac):.4f}  max {max(jac):.3f}")
    print(f"  overlap coefficient mean {st.mean(ovl):.4f}")
    print(f"  unique to dense  {st.mean(uniq_d):.1%} of its own set")
    print(f"  unique to sparse {st.mean(uniq_s):.1%} of its own set")
    print(f"  union / larger set {st.mean(lift):.3f}x")
    print(f"  topics with zero overlap: "
          f"{sum(1 for q in qids if not set(retrieved[DENSE][q]) & set(retrieved[SPARSE][q]))}/{len(qids)}")
    return qids


def section_cited(retrieved, qids) -> None:
    cited = {LABEL[r]: {json.loads(l)["metadata"]["narrative_id"]: set(json.loads(l)["references"])
                        for l in (EVAL / f"{LABEL[r]}.jsonl").read_text(
                            encoding="utf-8").splitlines() if l.strip()}
             for r in (DENSE, SPARSE)}
    other = {DENSE: SPARSE, SPARSE: DENSE}
    print("\n=== cited sets ===")
    cj = []
    for q in qids:
        d, s = cited["ours-semantic"][q], cited["ours-keyword"][q]
        cj.append(len(d & s) / len(d | s) if (d | s) else 0.0)
    print(f"  cited Jaccard mean {st.mean(cj):.4f}")
    for run in (DENSE, SPARSE):
        unreachable = [len(cited[LABEL[run]][q] - set(retrieved[other[run]][q]))
                       / max(len(cited[LABEL[run]][q]), 1) for q in qids]
        used = [len(cited[LABEL[run]][q] & set(retrieved[run][q]))
                / max(len(retrieved[run][q]), 1) for q in qids]
        print(f"  {LABEL[run]:14s} cites {st.mean(used):.1%} of what it retrieved;"
              f" {st.mean(unreachable):.1%} of its citations point at documents the"
              f" other retriever never returned")


def section_support_quality(retrieved) -> None:
    """Is the non-overlapping material as good as the shared material?

    If the unique half were junk, fusing would add noise rather than coverage.
    """
    other = {"ours-semantic": SPARSE, "ours-keyword": DENSE}
    scores = {"FS": 2, "PS": 1, "NS": 0}
    buckets = collections.defaultdict(collections.Counter)
    for path in SUPPORT.glob("ours-*.json"):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec["status"] != "completed":
            continue
        shared = rec["docid"] in set(retrieved[other[rec["run_id"]]].get(rec["topic_id"], []))
        buckets[(rec["run_id"], "both" if shared else "only this one")][rec["support_label"]] += 1
    print("\n=== support of a citation, by whether the other retriever also found the doc ===")
    print(f"{'run':15s} {'found by':14s} {'n':>6s} {'FS':>5s} {'PS':>5s} {'NS':>5s} {'mean 0-2':>9s}")
    for run in ("ours-semantic", "ours-keyword"):
        for kind in ("both", "only this one"):
            c = buckets[(run, kind)]
            n = sum(c.values())
            mean = sum(scores[k] * v for k, v in c.items()) / n
            print(f"{run:15s} {kind:14s} {n:>6d} {c['FS']:>5d} {c['PS']:>5d} {c['NS']:>5d} {mean:>9.3f}")


def section_oracle() -> None:
    """Do the two runs succeed on the same topics? Sets the fusion ceiling."""
    metrics = {lab: {json.loads(l)["topic_id"]: json.loads(l)
                     for l in (METRICS / f"{lab}.jsonl").read_text(
                         encoding="utf-8").splitlines() if l.strip()}
               for lab in ("ours-semantic", "ours-keyword", OPPONENT)}
    qids = sorted(metrics["ours-semantic"], key=lambda q: int(q.split("-")[1]))
    key = "weighted_precision_first_citation"
    d = [metrics["ours-semantic"][q][key] for q in qids]
    s = [metrics["ours-keyword"][q][key] for q in qids]
    print("\n=== per-topic agreement and the oracle ceiling ===")
    print(f"  weighted precision: dense {st.mean(d):.4f}, sparse {st.mean(s):.4f},"
          f" {OPPONENT} {st.mean(metrics[OPPONENT][q][key] for q in qids):.4f}")
    print(f"  corr(dense, sparse) = {corr(d, s):+.3f};"
          f" mean |per-topic difference| = {st.mean(abs(a - b) for a, b in zip(d, s)):.4f}")
    print(f"  oracle max per topic = {st.mean(max(a, b) for a, b in zip(d, s)):.4f}"
          f"  (+{st.mean(max(a, b) for a, b in zip(d, s)) - max(st.mean(d), st.mean(s)):.4f})")
    print(f"  dense better on {sum(1 for a, b in zip(d, s) if a > b)} topics,"
          f" sparse better on {sum(1 for a, b in zip(d, s) if b > a)}")

    def arena(label):
        seen = collections.defaultdict(dict)
        for path in ARENA.glob(f"*__{label}__{OPPONENT}__o*.json"):
            rec = json.loads(path.read_text(encoding="utf-8"))
            seen[rec["topic_id"]][rec["orientation"]] = rec["preferred_run_id"]
        return {q: (1.0 if all(v[i] == label for i in (0, 1))
                    else 0.0 if all(v[i] == OPPONENT for i in (0, 1)) else 0.5)
                for q, v in seen.items()}

    ad, asp = arena("ours-semantic"), arena("ours-keyword")
    both = [q for q in qids if q in ad and q in asp]
    print(f"  arena vs {OPPONENT}: dense {st.mean(ad[q] for q in both):.3f},"
          f" sparse {st.mean(asp[q] for q in both):.3f},"
          f" corr {corr([ad[q] for q in both], [asp[q] for q in both]):+.3f}")
    print(f"  same outcome on {sum(1 for q in both if ad[q] == asp[q])}/{len(both)} topics;"
          f" exactly one of the two beats the baseline on"
          f" {sum(1 for q in both if (ad[q] == 1) != (asp[q] == 1))}")
    print(f"  oracle pick-better-run = {st.mean(max(ad[q], asp[q]) for q in both):.3f}")


def main() -> int:
    print("=== runs ===")
    retrieved, _ = load_trajectories()
    qids = section_retrieval(retrieved)
    section_cited(retrieved, qids)
    section_support_quality(retrieved)
    section_oracle()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
