#!/usr/bin/env python3
"""Free (no-LLM-cost) behavioral analysis of aus_agent vs facets_agent
trajectories over their shared 15 topics (run_id=aus-agent-15topic /
facets-agent-15topic). Extracts search-engine usage, query characteristics,
commit/release patterns, turn/token/time stats, and errors -- purely from
the trace already on disk, no API calls.
"""
from __future__ import annotations

import glob
import json
import statistics as st
from collections import Counter, defaultdict

ROOT = "/home/el7/E103037/repos/trec-rag-26"


def load_run(system_dir, run_id):
    rows = {}
    for f in sorted(glob.glob(f"{ROOT}/data/outputs/{system_dir}/*.output.json")):
        obj = json.load(open(f))
        md = obj.get("metadata", {})
        if md.get("run_id") != run_id:
            continue
        qid = md["narrative_id"]
        rows[qid] = obj
    return rows


def search_calls(obj):
    calls = []
    for step in obj["trace"]["steps"]:
        if step["type"] != "tool_call" or step.get("tool_name") != "search":
            continue
        calls.append(step)
    return calls


def commit_calls(obj):
    return [s for s in obj["trace"]["steps"]
           if s["type"] == "tool_call" and s.get("tool_name") == "commit_context"]


def get_doc_calls(obj):
    return [s for s in obj["trace"]["steps"]
           if s["type"] == "tool_call" and s.get("tool_name") == "get_documents"]


def analyze_system(rows, label):
    print(f"\n{'='*80}\n{label} (n={len(rows)} topics)\n{'='*80}")
    engine_counts = Counter()
    engine_k = defaultdict(list)
    engine_query_words = defaultdict(list)
    n_searches, n_commits, n_release, n_getdocs = [], [], [], []
    n_committed_docs, n_rejected_docs = [], []
    turns, durations_s, processed_tokens = [], [], []
    failed_calls = 0
    release_events = []

    for qid, obj in rows.items():
        trace = obj["trace"]
        searches = search_calls(obj)
        commits = commit_calls(obj)
        getdocs = get_doc_calls(obj)
        n_searches.append(len(searches))
        n_commits.append(len(commits))
        n_getdocs.append(len(getdocs))

        for s in searches:
            args = s.get("arguments", {}) or {}
            eng = args.get("search_engine", "?")
            engine_counts[eng] += 1
            k = args.get("k")
            if isinstance(k, (int, float)):
                engine_k[eng].append(k)
            q = str(args.get("query", ""))
            engine_query_words[eng].append(len(q.split()))
            out = s.get("output")
            if isinstance(out, str) and '"error"' in out[:50]:
                failed_calls += 1

        committed_this_run = 0
        rejected_this_run = 0
        release_this_run = 0
        for c in commits:
            args = c.get("arguments", {}) or {}
            docs = args.get("documents") or []
            committed_this_run += len(docs)
            rel = args.get("release") or []
            if rel:
                release_this_run += len(rel)
                release_events.append((qid, rel))
            ctx = c.get("context") or {}
            rejected_this_run += len(ctx.get("rejected") or [])
        n_committed_docs.append(committed_this_run)
        n_rejected_docs.append(rejected_this_run)
        n_release.append(release_this_run)

        # turn count = max turn index across generation steps + 1
        gen_turns = [s.get("turn") for s in trace["steps"] if s["type"] == "generation"]
        gen_turns = [t for t in gen_turns if isinstance(t, int)]
        turns.append((max(gen_turns) + 1) if gen_turns else 0)
        durations_s.append((trace.get("duration_ms") or 0) / 1000)
        processed_tokens.append(
            trace.get("summary", {}).get("tokens", {}).get("processed", 0))

    def stats(xs):
        xs = [x for x in xs if x is not None]
        if not xs:
            return "n/a"
        return f"mean={st.mean(xs):.1f} min={min(xs)} max={max(xs)} total={sum(xs)}"

    print(f"searches/topic:        {stats(n_searches)}")
    print(f"commit_context/topic:  {stats(n_commits)}")
    print(f"get_documents/topic:   {stats(n_getdocs)}")
    print(f"committed docs/topic:  {stats(n_committed_docs)}")
    print(f"rejected docs/topic:   {stats(n_rejected_docs)}")
    print(f"release() uses/topic:  {stats(n_release)}  (total release events: {len(release_events)})")
    print(f"model turns/topic:     {stats(turns)}")
    print(f"wall-clock s/topic:    {stats(durations_s)}")
    print(f"processed tokens/topic:{stats(processed_tokens)}")
    print(f"failed search calls:   {failed_calls}")
    print(f"\nengine usage counts:   {dict(engine_counts)}")
    for eng, ks in engine_k.items():
        print(f"  {eng:10s} k: mean={st.mean(ks):.1f} min={min(ks)} max={max(ks)}  "
             f"query_words: mean={st.mean(engine_query_words[eng]):.1f} "
             f"min={min(engine_query_words[eng])} max={max(engine_query_words[eng])}")

    if release_events:
        print("\nrelease() events:")
        for qid, rel in release_events:
            for r in rel:
                print(f"  [{qid[-6:]}] released {r.get('id','?')}: {r.get('reason','')[:100]}")

    return {
        "n_searches": n_searches, "n_commits": n_commits, "n_getdocs": n_getdocs,
        "n_committed_docs": n_committed_docs, "n_rejected_docs": n_rejected_docs,
        "n_release": n_release, "turns": turns, "durations_s": durations_s,
        "processed_tokens": processed_tokens, "engine_counts": dict(engine_counts),
    }


aus = load_run("aus_agent", "aus-agent-15topic")
fac = load_run("facets_agent", "facets-agent-15topic")
print(f"aus_agent topics: {len(aus)}, facets_agent topics: {len(fac)}, "
     f"shared: {len(set(aus) & set(fac))}")

aus_stats = analyze_system(aus, "aus_agent")
fac_stats = analyze_system(fac, "facets_agent")

# Look at facets_agent's reasoning text for evidence of actual facet
# decomposition (the prompt asks for it, nothing enforces it programmatically).
print(f"\n{'='*80}\nfacets_agent: does reasoning actually mention decomposing into facets?\n{'='*80}")
facet_mentions = 0
for qid, obj in fac.items():
    reasoning_text = " ".join(
        r for s in obj["trace"]["steps"] if s["type"] == "generation"
        for r in (s.get("output", {}).get("reasoning") or []))
    mentions = reasoning_text.lower().count("facet")
    if mentions > 0:
        facet_mentions += 1
    print(f"  [{qid[-6:]}] 'facet' mentioned {mentions}x in reasoning "
         f"({len(reasoning_text)} chars total)")
print(f"topics with >=1 'facet' mention in reasoning: {facet_mentions}/{len(fac)}")
