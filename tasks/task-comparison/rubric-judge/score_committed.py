"""Score the COMMITTED docs per engine on 30 dev topics — the diversity study's
rubric + credibility cuts. NO luna calls (reads the cached judgments).

Treats each engine's committed-doc set as its "evidence set" for a topic and asks:
  RUBRIC BEST-EXPLANATION (per criterion, which engine supplied the best evidence):
    - best_grade[engine][cid] = max coverage grade (0/1/2) over engine's committed
      docs. The "best explainer" of a criterion = engine(s) with the top grade>=1.
    - sole_win  : criteria where ONE engine strictly beats the rest (credit 1)
    - coбest_share : ties split evenly (credit 1/k)  → weighted by criterion weight too
    - unique_criteria : criteria covered (grade>=1) by ONLY this engine
    - weighted_coverage(lenient>=1 / strict>=2) : Σw covered / Σw   (same defn as score.py)
  CREDIBILITY / RESILIENCE proxies (no URLs available → content-quality proxies):
    - mean_umbrela over committed docs
    - low_umbrela_rate  frac of committed docs with umbrela<=1 (on-topic-but-empty
      or off-topic content that still got committed → weak/"bad" evidence)
    - highly_rel_rate   frac with umbrela==3
    (near-dup rate + Vendi come from diversity_metrics.json, merged in.)

Run:  uv run --group aus-agent python \
        tasks/task-comparison/rubric-judge/score_committed.py
Out:  data/task-comparison/diversity/committed_analysis.{json,md}
"""
from __future__ import annotations

import json
from collections import defaultdict

import common as C

DIV = C.ROOT / "data/task-comparison/diversity"
ENG = ["dense", "keyword", "ssr", "lucene"]  # committed_map keys (agent-side names)


def load_committed_judgments(committed):
    """{qid: {docid: {umbrela, coverage}}} for committed docs only."""
    j = defaultdict(dict)
    miss = 0
    for qid, engmap in committed.items():
        docs = set()
        for dl in engmap.values():
            docs.update(dl)
        for docid in docs:
            p = C.JUDGE_DIR / f"{qid}__{docid}.json"
            if not p.exists():
                miss += 1
                continue
            d = C.load_json(p)
            if "error" not in d:
                j[qid][docid] = d
    return j, miss


