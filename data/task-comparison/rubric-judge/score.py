"""Stage 5 — score each engine per topic, aggregate, and break down by the
official labels + rubric axis. Emits out/rubric_judge_matrix.{md,json}.

Inputs: rubrics_info.json (criteria + weights + labels), provenance.json (which
engine surfaced which doc), retrieved_raw.json (per-sub-need ranked lists, for
nDCG), and the cached judgments in out/judgments/.

Per (qid, engine):
  (a) weighted coverage — Σ weight over info criteria covered by >=1 of THAT
      engine's retrieved docs, / Σ weight of all info criteria. Two thresholds:
      lenient (any covering doc has grade>=1) and strict (grade>=2). A doc
      counts toward an engine's coverage only if that engine surfaced it (per
      provenance).
  (b) precision — mean UMBRELA over that engine's retrieved UNIQUE docs.
  (c) nDCG@10 per sub-need (UMBRELA as gain), averaged over the engine's
      sub-needs for the topic.

Aggregation: mean over topics per engine. Then break downs:
  - by official label (domain / conceptual_breadth / logical_nesting /
    exploration): per label value, per engine, mean weighted-coverage(lenient),
    mean-UMBRELA, mean nDCG — so we can read WHICH topic types each engine wins.
  - by rubric axis: per (engine, axis), lenient weighted-coverage restricted to
    that axis's criteria — which axis each engine covers best.

Usage:
    uv run --group aus-agent python .../score.py [--qids ...]
    (no luna calls; stdlib + common only)
"""
from __future__ import annotations

import argparse
import math
from collections import defaultdict

import common as C

LABELS = ["domain", "conceptual_breadth", "logical_nesting", "exploration"]
K = 10  # retrieval depth used in retrieve.py (for nDCG@K)


def load_judgments(qids):
    """{qid: {docid: {umbrela, coverage:[{cid,grade}]}}} from the cache dir."""
    j = defaultdict(dict)
    for qid in qids:
        for p in C.JUDGE_DIR.glob(f"{qid}__*.json"):
            d = C.load_json(p)
            if "error" in d:
                continue
            j[qid][d["docid"]] = d
    return j


def dcg(gains):
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(ranked_umbrela, all_umbrela_for_ideal, k=10):
    """ranked_umbrela: UMBRELA gains in retrieved order (this list, len<=k).
    Ideal DCG uses the best-possible ordering of the SAME retrieved set."""
    ranked = ranked_umbrela[:k]
    ideal = sorted(all_umbrela_for_ideal, reverse=True)[:k]
    idcg = dcg(ideal)
    if idcg == 0:
        return 0.0
    return dcg(ranked) / idcg


