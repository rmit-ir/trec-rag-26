"""RAGDOLL-style ANSWER-level eval per engine: judge each generated answer of
the 4 dev-*-30 runs against its topic's info criteria (rubric coverage of the
FINAL ANSWER, not the retrieved docs). ONE luna call per (engine, topic) = 120.

Answer text = concat of output.json `answer[].text` for run_id dev-<engine>-30.
Judgment: {"criteria_coverage":[{cid,grade 0-2}], "overall": 0-3} where grade
is how well the ANSWER satisfies that information requirement (0 none / 1 partial
/ 2 full), overall = holistic answer quality vs the topic's information need.

Cache -> out/answer_judgments/<engine>__<qid>.json (resumable). Then aggregates
weighted answer-coverage per engine and prints the ranking.

Run:  PYTHONPATH=src uv run --group aus-agent python \
        tasks/task-comparison/rubric-judge/judge_answers.py [--workers N]
"""
from __future__ import annotations

import argparse
import glob
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import common as C

RUN2ENG = {"dev-dense-30": "dense", "dev-keyword-30": "keyword",
           "dev-ssr-30": "ssr", "dev-lucene-30": "lucene"}
ADIR = C.OUT / "answer_judgments"

SYSTEM = (
    "You are a strict evaluator for a research RAG system over the ClimbMix web "
    "corpus. Given a research topic, its information requirements (rubric "
    "criteria), and a system's FINAL ANSWER, grade how well the answer satisfies "
    "each information requirement, and give a holistic quality grade. Judge ONLY "
    "the answer text shown. Ignore length/format/citation-style requirements; "
    "grade on INFORMATION content only. Return STRICT JSON only."
)
USER_TMPL = """TOPIC NARRATIVE:
{narrative}

INFORMATION REQUIREMENTS (cid = stable id):
{criteria}

SYSTEM FINAL ANSWER:
\"\"\"
{answer}
\"\"\"

Return STRICT JSON:
{{"criteria_coverage": [{{"cid": <int>, "grade": <0|1|2>}}, ...], "overall": <0|1|2|3>}}
  grade per criterion: 0 = answer does not satisfy it, 1 = partially, 2 = fully.
  Include EVERY cid from the list. overall = holistic answer quality vs the need
  (0 poor … 3 excellent). Use ONLY cids from the list above.
"""


def load_answers():
    """{(engine, qid): answer_text}."""
    out = {}
    for f in glob.glob(str(C.ROOT / "data/outputs/aus_agent/*.output.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        eng = RUN2ENG.get(d.get("metadata", {}).get("run_id"))
        if not eng:
            continue
        qid = d["metadata"]["narrative_id"]
        ans = d.get("answer") or []
        txt = "\n".join(s.get("text", "") for s in ans if isinstance(s, dict))
        out[(eng, qid)] = txt
    return out


def fmt_criteria(crit):
    return "\n".join(f"  [cid {c['cid']}] (w={c['weight']}, {c['axis']}) {c['text']}" for c in crit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    answers = load_answers()
    rinfo = C.load_json(C.OUT / "rubrics_info.json")
    ADIR.mkdir(parents=True, exist_ok=True)
    client = C.luna_client()

    todo = []
    for (eng, qid), txt in answers.items():
        p = ADIR / f"{eng}__{qid}.json"
        if p.exists() or not txt.strip():
            continue
        todo.append((eng, qid, txt, rinfo[qid]))
    print(f"answer-judge: {len(todo)} to do, {len(answers) - len(todo)} cached/empty "
          f"(workers={args.workers})", flush=True)

    def worker(job):
        eng, qid, txt, crit = job
        user = USER_TMPL.format(narrative=crit["narrative"],
                                criteria=fmt_criteria(crit["criteria"]),
                                answer=txt[:12000])
        try:
            obj = C.luna_json(client, SYSTEM, user)
            valid = {c["cid"] for c in crit["criteria"]}
            cov = [{"cid": int(x["cid"]), "grade": max(0, min(2, int(x["grade"])))}
                   for x in obj.get("criteria_coverage", [])
                   if int(x.get("cid", -1)) in valid]
            return eng, qid, {"engine": eng, "qid": qid,
                              "overall": max(0, min(3, int(obj.get("overall", 0)))),
                              "criteria_coverage": cov}
        except Exception as e:
            return eng, qid, {"error": f"{type(e).__name__}: {e}"}

    done = err = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for fut in as_completed([ex.submit(worker, j) for j in todo]):
            eng, qid, res = fut.result()
            if "error" in res:
                err += 1
                print(f"  ERR {eng} {qid}: {res['error']}", flush=True)
                continue
            C.dump_json(res, ADIR / f"{eng}__{qid}.json")
            done += 1
    print(f"done: {done} judged, {err} errored.")

    # ---- aggregate weighted answer-coverage + overall per engine ----
    covL = defaultdict(list); covF = defaultdict(list); ov = defaultdict(list)
    for p in ADIR.glob("*.json"):
        d = C.load_json(p)
        if "error" in d:
            continue
        eng, qid = d["engine"], d["qid"]
        crit = rinfo[qid]["criteria"]
        cid2w = {c["cid"]: c["weight"] for c in crit}
        tw = sum(cid2w.values()) or 1.0
        g = {c["cid"]: c["grade"] for c in d["criteria_coverage"]}
        covL[eng].append(sum(w for cid, w in cid2w.items() if g.get(cid, 0) >= 1) / tw)
        covF[eng].append(sum(w for cid, w in cid2w.items() if g.get(cid, 0) >= 2) / tw)
        ov[eng].append(d["overall"])

    def avg(xs): return sum(xs) / len(xs) if xs else float("nan")
    agg = {e: {"answer_cov_partial": avg(covL[e]), "answer_cov_full": avg(covF[e]),
               "overall": avg(ov[e]), "n": len(ov[e])} for e in RUN2ENG.values()}
    (DIV_OUT := C.ROOT / "data/task-comparison/diversity" / "answer_quality.json").write_text(
        json.dumps(agg, indent=2))
    print("\nRAGDOLL answer quality per engine (weighted rubric coverage of the ANSWER):")
    for e in sorted(agg, key=lambda k: -agg[k]["answer_cov_partial"]):
        a = agg[e]
        print(f"  {e:8} cov≥1={a['answer_cov_partial']:.3f} cov=full={a['answer_cov_full']:.3f} "
              f"overall={a['overall']:.2f} (n={a['n']})")
    print("wrote", DIV_OUT)


if __name__ == "__main__":
    main()
