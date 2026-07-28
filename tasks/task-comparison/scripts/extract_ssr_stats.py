"""Per-topic SSR-arm trajectory stats for a given aus_agent run_id.

Computes the same metrics the comparison_matrix.md reports, so an OLD run
(run_id cmp-ssr, Hazel backend, thin snippets) and a NEW run (cmp-ssr-fork,
fork stemmed backend + 256-tok windows) are directly comparable:

  #search  = search tool calls
  #zero    = searches returning empty results (the over-constraint symptom)
  #uniqDoc = distinct docids returned across all searches (recall proxy)
  #commit  = distinct docids committed as evidence
  ev_chars = mean returned evidence size per hit (the "thin window" axis)
  maxAND   = max required-term count in any (^ ...) query (over-constraint axis)

Usage: python extract_ssr_stats.py <run_id> [<run_id2> ...]
"""
import glob
import json
import re
import statistics
import sys
from collections import defaultdict

OUT = "/scratch/fast/kun/projects/trec-rag-26/data/outputs/aus_agent"


def and_arity(query: str) -> int:
    """Largest number of whitespace-separated required terms inside a top-level
    (^ ...) AND — a crude over-constraint proxy (counts atoms, ignores nesting)."""
    best = 0
    for m in re.finditer(r"\(\^([^()]*)\)", query or ""):
        best = max(best, len(m.group(1).split()))
    return best


def stats_for(run_id: str) -> dict:
    rows = {}
    for f in glob.glob(f"{OUT}/*.output.json"):
        try:
            o = json.load(open(f))
        except Exception:
            continue
        m = o.get("metadata", {})
        if m.get("run_id") != run_id:
            continue
        qid = str(m.get("narrative_id"))
        steps = o.get("trace", {}).get("steps", [])
        n_search = n_zero = 0
        uniq, commit = set(), set()
        ev, ands = [], []
        for s in steps:
            tn = s.get("tool_name")
            if tn == "search":
                n_search += 1
                res = (s.get("output") or {}).get("results") or []
                if not res:
                    n_zero += 1
                for r in res:
                    if r.get("docid"):
                        uniq.add(r["docid"])
                    if r.get("returned_chars"):
                        ev.append(r["returned_chars"])
                ands.append(and_arity((s.get("arguments") or {}).get("query", "")))
            elif tn == "commit_context":
                for d in (s.get("context") or {}).get("staged", []):
                    commit.add(d)
        rows[qid] = dict(
            search=n_search, zero=n_zero, uniqDoc=len(uniq), commit=len(commit),
            ev_chars=round(statistics.mean(ev)) if ev else 0,
            maxAND=max(ands) if ands else 0,
            status=o.get("trace", {}).get("status"),
        )
    return rows


def main():
    run_ids = sys.argv[1:] or ["cmp-ssr"]
    all_stats = {rid: stats_for(rid) for rid in run_ids}
    qids = sorted({q for r in all_stats.values() for q in r}, key=lambda x: (len(x), x))
    hdr = f"{'qid':<12}"
    for rid in run_ids:
        hdr += f" | {rid:>34}"
    print(hdr)
    print(f"{'':<12}" + (" | " + f"{'srch/zero/uniq/commit ev maxAND':>34}") * len(run_ids))
    agg = defaultdict(lambda: defaultdict(int))
    for q in qids:
        line = f"{q:<12}"
        for rid in run_ids:
            s = all_stats[rid].get(q)
            if s:
                line += f" | {s['search']:>2}/{s['zero']:>2}/{s['uniqDoc']:>3}/{s['commit']:>2} {s['ev_chars']:>5} {s['maxAND']:>2}"
                for k in ("search", "zero", "uniqDoc", "commit"):
                    agg[rid][k] += s[k]
                agg[rid]["_ev"] += s["ev_chars"]
                agg[rid]["_n"] += 1
            else:
                line += f" | {'(missing)':>34}"
        print(line)
    print("-" * len(hdr))
    tot = f"{'TOTAL/mean':<12}"
    for rid in run_ids:
        a = agg[rid]
        n = max(1, a["_n"])
        tot += f" | {a['search']:>2}/{a['zero']:>2}/{a['uniqDoc']:>3}/{a['commit']:>2} {round(a['_ev']/n):>5}  ~"
    print(tot)


if __name__ == "__main__":
    main()
