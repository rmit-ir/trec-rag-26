"""Judge the prompt-A/B runs (promptab-default vs promptab-firsthand).

For each committed doc: ONE luna call → {umbrela 0-3, coverage:[{cid,grade}],
source_type} where source_type grades how first-hand the doc is (2=primary/
first-hand original, 1=mixed, 0=secondary/derivative). This directly tests
whether the 'firsthand' prompt shifted committed docs toward primary sources.
For each answer (arm,topic): rubric coverage + overall (reuses judge_answers'
shape). Both cached + resumable in dedicated dirs (NOT the main study's cache,
since the schema adds source_type).

Run: PYTHONPATH=src uv run --group aus-agent python \
       tasks/task-comparison/rubric-judge/ab_judge.py [--workers N]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import common as C
from utils.search_dense import auth_headers

DENSE = os.environ.get(
    "DENSE_SEARCH_URL", "https://index-climbmix-jina-v5-nano.dsync.net").rstrip("/")

RUN2ARM = {"promptab-default": "default", "promptab-firsthand": "firsthand"}
CJDIR = C.OUT / "ab_judgments"          # committed-doc judgments (w/ source_type)
AJDIR = C.OUT / "ab_answer_judgments"   # answer judgments
DIV = C.ROOT / "data/task-comparison/diversity"
DOC_CHARS = 6000

# ---- text for a committed id ----
# The agent commits PARENT docids (whole-doc, no _p suffix) even though
# retrieval is chunk-level, so parent docids need whole-doc text (Pyserini);
# a chunk id (_pN), if ever committed, comes from the dense chunk docstore.
_CHUNK_ID = re.compile(r"_p\d+$")


def fetch_committed_text(did):
    if _CHUNK_ID.search(did):
        url = f"{DENSE}/doc/{urllib.parse.quote(did, safe='')}"
        # non-default UA: the endpoint's proxy 403s the stock "Python-urllib" UA.
        headers = {**auth_headers(), "User-Agent": "trec-rag-search/1.0"}
        with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=30) as r:
            return json.load(r).get("text")
    from utils.fetch_doc import fetch_doc
    return fetch_doc(did).get("text")


def build_committed_map():
    """{qid: {arm: [docid]}} from the two A/B run_ids' output.json references."""
    m = defaultdict(lambda: defaultdict(list))
    answers = {}  # (arm,qid)->answer_text
    for f in glob.glob(str(C.ROOT / "data/outputs/aus_agent/*.output.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        arm = RUN2ARM.get(d.get("metadata", {}).get("run_id"))
        if not arm:
            continue
        qid = d["metadata"]["narrative_id"]
        m[qid][arm] = d.get("references") or []
        ans = d.get("answer") or []
        answers[(arm, qid)] = "\n".join(s.get("text", "") for s in ans
                                        if isinstance(s, dict))
    return {q: dict(v) for q, v in m.items()}, answers


CSYS = (
    "You are a strict relevance + provenance judge for a research RAG system "
    "over the ClimbMix web corpus. Given a topic, its information requirements, "
    "and ONE retrieved document, output its holistic relevance, which criteria "
    "it supports, and how FIRST-HAND it is. Judge only on the document text. "
    "Return STRICT JSON only."
)
CTMPL = """TOPIC NARRATIVE:
{narrative}

INFORMATION REQUIREMENTS (cid = stable id):
{criteria}

RETRIEVED DOCUMENT (docid {docid}):
\"\"\"
{doc}
\"\"\"

Return STRICT JSON:
{{"umbrela": <0|1|2|3>, "coverage": [{{"cid": <int>, "grade": <1|2>}}, ...],
  "source_type": <0|1|2>}}
UMBRELA: 0 irrelevant, 1 on-topic-but-no-answer, 2 partial, 3 highly relevant.
COVERAGE: list ONLY criteria the doc gives textual evidence for (1 partial, 2 full).
SOURCE_TYPE — how first-hand/original the document is:
  2 = PRIMARY / first-hand: original research, official record, direct testimony,
      dataset, standard, the artefact or text itself, or the source that
      introduces/owns the fact, method, or argument.
  1 = MIXED: original reporting interleaved with substantial summary of others.
  0 = SECONDARY / derivative: summary, aggregation, listicle, or commentary that
      mainly restates work owned elsewhere.
"""


def fmt_criteria(crit):
    return "\n".join(f"  [cid {c['cid']}] (w={c['weight']}, {c['axis']}) {c['text']}"
                     for c in crit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    cmap, answers = build_committed_map()
    if not cmap:
        print("no promptab-* runs found yet — run run_prompt_ab.sh first.")
        return
    rinfo = C.load_json(C.OUT / "rubrics_info.json")
    text = {}
    CJDIR.mkdir(parents=True, exist_ok=True)
    AJDIR.mkdir(parents=True, exist_ok=True)
    client = C.luna_client()

    # ---- fetch text for every committed doc (parent docid → whole-doc; _pN → chunk) ----
    need = {d for qid, arms in cmap.items() for arm in arms for d in arms[arm]}
    print(f"fetching text for {len(need)} committed docs ...", flush=True)

    def grab(did):
        for _ in range(2):
            try:
                t = fetch_committed_text(did)
                if t:
                    return did, t
            except Exception:
                pass
        return did, None
    with ThreadPoolExecutor(max_workers=16) as ex:
        for did, t in ex.map(grab, need):
            if t:
                text[did] = t

    # ---- committed-doc judging (union of both arms; judge once per qid,docid) ----
    todo = []
    for qid, arms in cmap.items():
        crit = rinfo[qid]
        docs = {d for arm in arms for d in arms[arm]}
        for d in docs:
            if (CJDIR / f"{qid}__{d}.json").exists() or d not in text:
                continue
            todo.append((qid, d, text[d], crit))
    print(f"committed A/B judge: {len(todo)} to do", flush=True)

    def cworker(job):
        qid, d, txt, crit = job
        user = CTMPL.format(narrative=crit["narrative"],
                            criteria=fmt_criteria(crit["criteria"]),
                            docid=d, doc=(txt or "")[:DOC_CHARS])
        try:
            o = C.luna_json(client, CSYS, user)
            valid = {c["cid"] for c in crit["criteria"]}
            cov = [{"cid": int(x["cid"]), "grade": max(1, min(2, int(x["grade"])))}
                   for x in (o.get("coverage") or []) if int(x.get("cid", -1)) in valid]
            return qid, d, {"docid": d, "umbrela": max(0, min(3, int(o.get("umbrela", 0)))),
                            "coverage": cov,
                            "source_type": max(0, min(2, int(o.get("source_type", 0))))}
        except Exception as e:
            return qid, d, {"error": f"{type(e).__name__}: {e}"}

    done = err = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for fut in as_completed([ex.submit(cworker, j) for j in todo]):
            qid, d, res = fut.result()
            if "error" in res:
                err += 1; continue
            C.dump_json(res, CJDIR / f"{qid}__{d}.json"); done += 1
    print(f"committed judged: {done} ({err} errored)", flush=True)

    # ---- answer judging (per arm, per topic) ----
    atodo = [(arm, qid, txt, rinfo[qid]) for (arm, qid), txt in answers.items()
             if txt.strip() and not (AJDIR / f"{arm}__{qid}.json").exists()]
    print(f"answer A/B judge: {len(atodo)} to do", flush=True)
    ASYS = ("You are a strict evaluator. Grade how well a system's FINAL ANSWER "
            "satisfies each information requirement (0 none/1 partial/2 full) and "
            "give a holistic grade. Judge only the answer text; ignore length/"
            "format/citation-style. Return STRICT JSON only.")
    ATMPL = ("TOPIC NARRATIVE:\n{narrative}\n\nINFORMATION REQUIREMENTS:\n{criteria}"
             "\n\nSYSTEM FINAL ANSWER:\n\"\"\"\n{answer}\n\"\"\"\n\nReturn STRICT JSON:\n"
             '{{"criteria_coverage": [{{"cid": <int>, "grade": <0|1|2>}}, ...], '
             '"overall": <0|1|2|3>}}\n Include EVERY cid.')

    def aworker(job):
        arm, qid, txt, crit = job
        user = ATMPL.format(narrative=crit["narrative"],
                            criteria=fmt_criteria(crit["criteria"]), answer=txt[:12000])
        try:
            o = C.luna_json(client, ASYS, user)
            valid = {c["cid"] for c in crit["criteria"]}
            cov = [{"cid": int(x["cid"]), "grade": max(0, min(2, int(x["grade"])))}
                   for x in (o.get("criteria_coverage") or []) if int(x.get("cid", -1)) in valid]
            return arm, qid, {"arm": arm, "qid": qid, "criteria_coverage": cov,
                              "overall": max(0, min(3, int(o.get("overall", 0))))}
        except Exception as e:
            return arm, qid, {"error": f"{type(e).__name__}: {e}"}

    ad = ae = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for fut in as_completed([ex.submit(aworker, j) for j in atodo]):
            arm, qid, res = fut.result()
            if "error" in res:
                ae += 1; continue
            C.dump_json(res, AJDIR / f"{arm}__{qid}.json"); ad += 1
    print(f"answers judged: {ad} ({ae} errored)")
    # persist the committed map for the scorer
    C.dump_json(cmap, DIV / "promptab_committed_map.json")
    print("wrote", DIV / "promptab_committed_map.json")


if __name__ == "__main__":
    main()