def main():
    committed = C.load_json(DIV / "committed_map.json")
    rinfo = C.load_json(C.OUT / "rubrics_info.json")
    judg, miss = load_committed_judgments(committed)
    if miss:
        print(f"WARNING: {miss} committed docs have no judgment (run judge_committed.py first)")

    # accumulators over topics
    sole = defaultdict(float); cobest = defaultdict(float); uniq = defaultdict(float)
    wsole = defaultdict(float); wtotal = 0.0
    covL = defaultdict(list); covS = defaultdict(list)
    umeans = defaultdict(list); ulow = defaultdict(list); uhigh = defaultdict(list)
    ndocs = defaultdict(list)

    for qid, engmap in committed.items():
        crit = rinfo[qid]["criteria"]
        cid2w = {c["cid"]: c["weight"] for c in crit}
        total_w = sum(cid2w.values()) or 1.0
        jj = judg.get(qid, {})

        # best coverage grade per (engine, cid) over engine's committed docs
        best = {e: defaultdict(int) for e in ENG}
        for e in ENG:
            for docid in engmap.get(e, []):
                d = jj.get(docid)
                if not d:
                    continue
                for cv in d.get("coverage", []):
                    best[e][cv["cid"]] = max(best[e][cv["cid"]], cv["grade"])

        # per-criterion best-explanation
        for cid, w in cid2w.items():
            wtotal += w
            grades = {e: best[e].get(cid, 0) for e in ENG}
            top = max(grades.values())
            if top >= 1:
                winners = [e for e, g in grades.items() if g == top]
                for e in winners:
                    cobest[e] += 1.0 / len(winners)
                if len(winners) == 1:
                    sole[winners[0]] += 1
                    wsole[winners[0]] += w
                covering = [e for e, g in grades.items() if g >= 1]
                if len(covering) == 1:
                    uniq[covering[0]] += 1

        # weighted coverage per engine + credibility
        for e in ENG:
            wl = sum(w for cid, w in cid2w.items() if best[e].get(cid, 0) >= 1)
            ws = sum(w for cid, w in cid2w.items() if best[e].get(cid, 0) >= 2)
            covL[e].append(wl / total_w); covS[e].append(ws / total_w)
            us = [jj[d]["umbrela"] for d in engmap.get(e, []) if d in jj]
            if us:
                umeans[e].append(sum(us) / len(us))
                ulow[e].append(sum(1 for u in us if u <= 1) / len(us))
                uhigh[e].append(sum(1 for u in us if u == 3) / len(us))
            ndocs[e].append(len(engmap.get(e, [])))

    def avg(xs):
        xs = [x for x in xs if x == x]
        return sum(xs) / len(xs) if xs else float("nan")

    # merge diversity metrics if present
    div = {}
    dp = DIV / "diversity_metrics.json"
    if dp.exists():
        div = C.load_json(dp).get("within_engine", {})

    per = {}
    ncrit_total = sum(len(rinfo[q]["criteria"]) for q in committed)
    for e in ENG:
        per[e] = {
            "committed_docs_per_topic": avg(ndocs[e]),
            "best_explainer_sole_wins": sole[e],
            "best_explainer_cobest_share": cobest[e],
            "best_explainer_win_rate": cobest[e] / ncrit_total,
            "weighted_sole_win_share": wsole[e] / wtotal if wtotal else float("nan"),
            "unique_criteria_covered": uniq[e],
            "cov_lenient": avg(covL[e]),
            "cov_strict": avg(covS[e]),
            "mean_umbrela": avg(umeans[e]),
            "low_umbrela_rate": avg(ulow[e]),
            "highly_rel_rate": avg(uhigh[e]),
            "near_dup_rate": div.get(e, {}).get("nn_dup_rate"),
            "vendi_ratio": div.get(e, {}).get("vendi_ratio"),
            "unique_contrib": div.get(e, {}).get("unique_contrib"),
        }

    out = {"n_topics": len(committed), "n_criteria_total": ncrit_total,
           "judgments_missing": miss, "per_engine": per}
    (DIV / "committed_analysis.json").write_text(json.dumps(out, indent=2))

    # markdown
    L = ["# Committed-doc rubric best-explanation + credibility (30 dev topics)\n",
         f"_Info criteria total across topics: {ncrit_total}. Best-explainer = engine whose "
         f"committed docs supply the top coverage grade for a criterion; ties share credit._\n",
         "## Rubric best-explanation\n",
         "| engine | docs/topic | sole wins | co-best share | win-rate | wtd sole-share | unique criteria | cov(≥1) | cov(≥2) |",
         "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for e in ENG:
        p = per[e]
        L.append(f"| {e} | {p['committed_docs_per_topic']:.1f} | {p['best_explainer_sole_wins']:.0f} "
                 f"| {p['best_explainer_cobest_share']:.1f} | {p['best_explainer_win_rate']:.3f} "
                 f"| {p['weighted_sole_win_share']:.3f} | {p['unique_criteria_covered']:.0f} "
                 f"| {p['cov_lenient']:.3f} | {p['cov_strict']:.3f} |")
    L += ["\n## Credibility / resilience proxies (no URLs → content-quality proxies)\n",
          "| engine | mean UMBRELA | low-rel rate (≤1) | highly-rel rate (=3) | near-dup rate | Vendi/n | unique-contrib |",
          "|---|--:|--:|--:|--:|--:|--:|"]
    for e in ENG:
        p = per[e]
        def f(x): return f"{x:.3f}" if isinstance(x, (int, float)) and x == x else "—"
        L.append(f"| {e} | {f(p['mean_umbrela'])} | {f(p['low_umbrela_rate'])} | {f(p['highly_rel_rate'])} "
                 f"| {f(p['near_dup_rate'])} | {f(p['vendi_ratio'])} | {f(p['unique_contrib'])} |")
    L += ["\n- **low-rel rate** ↑ = engine commits more weak/off-target evidence (worse resilience).",
          "- **near-dup rate** ↑ = more repeated content; **Vendi/n** & **unique-contrib** ↑ = richer/standout support.\n"]
    (DIV / "committed_analysis.md").write_text("\n".join(L) + "\n")

    print("wrote committed_analysis.{json,md}")
    for e in ENG:
        p = per[e]
        print(f"  {e:8} win-rate={p['best_explainer_win_rate']:.3f} uniq={p['unique_criteria_covered']:.0f} "
              f"cov≥1={p['cov_lenient']:.3f} meanUMB={p['mean_umbrela']:.2f} lowrel={p['low_umbrela_rate']:.3f}")


if __name__ == "__main__":
    main()
