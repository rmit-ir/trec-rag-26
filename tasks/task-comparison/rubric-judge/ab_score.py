"""Compare the prompt-A/B arms (default vs firsthand) from the ab_judge caches.
NO luna calls. Emits data/task-comparison/diversity/prompt_ab.{md,json}.

Reports per arm + the delta:
  Selection change: committed docs/topic; cross-arm docid Jaccard (did the prompt
    change WHICH docs get committed); docs unique to each arm.
  First-hand shift (the point of the variant): primary-source rate (source_type==2)
    and mean source_type over committed docs.
  Committed quality: mean UMBRELA, low-rel rate (≤1), weighted rubric coverage(≥1).
  Answer quality: weighted rubric coverage (partial/full) + overall.

Run: uv run --group aus-agent python tasks/task-comparison/rubric-judge/ab_score.py
"""
from __future__ import annotations

from collections import defaultdict

import common as C

DIV = C.ROOT / "data/task-comparison/diversity"
CJDIR = C.OUT / "ab_judgments"
AJDIR = C.OUT / "ab_answer_judgments"
ARMS = ["default", "firsthand"]


def avg(xs):
    xs = [x for x in xs if x == x]
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    cmap = C.load_json(DIV / "promptab_committed_map.json")
    rinfo = C.load_json(C.OUT / "rubrics_info.json")

    # committed judgments {qid:{docid:{umbrela,coverage,source_type}}}
    cj = defaultdict(dict)
    for p in CJDIR.glob("*.json"):
        d = C.load_json(p)
        if "error" in d:
            continue
        qid = p.stem.split("__", 1)[0]
        cj[qid][d["docid"]] = d

    ndocs = defaultdict(list); umb = defaultdict(list); low = defaultdict(list)
    prim = defaultdict(list); msrc = defaultdict(list); covL = defaultdict(list)
    jacc = []; only = defaultdict(list)

    for qid, arms in cmap.items():
        crit = rinfo[qid]["criteria"]
        cid2w = {c["cid"]: c["weight"] for c in crit}
        tw = sum(cid2w.values()) or 1.0
        jj = cj.get(qid, {})
        sets = {a: set(arms.get(a, [])) for a in ARMS}
        if sets["default"] or sets["firsthand"]:
            u = sets["default"] | sets["firsthand"]
            jacc.append(len(sets["default"] & sets["firsthand"]) / len(u))
        for a in ARMS:
            docs = arms.get(a, [])
            ndocs[a].append(len(docs))
            only[a].append(len(sets[a] - sets["firsthand" if a == "default" else "default"]))
            js = [jj[d] for d in docs if d in jj]
            if js:
                umb[a].append(avg([j["umbrela"] for j in js]))
                low[a].append(sum(1 for j in js if j["umbrela"] <= 1) / len(js))
                prim[a].append(sum(1 for j in js if j.get("source_type") == 2) / len(js))
                msrc[a].append(avg([j.get("source_type", 0) for j in js]))
                best = defaultdict(int)
                for j in js:
                    for cv in j.get("coverage", []):
                        best[cv["cid"]] = max(best[cv["cid"]], cv["grade"])
                covL[a].append(sum(w for cid, w in cid2w.items() if best.get(cid, 0) >= 1) / tw)

    # answer judgments
    acovL = defaultdict(list); acovF = defaultdict(list); aov = defaultdict(list)
    for p in AJDIR.glob("*.json"):
        d = C.load_json(p)
        if "error" in d:
            continue
        arm, qid = d["arm"], d["qid"]
        crit = rinfo[qid]["criteria"]
        cid2w = {c["cid"]: c["weight"] for c in crit}
        tw = sum(cid2w.values()) or 1.0
        g = {c["cid"]: c["grade"] for c in d["criteria_coverage"]}
        acovL[arm].append(sum(w for cid, w in cid2w.items() if g.get(cid, 0) >= 1) / tw)
        acovF[arm].append(sum(w for cid, w in cid2w.items() if g.get(cid, 0) >= 2) / tw)
        aov[arm].append(d["overall"])

    per = {}
    for a in ARMS:
        per[a] = {
            "committed_docs_per_topic": avg(ndocs[a]),
            "docs_unique_to_arm_per_topic": avg(only[a]),
            "primary_source_rate": avg(prim[a]),
            "mean_source_type": avg(msrc[a]),
            "mean_umbrela": avg(umb[a]),
            "low_rel_rate": avg(low[a]),
            "committed_cov_lenient": avg(covL[a]),
            "answer_cov_partial": avg(acovL[a]),
            "answer_cov_full": avg(acovF[a]),
            "answer_overall": avg(aov[a]),
        }
    out = {"n_topics": len(cmap), "cross_arm_committed_jaccard": avg(jacc), "per_arm": per}
    C.dump_json(out, DIV / "prompt_ab.json")

    d, f = per["default"], per["firsthand"]
    def dl(k): return f[k] - d[k]
    L = [f"# Prompt A/B — default vs firsthand ({len(cmap)} dev topics)\n",
         f"_Same 10 topics, backends (semantic,keyword), model. Cross-arm committed-docid "
         f"Jaccard = **{out['cross_arm_committed_jaccard']:.3f}** (how much the two prompts "
         f"commit the SAME docs)._\n",
         "| metric | default | firsthand | Δ (first−def) |",
         "|---|--:|--:|--:|",
         f"| committed docs/topic | {d['committed_docs_per_topic']:.1f} | {f['committed_docs_per_topic']:.1f} | {dl('committed_docs_per_topic'):+.1f} |",
         f"| **primary-source rate** | {d['primary_source_rate']:.3f} | {f['primary_source_rate']:.3f} | {dl('primary_source_rate'):+.3f} |",
         f"| mean source_type (0-2) | {d['mean_source_type']:.3f} | {f['mean_source_type']:.3f} | {dl('mean_source_type'):+.3f} |",
         f"| mean UMBRELA | {d['mean_umbrela']:.3f} | {f['mean_umbrela']:.3f} | {dl('mean_umbrela'):+.3f} |",
         f"| low-rel rate (≤1) | {d['low_rel_rate']:.3f} | {f['low_rel_rate']:.3f} | {dl('low_rel_rate'):+.3f} |",
         f"| committed rubric cov(≥1) | {d['committed_cov_lenient']:.3f} | {f['committed_cov_lenient']:.3f} | {dl('committed_cov_lenient'):+.3f} |",
         f"| **answer** cov(≥1) | {d['answer_cov_partial']:.3f} | {f['answer_cov_partial']:.3f} | {dl('answer_cov_partial'):+.3f} |",
         f"| answer cov(full) | {d['answer_cov_full']:.3f} | {f['answer_cov_full']:.3f} | {dl('answer_cov_full'):+.3f} |",
         f"| **answer overall** (0-3) | {d['answer_overall']:.3f} | {f['answer_overall']:.3f} | {dl('answer_overall'):+.3f} |",
         "\n- **primary-source rate** ↑ under firsthand = the variant did shift committed docs toward first-hand/original sources (its intent).",
         "- Watch **answer overall / cov** for whether that shift helped, hurt, or was neutral to the final answer.",
         "- Low **cross-arm Jaccard** = the prompt materially changed which docs get committed (not just reordered).\n"]
    (DIV / "prompt_ab.md").write_text("\n".join(L) + "\n")
    print("wrote prompt_ab.{json,md}\n")
    for a in ARMS:
        p = per[a]
        print(f"  {a:10} prim={p['primary_source_rate']:.3f} src={p['mean_source_type']:.2f} "
              f"umb={p['mean_umbrela']:.2f} ans_cov={p['answer_cov_partial']:.3f} "
              f"ans_overall={p['answer_overall']:.2f}")
    print(f"  cross-arm committed Jaccard: {out['cross_arm_committed_jaccard']:.3f}")


if __name__ == "__main__":
    main()
