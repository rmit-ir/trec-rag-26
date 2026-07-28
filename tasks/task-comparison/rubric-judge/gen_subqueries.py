"""Stage 2 — per-topic sub-query generation (ONE luna call per topic).

For each topic, given the narrative + the info criteria, luna produces 3-6
engine-agnostic SUB-NEEDS that together cover the criteria, and for each
sub-need FOUR engine queries {semantic, keyword, ssr, lucene_bool} — the same
information need expressed in four query languages. The per-engine query-writing
guidance is lifted verbatim from src/tools/search_tool.py (the _NL/_GCL/_LUCENE
guidance + ENGINE_INFO blurbs) so the translations are competent and, crucially,
FAIR across engines (each engine gets its native idiom).

Design note (fixed by the task): the retrieval unit is MULTI SUB-QUERY per
engine — the pool for an engine is the union of its per-sub-need result lists,
NOT a single query and NOT the full agent trajectory.

Output out/subqueries.json:
    {qid: [{subneed, queries:{semantic,keyword,ssr,lucene_bool}}]}

Usage:
    PYTHONPATH=src uv run --group aus-agent python .../gen_subqueries.py [--qids ...]
"""
from __future__ import annotations

import argparse

import common as C

# Query-language guidance, imported from the real tool so it never drifts.
from tools.search_tool import (  # noqa: E402
    ENGINE_INFO,
    _GCL_GUIDANCE,
    _LUCENE_GUIDANCE,
    _NL_GUIDANCE,
)

SYSTEM = (
    "You are a retrieval query planner for the ClimbMix web corpus. You are "
    "given a research topic and its INFORMATION requirements (rubric criteria "
    "that a good answer's evidence must cover). Your job is to decompose the "
    "topic into a small set of focused SUB-NEEDS whose retrieved evidence, "
    "taken together, would cover the information requirements, then translate "
    "EACH sub-need into four search queries — one per engine — using each "
    "engine's native query language. Translate the SAME information need into "
    "all four languages; do not make one engine's query broader or narrower "
    "than another's. Return STRICT JSON only."
)

USER_TMPL = """TOPIC NARRATIVE:
{narrative}

INFORMATION REQUIREMENTS (each answer's evidence should cover these; cid = stable id):
{criteria}

ENGINE DESCRIPTIONS (when each is strong):
- semantic: {b_semantic}
- keyword: {b_keyword}
- ssr: {b_ssr}
- lucene_bool: {b_lucene_bool}

QUERY-LANGUAGE GUIDANCE (write each engine's query in ITS language):
[semantic & keyword — natural language / bag of distinctive terms]
{nl}

[ssr — GCL Boolean]
{gcl}

[lucene_bool — Lucene query-parser syntax]
{lucene}

TASK:
1. Produce 3 to 6 engine-agnostic SUB-NEEDS. Each sub-need is one focused,
   single-facet information need (a short phrase describing what to find).
   Together the sub-needs should span the information requirements above; aim
   to touch every high-weight criterion via at least one sub-need.
2. For EACH sub-need, write four queries — one per engine — expressing that
   same need in each engine's language per the guidance. Keep them fair: same
   scope, just different syntax. For ssr use GCL Boolean (e.g.
   (^ anchor (+ a b))); for lucene_bool use Lucene syntax (e.g.
   +"a b" +context); for semantic a natural phrase/question; for keyword bare
   distinctive terms.

Return STRICT JSON with this exact shape:
{{"subneeds": [
  {{"subneed": "<short description>",
    "queries": {{"semantic": "...", "keyword": "...", "ssr": "...", "lucene_bool": "..."}}}},
  ...
]}}
"""


def fmt_criteria(criteria) -> str:
    return "\n".join(
        f"  [cid {c['cid']}] (w={c['weight']}, {c['axis']}) {c['text']}"
        for c in criteria
    )


def gen_for_topic(client, topic) -> list[dict]:
    user = USER_TMPL.format(
        narrative=topic["narrative"],
        criteria=fmt_criteria(topic["criteria"]),
        b_semantic=ENGINE_INFO["semantic"]["blurb"],
        b_keyword=ENGINE_INFO["keyword"]["blurb"],
        b_ssr=ENGINE_INFO["ssr"]["blurb"],
        b_lucene_bool=ENGINE_INFO["lucene_bool"]["blurb"],
        nl=_NL_GUIDANCE,
        gcl=_GCL_GUIDANCE,
        lucene=_LUCENE_GUIDANCE,
    )
    obj = C.luna_json(client, SYSTEM, user)
    subneeds = obj.get("subneeds", [])
    # Normalize: ensure each has all four engine keys (empty string if missing).
    clean = []
    for sn in subneeds:
        q = sn.get("queries", {}) or {}
        clean.append({
            "subneed": sn.get("subneed", ""),
            "queries": {e: (q.get(e) or "").strip() for e in C.ENGINES},
        })
    return clean


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", nargs="*", default=None)
    args = ap.parse_args()

    rubrics_info = C.load_json(C.OUT / "rubrics_info.json")
    wanted = C.filter_qids(rubrics_info.keys(), args.qids)
    client = C.luna_client()

    out: dict[str, list] = {}
    for qid in wanted:
        print(f"gen sub-queries: {qid} ...", flush=True)
        subneeds = gen_for_topic(client, rubrics_info[qid])
        out[qid] = subneeds
        print(f"  {len(subneeds)} sub-needs")
        for i, sn in enumerate(subneeds):
            print(f"    [{i}] {sn['subneed']}")

    C.dump_json(out, C.OUT / "subqueries.json")
    print(f"\nwrote {C.OUT / 'subqueries.json'}")


if __name__ == "__main__":
    main()
