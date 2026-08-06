#!/usr/bin/env python3
"""Compare Phase-2 smoke topics against Phase-1 smoke and v1 baseline:
search count, requirement/coverage compliance, and specific named gaps."""
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


def commits(obj):
    return [s for s in obj["trace"]["steps"]
           if s["type"] == "tool_call" and s.get("tool_name") == "commit_context"]


def main():
    v1 = load("facets-agent-15topic")
    p1 = load("facets-agent-phase1-smoke")
    p2 = load("facets-agent-phase2-smoke")
    print(f"phase2-smoke topics found: {len(p2)} / {len(TARGETS)} expected\n")
    for qid, (short, watch_for) in TARGETS.items():
        if qid not in p2:
            print(f"  [{short}] NOT YET PRESENT")
            continue
        v1_obj, p1_obj, p2_obj = v1.get(qid), p1.get(qid), p2[qid]
        v1_n = len(searches(v1_obj)) if v1_obj else None
        p1_n = len(searches(p1_obj)) if p1_obj else None
        p2_n = len(searches(p2_obj))
        v1_refs = len(v1_obj["references"]) if v1_obj else None
        p1_refs = len(p1_obj["references"]) if p1_obj else None
        p2_refs = len(p2_obj["references"])
        status = p2_obj["trace"]["status"]
        print(f"[{short}] watch for: {watch_for}")
        print(f"  status={status}  searches: v1={v1_n} -> p1={p1_n} -> p2={p2_n}  "
             f"refs: v1={v1_refs} -> p1={p1_refs} -> p2={p2_refs}")

        # requirement/coverage compliance
        s_calls = searches(p2_obj)
        n_with_req = sum(1 for s in s_calls if s["arguments"].get("requirement"))
        c_calls = commits(p2_obj)
        n_with_cov = sum(1 for c in c_calls if c["arguments"].get("coverage"))
        n_with_ready = sum(1 for c in c_calls if "ready_to_report" in c["arguments"])
        print(f"  compliance: {n_with_req}/{len(s_calls)} searches carry `requirement`; "
             f"{n_with_cov}/{len(c_calls)} commits carry `coverage`; "
             f"{n_with_ready}/{len(c_calls)} carry `ready_to_report`")

        # final coverage ledger (last commit call)
        if c_calls:
            last_cov = c_calls[-1]["arguments"].get("coverage", [])
            statuses = [e.get("status") for e in last_cov]
            print(f"  final ledger ({len(last_cov)} entries): "
                 f"covered={statuses.count('covered')} open={statuses.count('open')} "
                 f"unavailable={statuses.count('unavailable')}")
            for e in last_cov:
                print(f"    [{e.get('status'):11s}] {e.get('requirement','')[:90]}")
        print(f"  queries fired in p2:")
        for s in s_calls:
            a = s["arguments"]
            req = a.get("requirement", "<MISSING>")[:50]
            print(f"    [{a['search_engine']:8s}] req={req!r:55s} q={a['query'][:70]}")
        print()


if __name__ == "__main__":
    main()
