"""Additive semantic-only backfill (dense server was 502-down during the full
30-topic run; SSR is now DOWN so we must NOT re-fetch any other engine).

For the given qids, this re-runs ONLY the `semantic` sub-queries already in
out/subqueries.json (reused, not regenerated), k=10 with text, and MERGES the
results into the existing pool/provenance/retrieved_raw:

  - out/pool.json          : add any NEW docids (never overwrite existing text).
  - out/provenance.json    : REPLACE that topic's `semantic` provenance entries
                             (drop stale/empty semantic provenance for the qid,
                             then append the fresh ones); keyword/ssr/lucene
                             provenance entries are left byte-for-byte intact.
  - out/retrieved_raw.json : REPLACE that topic's `semantic` per-sub-need lists;
                             keyword/ssr/lucene lists untouched.

It refuses to touch any topic whose semantic is already complete (all 6
sub-needs returned hits with no 502), unless --force is given — so a stray run
cannot clobber good data. It NEVER calls any engine other than semantic.

Usage:
    PYTHONPATH=src uv run --group aus-agent python .../backfill_semantic.py \
        --qids <qid> [<qid> ...]        # explicit list (recommended)
    ... backfill_semantic.py --auto     # auto-pick topics where semantic
                                        # has a 502/empty sub-need
"""
from __future__ import annotations

import argparse
import json

import common as C
from utils.search_dense import search_dense  # noqa: E402  (semantic ONLY)

K = 10
ENGINE = "semantic"


def semantic_broken(raw_topic) -> bool:
    """True if this topic's semantic arm has any sub-need that errored or came
    back empty (the 502-down symptom). A fully-healthy arm has every sub-need
    returning hits with error=None."""
    sem = raw_topic.get(ENGINE, [])
    if not sem:
        return True
    return any(e.get("error") or not e.get("hits") for e in sem)


def fetch_semantic(subneeds) -> list[dict]:
    """Return per-sub-need lists mirroring retrieve.py's raw[engine] shape,
    fetching ONLY the semantic engine (full text)."""
    out = []
    for si, sn in enumerate(subneeds):
        q = (sn["queries"].get(ENGINE) or "").strip()
        entry = {"subneed_idx": si, "query": q, "hits": [], "error": None,
                 "docs": []}
        if not q:
            entry["error"] = "empty query"
            out.append(entry)
            continue
        try:
            hits = search_dense(q, K, with_text=True)
        except Exception as e:  # keep it recorded, do not abort the topic
            entry["error"] = f"{type(e).__name__}: {e}"
            out.append(entry)
            continue
        for h in hits:
            docid = h["docid"]
            entry["hits"].append(docid)
            entry["docs"].append({
                "docid": docid, "text": h.get("text") or "",
                "rank": h["rank"], "score": round(float(h["score"]), 6),
            })
        out.append(entry)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", nargs="*", default=None)
    ap.add_argument("--auto", action="store_true",
                    help="auto-select topics with a broken semantic arm")
    ap.add_argument("--force", action="store_true",
                    help="backfill even topics whose semantic looks complete")
    args = ap.parse_args()

    subq = C.load_json(C.OUT / "subqueries.json")
    pool = C.load_json(C.OUT / "pool.json")
    prov = C.load_json(C.OUT / "provenance.json")
    raw = C.load_json(C.OUT / "retrieved_raw.json")

    if args.auto:
        targets = [q for q in subq if semantic_broken(raw.get(q, {}))]
    else:
        targets = C.filter_qids(subq.keys(), args.qids)
    if not targets:
        print("no target topics; nothing to do.")
        return

    print(f"backfill semantic for {len(targets)} topics (SSR/keyword/lucene NOT "
          f"touched): {', '.join(targets)}\n")

    total_new = 0
    for qid in targets:
        if not args.force and not semantic_broken(raw.get(qid, {})):
            print(f"SKIP {qid}: semantic already complete (use --force to override)")
            continue

        old_sem = len({d for d, pl in prov.get(qid, {}).items()
                       for p in pl if p["engine"] == ENGINE})
        fetched = fetch_semantic(subq[qid])
        n_err = sum(1 for e in fetched if e["error"])

        # 1) MERGE docs into pool (add new; never overwrite existing text).
        pool.setdefault(qid, {})
        new_docs = 0
        for entry in fetched:
            for d in entry["docs"]:
                docid, text = d["docid"], d["text"]
                if docid not in pool[qid]:
                    pool[qid][docid] = {"text": text}
                    new_docs += 1
                elif not pool[qid][docid]["text"] and text:
                    pool[qid][docid]["text"] = text

        # 2) provenance: drop this topic's OLD semantic entries, append fresh.
        #    keyword/ssr/lucene entries are preserved exactly.
        topic_prov = prov.setdefault(qid, {})
        for docid in list(topic_prov):
            kept = [p for p in topic_prov[docid] if p["engine"] != ENGINE]
            if kept:
                topic_prov[docid] = kept
            else:
                del topic_prov[docid]  # doc was semantic-only & stale (unlikely)
        for entry in fetched:
            for d in entry["docs"]:
                topic_prov.setdefault(d["docid"], []).append({
                    "engine": ENGINE, "subneed_idx": entry["subneed_idx"],
                    "rank": d["rank"], "score": d["score"],
                })

        # 3) retrieved_raw: replace ONLY the semantic per-sub-need lists (strip
        #    the transient `docs` field to match the original raw schema).
        raw.setdefault(qid, {})[ENGINE] = [
            {"subneed_idx": e["subneed_idx"], "query": e["query"],
             "hits": e["hits"], "error": e["error"]}
            for e in fetched
        ]

        new_sem = len({d for d, pl in topic_prov.items()
                       for p in pl if p["engine"] == ENGINE})
        total_new += new_docs
        print(f"{qid}: semantic {old_sem} -> {new_sem} unique "
              f"(+{new_docs} new pool docs, {n_err} sub-need errors)")

    C.dump_json(pool, C.OUT / "pool.json")
    C.dump_json(prov, C.OUT / "provenance.json")
    C.dump_json(raw, C.OUT / "retrieved_raw.json")
    print(f"\nmerged. {total_new} new pool docs total.")
    print(f"wrote {C.OUT/'pool.json'}, provenance.json, retrieved_raw.json")


if __name__ == "__main__":
    main()
