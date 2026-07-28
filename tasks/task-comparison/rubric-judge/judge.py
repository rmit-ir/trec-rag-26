"""Stage 4 — judge each UNIQUE (qid, docid) once against the topic's info
criteria (ONE luna call per doc), with a resumable per-doc cache + thread pool.

Relevance is a property of (topic, doc), so we judge each pooled doc ONCE
(deduped across engines in stage 3). Each judgment returns strict JSON:
    {"umbrela": 0-3, "coverage": [{"cid": int, "grade": 1|2}, ...]}
- umbrela: holistic 0-3 relevance of the doc to the topic's information need
  (0 irrelevant … 3 highly relevant), scale defined in the prompt.
- coverage: lists ONLY criteria the doc provides evidence for; grade 1 =
  partial support, 2 = fully supports. Omitted criteria => grade 0 (no evidence).

Each judgment is cached to out/judgments/<qid>__<docid>.json so the job is
RESUMABLE (skip any doc whose cache file exists) and safe to re-run. Runs with a
thread pool (default concurrency 8).

Usage:
    PYTHONPATH=src uv run --group aus-agent python .../judge.py [--qids ...] [--workers N]
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import common as C

DOC_CHARS = 6000  # cap doc text handed to the judge (web docs can be huge)

SYSTEM = (
    "You are a strict, careful relevance judge for a research RAG system over "
    "the ClimbMix web corpus. Given a research topic, its information "
    "requirements (rubric criteria), and ONE retrieved document, you output "
    "(a) a holistic UMBRELA relevance grade and (b) which specific information "
    "requirements the document supplies evidence for. Judge ONLY on the "
    "document text shown; do not use outside knowledge to fill gaps. Reward a "
    "criterion only when the document text itself provides the evidence. "
    "Return STRICT JSON only."
)

USER_TMPL = """TOPIC NARRATIVE:
{narrative}

INFORMATION REQUIREMENTS (cid = stable id; grade a doc's evidence per-criterion):
{criteria}

RETRIEVED DOCUMENT (docid {docid}):
\"\"\"
{doc}
\"\"\"

Return STRICT JSON with this exact shape:
{{"umbrela": <0|1|2|3>, "coverage": [{{"cid": <int>, "grade": <1|2>}}, ...]}}

UMBRELA relevance scale (holistic, w.r.t. the topic's information need):
  0 = Irrelevant: the document has nothing to do with the information need.
  1 = Related: the document is on-topic but does not answer any part of the
      information need (background/tangential).
  2 = Relevant: the document addresses part of the information need and
      contains useful information, but is incomplete or partially off-target.
  3 = Highly relevant: the document is dedicated to the information need and
      directly supplies substantial evidence for it.

COVERAGE rules:
  - List ONLY criteria the document provides actual textual evidence for.
  - grade 1 = the document PARTIALLY supports the criterion (touches it /
    partial evidence).
  - grade 2 = the document FULLY supports the criterion (clear, sufficient
    evidence a good answer could cite for that requirement).
  - OMIT any criterion the document gives no evidence for (that means grade 0).
  - Use ONLY cids from the list above.
"""


def fmt_criteria(criteria) -> str:
    return "\n".join(
        f"  [cid {c['cid']}] (w={c['weight']}, {c['axis']}) {c['text']}"
        for c in criteria
    )


def cache_path(qid, docid):
    # docids are safe filenames (shard_NNNNN_MMMM), but sanitize defensively.
    safe = docid.replace("/", "_")
    return C.JUDGE_DIR / f"{qid}__{safe}.json"


def judge_doc(client, qid, docid, doc_text, criteria) -> dict:
    user = USER_TMPL.format(
        narrative=criteria["narrative"],
        criteria=fmt_criteria(criteria["criteria"]),
        docid=docid,
        doc=(doc_text or "")[:DOC_CHARS],
    )
    obj = C.luna_json(client, SYSTEM, user)
    valid_cids = {c["cid"] for c in criteria["criteria"]}
    umb = int(obj.get("umbrela", 0))
    umb = max(0, min(3, umb))
    cov = []
    for item in obj.get("coverage", []) or []:
        try:
            cid = int(item["cid"])
            g = int(item["grade"])
        except (KeyError, TypeError, ValueError):
            continue
        if cid in valid_cids and g in (1, 2):
            cov.append({"cid": cid, "grade": g})
    # dedup cids, keep max grade
    best = {}
    for c in cov:
        best[c["cid"]] = max(best.get(c["cid"], 0), c["grade"])
    coverage = [{"cid": k, "grade": v} for k, v in sorted(best.items())]
    return {"docid": docid, "umbrela": umb, "coverage": coverage}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    rubrics_info = C.load_json(C.OUT / "rubrics_info.json")
    pool = C.load_json(C.OUT / "pool.json")
    wanted = C.filter_qids(pool.keys(), args.qids)
    C.JUDGE_DIR.mkdir(parents=True, exist_ok=True)
    client = C.luna_client()

    # build the work list, skipping cached judgments (resumable)
    todo = []
    n_cached = 0
    for qid in wanted:
        crit = rubrics_info[qid]
        for docid, d in pool[qid].items():
            if cache_path(qid, docid).exists():
                n_cached += 1
                continue
            todo.append((qid, docid, d["text"], crit))
    print(f"judge: {len(todo)} to do, {n_cached} already cached "
          f"(workers={args.workers})", flush=True)

    def worker(job):
        qid, docid, text, crit = job
        try:
            res = judge_doc(client, qid, docid, text, crit)
        except Exception as e:  # persist the error so a re-run retries it
            return qid, docid, {"error": f"{type(e).__name__}: {e}"}
        return qid, docid, res

    done = err = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(worker, j) for j in todo]
        for fut in as_completed(futs):
            qid, docid, res = fut.result()
            if "error" in res:
                err += 1
                print(f"  ERR {qid} {docid}: {res['error']}", flush=True)
                continue  # do NOT cache errors -> retried next run
            C.dump_json(res, cache_path(qid, docid))
            done += 1
            if done % 10 == 0:
                print(f"  judged {done}/{len(todo)} (errors {err})", flush=True)

    print(f"done: {done} judged, {err} errored, {n_cached} were cached.")
    print(f"judgments in {C.JUDGE_DIR}")


if __name__ == "__main__":
    main()
