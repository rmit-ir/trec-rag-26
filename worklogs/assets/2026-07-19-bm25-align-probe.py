"""Compare Pyserini REST API (climbmix-400b) vs our BM25 server, top-k alignment.

For each query: GET <pyserini>/v1/climbmix-400b/search?query=&hits=K
            and POST <ours>/api/search {"query": q, "hits": K}.
Metrics per query: overlap@5, overlap@10, Jaccard@10, top1 agreement,
rank-displacement for shared docids, score ranges (scale check).
"""
import base64
import json
import os
import sys

import requests

K = 10
PYSERINI_BASE = "http://api.castorini.uwaterloo.ca/v1/climbmix-400b"
OURS_BASE = "https://index-climbmix-bm25.dsync.net"

QUERIES = [
    "index fund definition tracks market index",
    "Albert Einstein",
    "how to change default program macos",
    "Markov chain stationary distribution",
    "photosynthesis light reactions",
    "history of the silk road trade",
    "python garbage collection reference counting",
    "climate change sea level rise projections",
    "homebrew python 3 default",
    "combinatorics pigeonhole principle example",
]


def pyserini_search(q: str) -> list[tuple[str, float]]:
    tok = os.environ["PYSERINI_API_TOKEN"]
    r = requests.get(f"{PYSERINI_BASE}/search",
                     params={"query": q, "hits": K},
                     headers={"Authorization": f"Bearer {tok}",
                              "User-Agent": "bm25-align-probe/1.0"},
                     timeout=60)
    r.raise_for_status()
    return [(c["docid"], float(c["score"]))
            for c in r.json().get("candidates", [])]


def ours_search(q: str) -> list[tuple[str, float]]:
    key = os.environ["SEARCH_API_KEY"]
    basic = base64.b64encode(key.encode()).decode() if ":" in key else key
    r = requests.post(f"{OURS_BASE}/api/search",
                      json={"query": q, "hits": K},
                      headers={"Authorization": f"Basic {basic}",
                               "User-Agent": "bm25-align-probe/1.0"},
                      timeout=60)
    r.raise_for_status()
    return [(h["_id"], float(h["_score"]))
            for h in r.json().get("hits", {}).get("hits", [])]


def main() -> None:
    rows = []
    raw: dict[str, dict] = {}
    for q in QUERIES:
        p = pyserini_search(q)
        o = ours_search(q)
        p_ids = [d for d, _ in p]
        o_ids = [d for d, _ in o]
        p_set, o_set = set(p_ids), set(o_ids)
        inter10 = p_set & o_set
        inter5 = set(p_ids[:5]) & set(o_ids[:5])
        jac = len(inter10) / len(p_set | o_set) if (p_set | o_set) else 0.0
        top1 = bool(p_ids and o_ids and p_ids[0] == o_ids[0])
        # mean |rank_p - rank_o| over shared docids
        disp = [abs(p_ids.index(d) - o_ids.index(d)) for d in inter10]
        mean_disp = sum(disp) / len(disp) if disp else None
        rows.append({
            "query": q,
            "pyserini_n": len(p_ids), "ours_n": len(o_ids),
            "overlap@5": len(inter5), "overlap@10": len(inter10),
            "jaccard@10": round(jac, 3), "top1_same": top1,
            "mean_rank_disp": (round(mean_disp, 2)
                               if mean_disp is not None else None),
            "p_top1": p_ids[0] if p_ids else None,
            "o_top1": o_ids[0] if o_ids else None,
            "p_score_range": [round(p[0][1], 3), round(p[-1][1], 3)] if p else None,
            "o_score_range": [round(o[0][1], 3), round(o[-1][1], 3)] if o else None,
        })
        raw[q] = {"pyserini": p, "ours": o}
        r = rows[-1]
        print(f"[{r['overlap@10']:>2}/10 ov10 | {r['overlap@5']}/5 ov5 | "
              f"top1={'=' if top1 else 'X'}] {q}")

    n = len(rows)
    print("\n=== aggregate ===")
    print(f"queries: {n}")
    print(f"mean overlap@10: {sum(r['overlap@10'] for r in rows) / n:.2f}")
    print(f"mean overlap@5:  {sum(r['overlap@5'] for r in rows) / n:.2f}")
    print(f"mean jaccard@10: {sum(r['jaccard@10'] for r in rows) / n:.3f}")
    print(f"top1 agreement:  {sum(r['top1_same'] for r in rows)}/{n}")
    disps = [r["mean_rank_disp"] for r in rows if r["mean_rank_disp"] is not None]
    if disps:
        print(f"mean rank displacement (shared docs): {sum(disps)/len(disps):.2f}")

    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bm25_align_results.json"
    with open(out, "w") as f:
        json.dump({"k": K, "rows": rows, "raw": raw}, f, indent=2)
    print(f"\nfull matrix + raw hit lists -> {out}")


if __name__ == "__main__":
    main()
