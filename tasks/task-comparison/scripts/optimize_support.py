#!/usr/bin/env python3
"""Weighted citation support for one prompt variant, paired against the baseline.

The second — and primary — measure in the optimization loop. It fills the
``wr_*`` columns of the row ``optimize_score.py`` created, rather than adding a
row of its own.

**Why this and not the arena.** The two organizer baselines settle it. On the
arena they are 3.4x apart (``base-agentic-bm25`` 0.654 preference,
``base-singlepass`` 0.195); on weighted citation support they are *tied*
(wR_first 0.6353 vs 0.6342, wP_first 0.6353 vs 0.6342). Two measures that rank
the same two systems that differently are not measuring the same property, so
neither can proxy for the other. And the deficit lives here: our published runs
score wR_first 0.5283 / 0.5174 against the baselines' 0.635, a clear gap on the
track's announced measure, while the arena against the stronger baseline is a
dead heat (0.485). Optimizing a dead heat optimizes noise.

**Recall, not precision.** Both baselines have wP == wR *exactly*, because both
cite every answer object; ours have wR < wP by exactly the uncited-object
penalty. So weighted precision alone rewards saying less and citing more
cautiously — the mirror image of the arena's reward for saying more. ``wR_first``
is the headline because it charges for both halves: a bare sentence scores zero
in the numerator and still counts in the denominator.

Methodology is RAGDoll's throughout (``render_support_prompt``,
``parse_support_label``, ``support_metric``); only execution is ours, and it
follows ``judge_test119_support.py`` so the numbers stay comparable to the
published table. First citation only, which is the TREC 2024 protocol and a
third of the judge calls.

    PYTHONPATH=src uv run --group aus-agent python \\
        tasks/task-comparison/scripts/optimize_support.py \\
        --run-id opt-evidence-paired --stage dev20 --variant evidence-paired
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import statistics as st
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evaluation/ragdoll/src"))


def _sibling(name: str):
    """Import a sibling script by path — this directory is not a package."""
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


score = _sibling("optimize_score")
resolver = _sibling("resolve_test119_refs")
sys.path.insert(0, str(HERE))
import judge_client  # noqa: E402

EVAL = ROOT / "data/task-comparison/test119-eval"
PUBLISHED_SUPPORT = EVAL / "support-judgments"
CACHE = ROOT / "data/task-comparison/optimize-support"
OPPONENT = "base-agentic-bm25"
LABEL_SCORES = {"FS": 2, "PS": 1, "NS": 0}


def resolve_segments(rows: dict[str, dict], workers: int, rate: float,
                     timeout: float) -> dict[str, dict[str, str]]:
    """docid -> passage text for every reference, via the shared doc cache.

    Text comes from the official Pyserini doc endpoint for *every* run, never
    from our own trajectories: our agent retrieves chunks and the baselines
    retrieve whole documents, so harvesting trajectory text would hand the judge
    a short focused passage for us and a full document for them. Same reasoning
    — and the same on-disk cache — as ``resolve_test119_refs.py``, so a variant
    citing documents the published runs already cited fetches nothing.
    """
    import os
    token = os.environ.get("PYSERINI_API_TOKEN")
    wanted = sorted({d for row in rows.values() for d in row["references"]})
    missing = [d for d in wanted if not resolver.cache_path(d).exists()]
    print(f"  {len(wanted)} distinct cited docids, {len(missing)} not in the "
          f"shared doc cache")
    if missing:
        if not token:
            raise SystemExit("PYSERINI_API_TOKEN is not set and "
                             f"{len(missing)} documents need fetching")
        limiter = resolver.RateLimiter(rate)
        failures: dict[str, str] = {}
        lock = threading.Lock()

        def work(docid: str) -> None:
            try:
                text = resolver.fetch(docid, token, timeout, limiter=limiter)
            except Exception as exc:  # noqa: BLE001 — record and keep going
                with lock:
                    failures[docid] = f"{type(exc).__name__}: {exc}"
                return
            path = resolver.cache_path(docid)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in as_completed([pool.submit(work, d) for d in missing]):
                future.result()
        if failures:
            print(f"  WARNING: {len(failures)} documents could not be fetched; "
                  f"their citations are dropped from the denominator, which "
                  f"flatters the score — {list(failures)[:3]}")
    return {qid: {d: resolver.cache_path(d).read_text(encoding="utf-8")
                  for d in row["references"] if resolver.cache_path(d).exists()}
            for qid, row in rows.items()}


def pairs_for(qid: str, row: dict, segments: dict[str, str],
              label: str, max_chars: int) -> list[dict]:
    """One (answer object, first cited passage) pair per citing object."""
    out = []
    for si, item in enumerate(row["answer"]):
        for ci, citation in enumerate(item["citations"][:1]):
            docid = (row["references"][citation] if isinstance(citation, int)
                     else citation)
            passage = segments.get(docid)
            if not passage:
                continue
            out.append({"task_id": f"{label}__{qid}__s{si}__c{ci}",
                        "run_id": label, "topic_id": qid, "sentence_index": si,
                        "citation_index": ci, "docid": docid,
                        "statement": item["text"],
                        "citation": passage[:max_chars]})
    return out


def judge_one(api, model: str, pair: dict, cache: Path) -> dict:
    from ragdoll.support.prompts import parse_support_label, render_support_prompt
    path = cache / f"{pair['task_id']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    meta = {k: pair[k] for k in ("task_id", "run_id", "topic_id",
                                 "sentence_index", "citation_index", "docid")}
    try:
        raw = judge_client.complete(api, model, render_support_prompt(
            statement=pair["statement"], citation=pair["citation"])).strip()
        label = parse_support_label(raw)
        record = {**meta, "support_label": label, "raw_output": raw[:400],
                  "status": "completed" if label else "unparsed"}
    except Exception as exc:  # noqa: BLE001 — a dead pair must not kill the run
        record = {**meta, "support_label": None,
                  "raw_output": f"{type(exc).__name__}: {exc}", "status": "failed"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


def adopt_published(pairs: list[dict], cache: Path, label: str, model: str) -> int:
    """Reuse ``judge_test119_support.py``'s judgments for the published runs.

    Its cache key is ``{run}__{qid}__s{n}__c{n}``, identical to the one built
    here, so the anchor rows cost nothing. Same judge, same prompt, same
    statement, same passage.
    """
    published = PUBLISHED_SUPPORT / judge_client.canonical(model)
    if not published.is_dir():
        return 0
    adopted = 0
    for pair in pairs:
        target = cache / f"{pair['task_id']}.json"
        source = published / f"{pair['task_id']}.json"
        if target.exists() or not source.exists():
            continue
        rec = json.loads(source.read_text(encoding="utf-8"))
        if rec.get("status") != "completed":
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({**rec, "adopted": True}, ensure_ascii=False),
                          encoding="utf-8")
        adopted += 1
    return adopted


def metrics_per_topic(rows: dict[str, dict], judged: dict, qids: list[str],
                      label: str) -> dict[str, tuple[float, float]]:
    """(wR_first, wP_first) per topic, through RAGDoll's ``support_metric``.

    ``-1`` is RAGDoll's "no label" marker: such a citation leaves both numerator
    and denominator instead of scoring zero, so an unparsed judgment does not
    silently count as unsupported.
    """
    from ragdoll.support.metrics import support_metric
    out = {}
    for qid in qids:
        row = rows[qid]
        sentences = []
        for si, item in enumerate(row["answer"]):
            scored = []
            for ci, citation in enumerate(item["citations"][:1]):
                docid = (row["references"][citation] if isinstance(citation, int)
                         else citation)
                lab = judged.get((qid, si, ci))
                scored.append({"citationID": ci, "reference": docid,
                               "support": LABEL_SCORES.get(lab, -1)})
            sentences.append({"sentenceID": si, "text": item["text"],
                              "citations": scored})
        result = support_metric({"topic_id": qid, "run_id": label,
                                 "sentences": sentences})
        out[qid] = (float(result.weighted_recall_first_citation),
                    float(result.weighted_precision_first_citation))
    return out


def paired_ci(deltas: list[float], draws: int = 10000) -> tuple[float, float]:
    """Percentile CI on the per-topic paired difference. Seeded, so reproducible."""
    if not deltas:
        return (float("nan"), float("nan"))
    rng = random.Random(20260805)
    n = len(deltas)
    means = sorted(st.mean(rng.choices(deltas, k=n)) for _ in range(draws))
    return (means[int(0.025 * draws)], means[int(0.975 * draws)])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--stage", required=True,
                        choices=["dev20", "confirm40", "holdout59"])
    parser.add_argument("--variant")
    parser.add_argument("--judge-model", default=judge_client.default_model())
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--max-chars", type=int, default=24000)
    parser.add_argument("--fetch-workers", type=int, default=12)
    parser.add_argument("--fetch-rate", type=float, default=6.0)
    parser.add_argument("--fetch-timeout", type=float, default=90.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    label = args.variant or args.run_id

    score.load_env()
    topics = score.load_split(args.stage)
    ours = score.load_ours(args.run_id)
    base = score.load_opponent()
    qids = [q for q in topics if q in ours and q in base]
    missing = [q for q in topics if q not in ours]
    print(f"stage={args.stage} run={args.run_id} variant={label}")
    print(f"  {len(qids)}/{len(topics)} topics have an artifact")
    if missing:
        print(f"  REFUSING to score a partial split — missing {missing[:6]}")
        return 1

    print("resolving cited documents")
    ours_rows = {q: ours[q] for q in qids}
    base_rows = {q: base[q] for q in qids}
    ours_seg = resolve_segments(ours_rows, args.fetch_workers, args.fetch_rate,
                                args.fetch_timeout)
    base_seg = resolve_segments(base_rows, args.fetch_workers, args.fetch_rate,
                                args.fetch_timeout)

    plans = [(label, ours_rows, ours_seg), (OPPONENT, base_rows, base_seg)]
    all_pairs = {name: [p for q in qids
                        for p in pairs_for(q, rows[q], seg[q], name, args.max_chars)]
                 for name, rows, seg in plans}
    judge_dir = judge_client.canonical(args.judge_model)
    caches = {name: CACHE / judge_dir / name for name in all_pairs}
    adopted = {name: adopt_published(all_pairs[name], caches[name], name,
                                     args.judge_model)
               for name in all_pairs}
    todo = {name: [p for p in all_pairs[name]
                   if not (caches[name] / f"{p['task_id']}.json").exists()]
            for name in all_pairs}
    for name in all_pairs:
        print(f"  {name:22s} {len(all_pairs[name]):4d} pairs, "
              f"{adopted[name]:4d} adopted, {len(todo[name]):4d} to judge")
    if args.dry_run:
        return 0

    flat = [(name, p) for name in all_pairs for p in todo[name]]
    if flat:
        api = judge_client.client(timeout=180.0)
        done, lock = 0, threading.Lock()

        def work(item):
            nonlocal done
            name, pair = item
            record = judge_one(api, args.judge_model, pair, caches[name])
            with lock:
                done += 1
                if done % 100 == 0:
                    print(f"    judged {done}/{len(flat)}", flush=True)
            return record

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(work, i) for i in flat]):
                future.result()

    scores = {}
    for name, rows, _seg in plans:
        judged = {}
        unparsed = 0
        for pair in all_pairs[name]:
            rec = json.loads((caches[name] / f"{pair['task_id']}.json")
                             .read_text(encoding="utf-8"))
            if rec["status"] == "completed":
                judged[(rec["topic_id"], rec["sentence_index"],
                        rec["citation_index"])] = rec["support_label"]
            else:
                unparsed += 1
        if unparsed:
            print(f"  {name}: {unparsed} pairs unjudged (left out of both "
                  f"numerator and denominator)")
        scores[name] = metrics_per_topic(rows, judged, qids, name)

    wr_ours = [scores[label][q][0] for q in qids]
    wr_base = [scores[OPPONENT][q][0] for q in qids]
    wp_ours = [scores[label][q][1] for q in qids]
    deltas = [a - b for a, b in zip(wr_ours, wr_base)]
    lo, hi = paired_ci(deltas)
    better = sum(1 for d in deltas if d > 0)
    worse = sum(1 for d in deltas if d < 0)
    verdict = ("PROMOTE" if lo > 0 else "KILL" if hi < 0 else "INCONCLUSIVE")

    print(f"\n  wR_first  ours {st.mean(wr_ours):.4f}   "
          f"{OPPONENT} {st.mean(wr_base):.4f}")
    print(f"  wP_first  ours {st.mean(wp_ours):.4f}")
    print(f"  paired delta {st.mean(deltas):+.4f} [{lo:+.4f}, {hi:+.4f}]   "
          f"better on {better}, worse on {worse}, tied on "
          f"{len(deltas) - better - worse}")
    print(f"  support verdict: {verdict}")

    fields = {"wr_first": round(st.mean(wr_ours), 4),
              "wr_base": round(st.mean(wr_base), 4),
              "wr_delta": round(st.mean(deltas), 4),
              "wr_lo": round(lo, 4), "wr_hi": round(hi, 4),
              "support_verdict": verdict}
    fields["judge"] = judge_client.canonical(args.judge_model)
    if score.update_row(args.stage, label, fields,
                        judge_client.canonical(args.judge_model)):
        print(f"  updated the {args.stage}/{label} row in "
              f"{score.RESULTS.relative_to(ROOT)}")
    else:
        print(f"  no {args.stage}/{label} row for judge {judge_client.canonical(args.judge_model)} — "
              f"run optimize_score.py with the same --judge-model first, so the "
              f"arena and support numbers share one row")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
