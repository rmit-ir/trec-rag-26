"""Judge the COMMITTED docs of the 4 per-engine dev-*-30 runs against each
topic's info criteria — ONE luna call per uncached (qid, docid), reusing the
SAME cache dir as judge.py (out/judgments/) so docs already judged in the pool
are free. Emits {"umbrela":0-3,"coverage":[{cid,grade}]} per doc, exactly like
judge.py (imported wholesale for identical prompt + validation).

Inputs (from the diversity build):
  data/task-comparison/diversity/committed_map.json   {qid: {engine: [docid]}}
  data/task-comparison/diversity/doc_text.jsonl       {docid, qid, text}
Ground truth: out/rubrics_info.json (filtered info criteria per topic).

Run:  PYTHONPATH=src uv run --group aus-agent python \
        tasks/task-comparison/rubric-judge/judge_committed.py [--workers N]
Resumable + safe to re-run (errors are not cached).
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import common as C
import judge as J  # reuse judge_doc() + cache_path() => identical prompt/validation

DIV = C.ROOT / "data/task-comparison/diversity"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    committed = C.load_json(DIV / "committed_map.json")
    rubrics_info = C.load_json(C.OUT / "rubrics_info.json")
    text = {}
    for line in (DIV / "doc_text.jsonl").read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            text[d["docid"]] = d["text"]

    C.JUDGE_DIR.mkdir(parents=True, exist_ok=True)
    client = C.luna_client()

    todo, n_cached, n_notext = [], 0, 0
    for qid, engmap in committed.items():
        crit = rubrics_info[qid]
        docs = set()
        for dl in engmap.values():
            docs.update(dl)
        for docid in docs:
            if J.cache_path(qid, docid).exists():
                n_cached += 1
                continue
            if docid not in text:
                n_notext += 1
                continue
            todo.append((qid, docid, text[docid], crit))
    print(f"judge_committed: {len(todo)} to do, {n_cached} cached, "
          f"{n_notext} missing-text (workers={args.workers})", flush=True)

    def worker(job):
        qid, docid, txt, crit = job
        try:
            return qid, docid, J.judge_doc(client, qid, docid, txt, crit)
        except Exception as e:
            return qid, docid, {"error": f"{type(e).__name__}: {e}"}

    done = err = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(worker, j) for j in todo]
        for fut in as_completed(futs):
            qid, docid, res = fut.result()
            if "error" in res:
                err += 1
                print(f"  ERR {qid} {docid}: {res['error']}", flush=True)
                continue
            C.dump_json(res, J.cache_path(qid, docid))
            done += 1
            if done % 25 == 0:
                print(f"  judged {done}/{len(todo)} (errors {err})", flush=True)

    print(f"done: {done} judged, {err} errored, {n_cached} cached, {n_notext} no-text.")


if __name__ == "__main__":
    main()