def score_topic(qid, topic, prov, raw, judg):
    """Return {engine: {cov_lenient, cov_strict, mean_umbrela, ndcg,
    per_axis_cov: {axis: lenient_coverage}, n_docs}} for one topic."""
    criteria = topic["criteria"]
    cid2crit = {c["cid"]: c for c in criteria}
    total_w = sum(c["weight"] for c in criteria) or 1.0
    axes = sorted({c["axis"] for c in criteria})
    w_by_axis = defaultdict(float)
    for c in criteria:
        w_by_axis[c["axis"]] += c["weight"]

    # docs surfaced by each engine (from provenance)
    eng_docs = defaultdict(set)
    for docid, plist in prov.items():
        for p in plist:
            eng_docs[p["engine"]].add(docid)

    result = {}
    for eng in C.ENGINES:
        docs = eng_docs.get(eng, set())
        # ---- coverage: best grade per criterion, over THIS engine's docs ----
        best_grade = defaultdict(int)  # cid -> max grade across engine's docs
        for docid in docs:
            jd = judg.get(docid)
            if not jd:
                continue
            for cov in jd["coverage"]:
                best_grade[cov["cid"]] = max(best_grade[cov["cid"]], cov["grade"])
        cov_len_w = sum(cid2crit[c]["weight"] for c, g in best_grade.items()
                        if g >= 1 and c in cid2crit)
        cov_str_w = sum(cid2crit[c]["weight"] for c, g in best_grade.items()
                        if g >= 2 and c in cid2crit)
        per_axis = {}
        for ax in axes:
            covw = sum(cid2crit[c]["weight"] for c, g in best_grade.items()
                       if g >= 1 and c in cid2crit and cid2crit[c]["axis"] == ax)
            per_axis[ax] = covw / (w_by_axis[ax] or 1.0)

        # ---- precision: mean UMBRELA over engine's unique judged docs ----
        umb = [judg[d]["umbrela"] for d in docs if d in judg]
        mean_umb = sum(umb) / len(umb) if umb else 0.0

        # ---- nDCG@10 per sub-need, averaged ----
        ndcgs = []
        for entry in raw.get(eng, []):
            hits = entry["hits"]
            if not hits:
                continue
            gains = [judg.get(d, {}).get("umbrela", 0) for d in hits]
            ndcgs.append(ndcg_at_k(gains, gains, k=K))
        ndcg = sum(ndcgs) / len(ndcgs) if ndcgs else 0.0

        result[eng] = {
            "n_docs": len(docs),
            "n_judged": len(umb),
            "cov_lenient": cov_len_w / total_w,
            "cov_strict": cov_str_w / total_w,
            "mean_umbrela": mean_umb,
            "ndcg": ndcg,
            "per_axis_cov": per_axis,
            "n_subneeds_scored": len(ndcgs),
        }
    return result, axes


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", nargs="*", default=None)
    args = ap.parse_args()

    rubrics_info = C.load_json(C.OUT / "rubrics_info.json")
    prov_all = C.load_json(C.OUT / "provenance.json")
    raw_all = C.load_json(C.OUT / "retrieved_raw.json")
    wanted = C.filter_qids(rubrics_info.keys(), args.qids)
    wanted = [q for q in wanted if q in prov_all]
    judg = load_judgments(wanted)

    per_topic = {}
    axes_by_topic = {}
    for qid in wanted:
        res, axes = score_topic(qid, rubrics_info[qid], prov_all[qid],
                                 raw_all[qid], judg[qid])
        per_topic[qid] = res
        axes_by_topic[qid] = axes

    # ---- aggregate per engine over topics ----
    agg = {}
    for eng in C.ENGINES:
        agg[eng] = {
            "cov_lenient": mean(per_topic[q][eng]["cov_lenient"] for q in wanted),
            "cov_strict": mean(per_topic[q][eng]["cov_strict"] for q in wanted),
            "mean_umbrela": mean(per_topic[q][eng]["mean_umbrela"] for q in wanted),
            "ndcg": mean(per_topic[q][eng]["ndcg"] for q in wanted),
        }

    # ---- breakdown by official label ----
    label_break = {}
    for lab in LABELS:
        buckets = defaultdict(list)  # value -> [qid]
        for q in wanted:
            buckets[rubrics_info[q].get(lab)].append(q)
        label_break[lab] = {}
        for val, qs in buckets.items():
            label_break[lab][str(val)] = {
                eng: {
                    "cov_lenient": mean(per_topic[q][eng]["cov_lenient"] for q in qs),
                    "mean_umbrela": mean(per_topic[q][eng]["mean_umbrela"] for q in qs),
                    "ndcg": mean(per_topic[q][eng]["ndcg"] for q in qs),
                    "n_topics": len(qs),
                } for eng in C.ENGINES
            }

    # ---- breakdown by rubric axis (mean per-axis lenient coverage) ----
    axis_break = {}
    all_axes = sorted({a for qid in wanted for a in axes_by_topic[qid]})
    for ax in all_axes:
        axis_break[ax] = {}
        for eng in C.ENGINES:
            vals = [per_topic[q][eng]["per_axis_cov"].get(ax)
                    for q in wanted if ax in per_topic[q][eng]["per_axis_cov"]]
            axis_break[ax][eng] = mean(v for v in vals if v is not None)

    out_json = {
        "engines": C.ENGINES,
        "qids": wanted,
        "per_topic": per_topic,
        "aggregate": agg,
        "by_label": label_break,
        "by_axis": axis_break,
    }
    C.dump_json(out_json, C.OUT / "rubric_judge_matrix.json")

    # ---- markdown ----
    L = []
    W = L.append
    W("# Rubric-grounded LLM-as-judge retrieval comparison\n")
    W(f"Judge model: `{C.LUNA_MODEL}`. Retrieval unit: multi sub-query per "
      f"engine (k={K}). Topics scored: "
      f"{len(wanted)} ({', '.join(wanted)}).\n")
    W("Coverage = Σ weight of info criteria covered by >=1 of the engine's "
      "retrieved docs, / Σ weight of all info criteria. lenient = judge "
      "grade>=1, strict = grade>=2. mUMBRELA = mean holistic 0-3 relevance "
      "over the engine's unique retrieved docs. nDCG@10 = per-sub-need, "
      "UMBRELA as gain, averaged over sub-needs.\n")

    W("## Aggregate per engine\n")
    W("| engine | cov(lenient) | cov(strict) | mUMBRELA | nDCG@10 |")
    W("|---|--:|--:|--:|--:|")
    for eng in C.ENGINES:
        a = agg[eng]
        W(f"| {eng} | {a['cov_lenient']:.3f} | {a['cov_strict']:.3f} "
          f"| {a['mean_umbrela']:.3f} | {a['ndcg']:.3f} |")
    W("")

    W("## Per-topic detail\n")
    for qid in wanted:
        t = rubrics_info[qid]
        W(f"### {qid} — domain={t['domain']}, breadth={t['conceptual_breadth']}, "
          f"nesting={t['logical_nesting']}, expl={t['exploration']} "
          f"({len(t['criteria'])} info criteria)\n")
        W("| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |")
        W("|---|--:|--:|--:|--:|--:|--:|")
        for eng in C.ENGINES:
            r = per_topic[qid][eng]
            W(f"| {eng} | {r['n_docs']} | {r['n_judged']} | {r['cov_lenient']:.3f} "
              f"| {r['cov_strict']:.3f} | {r['mean_umbrela']:.3f} | {r['ndcg']:.3f} |")
        W("")

    W("## Breakdown by official label (cov=lenient weighted coverage)\n")
    for lab in LABELS:
        W(f"### {lab}\n")
        W("| value | n_topics | metric | " + " | ".join(C.ENGINES) + " |")
        W("|---|--:|---|" + "|".join(["--:"] * len(C.ENGINES)) + "|")
        for val, per_eng in label_break[lab].items():
            n = per_eng[C.ENGINES[0]]["n_topics"]
            for metric in ("cov_lenient", "mean_umbrela", "ndcg"):
                cells = " | ".join(f"{per_eng[e][metric]:.3f}" for e in C.ENGINES)
                W(f"| {val} | {n} | {metric} | {cells} |")
        W("")

    W("## Breakdown by rubric axis (mean per-axis lenient coverage)\n")
    W("| axis | " + " | ".join(C.ENGINES) + " |")
    W("|---|" + "|".join(["--:"] * len(C.ENGINES)) + "|")
    for ax in all_axes:
        cells = " | ".join(f"{axis_break[ax][e]:.3f}" for e in C.ENGINES)
        W(f"| {ax} | {cells} |")
    W("")

    (C.OUT / "rubric_judge_matrix.md").write_text("\n".join(L))
    print(f"wrote {C.OUT / 'rubric_judge_matrix.md'} and .json")
    print("\n=== Aggregate per engine ===")
    for eng in C.ENGINES:
        a = agg[eng]
        print(f"  {eng:<12} cov_len={a['cov_lenient']:.3f} "
              f"cov_str={a['cov_strict']:.3f} mUMB={a['mean_umbrela']:.3f} "
              f"nDCG={a['ndcg']:.3f}")


if __name__ == "__main__":
    main()
