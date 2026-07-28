"""Stage 3 — run every (qid, subneed, engine) query and pool the results.

For each topic, for each sub-need, for each engine, call the engine at k=10 WITH
TEXT (max_chars=None -> full text). Pool per topic into UNIQUE (qid, docid) docs
(dedup across engines/sub-needs — relevance is judged once per doc), keeping the
FULL text (first non-empty text seen). Provenance records, for each pooled doc,
every (engine, subneed_idx, rank) that surfaced it — this is what score.py uses
to attribute coverage/precision/nDCG back to each engine.

Outputs:
  out/pool.json        {qid: {docid: {text}}}          (unique docs + text)
  out/provenance.json  {qid: {docid: [{engine, subneed_idx, rank, score}]}}
  Also out/retrieved_raw.json {qid: {engine: [{subneed_idx, query, hits:[docid...]}]}}
    — the per-sub-need ranked lists, needed for per-sub-need nDCG in score.py.

Usage:
    PYTHONPATH=src uv run --group aus-agent python .../retrieve.py [--qids ...]
"""
from __future__ import annotations

import argparse
import json

import common as C
from tools.search_tool import run_search_tool  # noqa: E402

K = 10


def retrieve_topic(qid, subneeds):
    pool: dict[str, dict] = {}          # docid -> {text}
    prov: dict[str, list] = {}          # docid -> [{engine, subneed_idx, rank, score}]
    raw: dict[str, list] = {e: [] for e in C.ENGINES}  # engine -> per-subneed lists

    for si, sn in enumerate(subneeds):
        for eng in C.ENGINES:
            q = sn["queries"].get(eng, "")
            entry = {"subneed_idx": si, "query": q, "hits": [], "error": None}
            if not q:
                entry["error"] = "empty query"
                raw[eng].append(entry)
                continue
            out = json.loads(run_search_tool(q, k=K, max_chars=None,
                                             search_engine=eng))
            if out.get("error"):
                entry["error"] = out["error"]
                raw[eng].append(entry)
                continue
            for r in out.get("results", []):
                docid = r["docid"]
                text = r.get("text") or ""
                entry["hits"].append(docid)
                # pool (keep first non-empty text)
                if docid not in pool:
                    pool[docid] = {"text": text}
                elif not pool[docid]["text"] and text:
                    pool[docid]["text"] = text
                prov.setdefault(docid, []).append({
                    "engine": eng, "subneed_idx": si,
                    "rank": r["rank"], "score": r["score"],
                })
            raw[eng].append(entry)
    return pool, prov, raw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", nargs="*", default=None)
    args = ap.parse_args()

    subq = C.load_json(C.OUT / "subqueries.json")
    wanted = C.filter_qids(subq.keys(), args.qids)

    all_pool, all_prov, all_raw = {}, {}, {}
    for qid in wanted:
        print(f"retrieve: {qid} ({len(subq[qid])} sub-needs x {len(C.ENGINES)} engines) ...",
              flush=True)
        pool, prov, raw = retrieve_topic(qid, subq[qid])
        all_pool[qid] = pool
        all_prov[qid] = prov
        all_raw[qid] = raw
        n_err = sum(1 for e in C.ENGINES for x in raw[e] if x["error"])
        print(f"  {len(pool)} unique docs pooled; {n_err} query errors")
        for eng in C.ENGINES:
            n_hits = sum(len(x["hits"]) for x in raw[eng])
            n_uniq = len({d for x in raw[eng] for d in x["hits"]})
            print(f"    {eng:<12} {n_hits:>3} hits / {n_uniq:>3} unique")

    C.dump_json(all_pool, C.OUT / "pool.json")
    C.dump_json(all_prov, C.OUT / "provenance.json")
    C.dump_json(all_raw, C.OUT / "retrieved_raw.json")
    print(f"\nwrote {C.OUT / 'pool.json'}, provenance.json, retrieved_raw.json")


if __name__ == "__main__":
    main()
