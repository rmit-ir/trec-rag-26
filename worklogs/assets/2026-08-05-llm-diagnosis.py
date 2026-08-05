#!/usr/bin/env python3
"""Budgeted LLM-assisted diagnosis of facets_agent vs aus_agent, per topic.

One gpt-5.6-luna call per topic (15 total): given the request, both systems'
final answers, the specific rubric criteria where the per-criterion scorer
already found a difference (reusing the cached scoring, no re-judging), and
facets_agent's own search-query log, ask for a structured diagnosis of
facets_agent's SPECIFIC weakness (if any) on this topic and a concrete
improvement suggestion. Tracks token usage/cost to stay well under budget.
"""
from __future__ import annotations

import glob
import json
import os
import re

ROOT = "/home/el7/E103037/repos/trec-rag-26"
OUT_DIR = f"{ROOT}/evaluation-results/arena/aus_agent-vs-facets_agent-15topic-rubric"
DIAG_DIR = "/tmp/claude-200103037/-home-el7-E103037-repos-trec-rag-26/6eb02a90-5386-45ae-a290-a6bd7b4f00df/scratchpad/diagnosis-cache"
os.makedirs(DIAG_DIR, exist_ok=True)

# gpt-5.6-luna Azure pricing is not in the repo's rate table (Azure-hosted,
# no committed rate); use a deliberately PESSIMISTIC placeholder so the
# running total stays a conservative (over-)estimate against the $20 cap.
EST_RATE_IN_PER_1M = 3.0
EST_RATE_OUT_PER_1M = 12.0


def load_env():
    for raw in open(f"{ROOT}/.env", encoding="utf-8").read().splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    if "OPENAI_API_KEY" not in os.environ and "AZURE_OPENAI_API_KEY" in os.environ:
        os.environ["OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_API_KEY"]


def client():
    from openai import OpenAI
    return OpenAI(base_url=os.environ["OPENAI_BASE_URL"],
                  api_key=os.environ["OPENAI_API_KEY"], timeout=180.0, max_retries=4)


def load_outputs(system_dir, run_id):
    rows = {}
    for f in sorted(glob.glob(f"{ROOT}/data/outputs/{system_dir}/*.output.json")):
        obj = json.load(open(f))
        if obj["metadata"].get("run_id") != run_id:
            continue
        rows[obj["metadata"]["narrative_id"]] = obj
    return rows


def answer_text(obj):
    return "\n".join(s["text"] for s in obj["answer"])


def search_log(obj):
    lines = []
    for s in obj["trace"]["steps"]:
        if s["type"] != "tool_call" or s.get("tool_name") != "search":
            continue
        a = s["arguments"]
        lines.append(f"[{a['search_engine']}] {a['query']}")
    return lines


def load_criteria(path):
    out = {}
    for line in open(path, encoding="utf-8").read().splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        out[row["qid"]] = [
            {"cid": i, "text": c["criterion"], "weight": c["weight"], "axis": c["axis"]}
            for i, c in enumerate(row.get("rubrics", []))]
    return out


def differing_criteria(qid, criteria):
    aus = json.load(open(f"{OUT_DIR}/criterion-scores/aus_agent__{qid}.json"))
    fac = json.load(open(f"{OUT_DIR}/criterion-scores/facets_agent__{qid}.json"))
    aus_g = {c["cid"]: c["grade"] for c in aus["criteria_coverage"]}
    fac_g = {c["cid"]: c["grade"] for c in fac["criteria_coverage"]}
    rows = []
    for c in criteria:
        a, f = aus_g.get(c["cid"]), fac_g.get(c["cid"])
        if a is None or f is None or a == f:
            continue
        w = c["weight"]
        better = "aus_agent" if ((a > f) if w >= 0 else (a < f)) else "facets_agent"
        rows.append({"axis": c["axis"], "weight": w, "text": c["text"],
                    "aus_agent_grade": a, "facets_agent_grade": f, "better": better})
    return rows, aus["overall"], fac["overall"]


SYSTEM = (
    "You are analyzing an agentic RAG system's behavior to help its "
    "developers improve it. You will see a research request, two systems' "
    "final answers to it (aus_agent: a long, heavily-tuned prompt; "
    "facets_agent: a short, minimal prompt asking the model to decompose "
    "into facets, search each across semantic/keyword/hybrid engines, "
    "curate evidence, and self-check citations), the specific rubric "
    "criteria an independent judge found they differ on, and facets_agent's "
    "own search query log. Diagnose SPECIFICALLY what facets_agent did "
    "well or poorly on THIS topic, tied to concrete evidence -- not a "
    "generic restatement of the rubric gaps. Return STRICT JSON only.")

