#!/usr/bin/env python3
"""Compare Phase-1 smoke-test topics against the v1 (facets-agent-15topic)
baseline: search count, engine mix, and a read of the reasoning text for
whether the plan's named target requirements now get searched.
"""
import glob
import json

ROOT = "/home/el7/E103037/repos/trec-rag-26"

TARGETS = {
    "6847465956a0f6376a6054a7": ("6054a7", "Ontario eligibility / political feasibility / UBI definition"),
    "6847465956a0f6376a605476": ("605476", "shared US-Soviet enemy / internal British opposition"),
    "684397d188c1deceb49af325": ("9af325", "book-by-book structure"),
    "6847465956a0f6376a605391": ("605391", "named partners: Indomaret, GrabFood, etc."),
}


def load(run_id):
    rows = {}
    for f in glob.glob(f"{ROOT}/data/outputs/facets_agent/*.output.json"):
        obj = json.load(open(f))
        if obj["metadata"].get("run_id") != run_id:
            continue
        rows[obj["metadata"]["narrative_id"]] = obj
    return rows


def searches(obj):
    return [s for s in obj["trace"]["steps"]
           if s["type"] == "tool_call" and s.get("tool_name") == "search"]


def main():
    v1 = load("facets-agent-15topic")
    v2 = load("facets-agent-phase1-smoke")
    print(f"v2 (phase1-smoke) topics found: {len(v2)} / {len(TARGETS)} expected")
    for qid, (short, watch_for) in TARGETS.items():
        if qid not in v2:
            print(f"  [{short}] NOT YET PRESENT")
            continue
        v1_obj, v2_obj = v1.get(qid), v2[qid]
        v1_n = len(searches(v1_obj)) if v1_obj else None
        v2_n = len(searches(v2_obj))
        v1_words = sum(len(s["text"].split()) for s in v1_obj["answer"]) if v1_obj else None
        v2_words = sum(len(s["text"].split()) for s in v2_obj["answer"])
        v1_refs = len(v1_obj["references"]) if v1_obj else None
        v2_refs = len(v2_obj["references"])
        status = v2_obj["trace"]["status"]
        print(f"\n[{short}] watch for: {watch_for}")
        print(f"  status={status}  searches: v1={v1_n} -> v2={v2_n}  "
             f"words: v1={v1_words} -> v2={v2_words}  refs: v1={v1_refs} -> v2={v2_refs}")
        print(f"  queries fired in v2:")
        for s in searches(v2_obj):
            a = s["arguments"]
            print(f"    [{a['search_engine']:8s}] {a['query'][:100]}")


if __name__ == "__main__":
    main()
