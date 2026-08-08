#!/usr/bin/env python3
"""Per-topic root-cause diagnosis of why facets_agent lost specific rubric
criteria to aus_agent on the 15topic-5728aff run. For each aus_agent-won
topic: feed gpt-5.6-sol the topic narrative, facets_agent's own step-1
facet/requirement enumeration (extracted from raw_messages), facets_agent's
final answer, and the list of criteria aus_agent won on -- ask it to
root-cause each loss into one of four stages (never decomposed / searched
but not committed / committed but dropped from answer / decomposed+committed
but under-specified) plus a one-line concrete facets_agent fix suggestion.
"""
from __future__ import annotations
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path("/Users/e103037/repos/trec-rag-26")
DIFFS = json.loads(Path("/private/tmp/claude-501/-Users-e103037-repos-trec-rag-26/"
                        "11f55252-b0e1-4b10-855a-99a893005e83/scratchpad/"
                        "criterion_diffs.json").read_text())
FACETS_RUN_ID = "facets-agent-15topic-5728aff"
OUT_DIR = ROOT / "evaluation-results/arena/aus_agent-vs-facets_agent-15topic-5728aff-rubric/loss-diagnosis"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_env() -> None:
    import os
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    if "OPENAI_API_KEY" not in os.environ and "AZURE_OPENAI_API_KEY" in os.environ:
        os.environ["OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_API_KEY"]


def client():
    import os
    from openai import OpenAI
    return OpenAI(base_url=os.environ["OPENAI_BASE_URL"],
                  api_key=os.environ["OPENAI_API_KEY"], timeout=180.0, max_retries=4)


def facets_output_for(qid: str) -> dict:
    import glob
    for p in glob.glob(str(ROOT / "data/outputs/facets_agent/*.output.json")):
        d = json.loads(Path(p).read_text())
        if (d.get("metadata", {}).get("run_id") == FACETS_RUN_ID
                and d["metadata"]["narrative_id"] == qid):
            traj = json.loads(Path(p.replace(".output.json", ".trajectory.json")).read_text())
            return {"output": d, "trajectory": traj}
    raise SystemExit(f"no facets_agent output for {qid}")


def extract_enumeration(traj: dict) -> str:
    for m in traj["raw_messages"]:
        if m.get("role") == "assistant" and isinstance(m.get("content"), list):
            for block in m["content"]:
                text = block.get("text", "")
                if "requirement" in text.lower()[:60] or "facet" in text.lower()[:60]:
                    return text
    return "(enumeration not found in first assistant message)"


SYSTEM_PROMPT = (
    "You are diagnosing why one RAG agent's (facets_agent) answer scored lower "
    "than a rival agent's (aus_agent) on specific rubric criteria for the same "
    "research request. You are given: the request, facets_agent's own step-1 "
    "requirement/facet enumeration (its plan), facets_agent's final answer, and "
    "the list of criteria aus_agent satisfied better. For EACH losing criterion, "
    "classify the root cause using ONLY these stage labels: "
    "'not_decomposed' (the requirement never appears in the facet list at all), "
    "'decomposed_not_covered' (it's in the facet list but the final answer never "
    "addresses it, at all or only vaguely), "
    "'covered_but_shallow' (the answer touches it but lacks the specific "
    "names/numbers/mechanisms the criterion wants), "
    "'other' (anything else, briefly say what). "
    "Return STRICT JSON only.")

USER_TMPL = """REQUEST:
{query}

FACETS_AGENT'S STEP-1 ENUMERATION:
{enumeration}

FACETS_AGENT'S FINAL ANSWER:
\"\"\"
{answer}
\"\"\"

CRITERIA AUS_AGENT SATISFIED BETTER (weight = importance):
{criteria}

Return STRICT JSON: {{"diagnoses": [{{"criterion_index": <int, 0-based index into \
the list above>, "stage": <one of the 4 labels>, "evidence": <one short sentence \
citing what's in/missing from the enumeration or answer>, "fix_suggestion": <one \
short concrete sentence: what should facets_agent's PROMPT or PROCESS do \
differently for this kind of miss>}}, ...]}} -- one entry per criterion, in order.
"""


def diagnose_one(api, model: str, qid: str, query: str, enumeration: str,
                 answer_text: str, criteria: list[dict]) -> dict:
    cache = OUT_DIR / f"{qid}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    criteria_str = "\n".join(
        f"  [{i}] (weight={c['weight']:+.1f}) {c['text']}" for i, c in enumerate(criteria))
    user = USER_TMPL.format(query=query, enumeration=enumeration,
                            answer=answer_text[:12000], criteria=criteria_str)
    try:
        resp = api.chat.completions.create(
            model=model, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user}])
        obj = json.loads(resp.choices[0].message.content)
        record = {"qid": qid, "status": "completed", "diagnoses": obj.get("diagnoses", []),
                  "criteria": criteria}
    except Exception as exc:  # noqa: BLE001
        record = {"qid": qid, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    cache.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return record


def main() -> int:
    load_env()
    model = sys.argv[1] if len(sys.argv) > 1 else "gpt-5.6-sol"

    from collections import defaultdict
    by_qid = defaultdict(list)
    for d in DIFFS:
        if d["winner"] == "aus":
            by_qid[d["qid"]].append(d)

    print(f"{len(by_qid)} topics with aus_agent-won criteria, judge={model}")
    api = client()
    jobs = []
    for qid, criteria in by_qid.items():
        fac = facets_output_for(qid)
        query = fac["output"]["metadata"]["narrative"]
        enumeration = extract_enumeration(fac["trajectory"])
        answer_text = "\n".join(s["text"] for s in fac["output"]["answer"])
        jobs.append((qid, query, enumeration, answer_text, criteria))

    done, lock = 0, threading.Lock()

    def work(job):
        nonlocal done
        qid, query, enumeration, answer_text, criteria = job
        record = diagnose_one(api, model, qid, query, enumeration, answer_text, criteria)
        with lock:
            done += 1
            print(f"  [{done}/{len(jobs)}] {qid} status={record['status']}", flush=True)
        return record

    with ThreadPoolExecutor(max_workers=6) as pool:
        for future in as_completed([pool.submit(work, j) for j in jobs]):
            future.result()

    print(f"\nwrote {len(jobs)} diagnosis files under {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