USER_TMPL = """RESEARCH REQUEST:
{query}

FACETS_AGENT'S SEARCH QUERY LOG ({n_searches} calls):
{search_log}

FACETS_AGENT'S FINAL ANSWER:
\"\"\"
{facets_answer}
\"\"\"

AUS_AGENT'S FINAL ANSWER:
\"\"\"
{aus_answer}
\"\"\"

RUBRIC CRITERIA WHERE AN INDEPENDENT JUDGE FOUND THE TWO ANSWERS DIFFER \
(overall grades 0-3: aus_agent={aus_overall}, facets_agent={facets_overall}):
{criteria_block}

Return STRICT JSON:
{{
  "weakness_category": "<one of: search_coverage_gap, search_redundancy_low_yield, \
synthesis_organization, citation_precision, over_verbose_or_padding, \
under_specified_or_thin, instruction_compliance, none_facets_agent_fine>",
  "evidence": "<1-3 sentences citing SPECIFIC content from the search log or \
answers above, not a generic statement>",
  "improvement_suggestion": "<1-2 sentences: a concrete prompt/tool/process \
change for facets_agent that would address this on future topics like this one>"
}}
"""


def diagnose(api, model, qid, query, facets_obj, aus_obj, criteria_rows,
            aus_overall, facets_overall):
    cache_path = f"{DIAG_DIR}/{qid}.json"
    if os.path.exists(cache_path):
        return json.load(open(cache_path)), None
    sq = search_log(facets_obj)
    criteria_block = "\n".join(
        f"- [{r['axis']}, w={r['weight']:+.1f}] {r['text']} "
        f"(aus_agent={r['aus_agent_grade']}, facets_agent={r['facets_agent_grade']}, "
        f"favors {r['better']})"
        for r in criteria_rows) or "(no differing criteria found)"
    user = USER_TMPL.format(
        query=query, n_searches=len(sq), search_log="\n".join(sq),
        facets_answer=answer_text(facets_obj)[:6000],
        aus_answer=answer_text(aus_obj)[:6000],
        aus_overall=aus_overall, facets_overall=facets_overall,
        criteria_block=criteria_block)
    resp = api.chat.completions.create(
        model=model, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": user}])
    usage = resp.usage
    result = json.loads(resp.choices[0].message.content)
    result["_qid"] = qid
    json.dump(result, open(cache_path, "w"), indent=2)
    return result, (usage.prompt_tokens, usage.completion_tokens)


def main():
    load_env()
    aus = load_outputs("aus_agent", "aus-agent-15topic")
    fac = load_outputs("facets_agent", "facets-agent-15topic")
    criteria_by_qid = load_criteria(
        f"{ROOT}/data/official/trec-rag-2026-data/trec-rag-2026/development-data/"
        "researchrubrics-dev-rubrics/research-rubrics-dev-rubrics.jsonl")
    qids = sorted(set(aus) & set(fac))

    api = client()
    total_in = total_out = 0
    results = []
    for qid in qids:
        rows, aus_ov, fac_ov = differing_criteria(qid, criteria_by_qid[qid])
        query = aus[qid]["metadata"]["narrative"]
        result, usage = diagnose(api, "gpt-5.6-luna", qid, query, fac[qid], aus[qid],
                                 rows, aus_ov, fac_ov)
        if usage:
            total_in += usage[0]
            total_out += usage[1]
        est_cost = (total_in / 1e6 * EST_RATE_IN_PER_1M
                   + total_out / 1e6 * EST_RATE_OUT_PER_1M)
        print(f"[{qid[-6:]}] {result.get('weakness_category')} "
             f"(running est. cost so far: ${est_cost:.4f}, "
             f"tokens in={total_in} out={total_out})")
        results.append(result)

    print(f"\nTOTAL estimated cost: ${(total_in/1e6*EST_RATE_IN_PER_1M + total_out/1e6*EST_RATE_OUT_PER_1M):.4f}")
    print(f"total tokens: in={total_in} out={total_out}")
    json.dump(results, open(f"{DIAG_DIR}/_all.json", "w"), indent=2)
    print(f"wrote {DIAG_DIR}/_all.json")


if __name__ == "__main__":
    main()
