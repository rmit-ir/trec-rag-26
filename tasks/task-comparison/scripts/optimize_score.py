#!/usr/bin/env python3
"""Score one prompt variant against the organizer baseline and log a results row.

This is the measurement half of the prompt-optimization loop described in
``docs/auto-optimize/README.md``. Given a completed ``aus_agent`` run id and one
of the frozen splits, it judges that run head-to-head against
``base-agentic-bm25`` — whose 119 answers are frozen on disk, so only our side
ever needs re-running — and upserts one row into
``docs/auto-optimize/results.tsv``, keyed by (stage, variant).

Three things it does that a naive win-rate script would not, each because the
2026-08-04 comparison showed the naive version misleads:

- **Every pair is judged in both presentation orders**, and a topic only counts
  as a win if we won both. The published ``ours-keyword`` vs
  ``base-agentic-bm25`` pair has order consistency 0.782 — the judge disagrees
  with itself on 22% of topics from presentation order alone. A single-order
  win rate measures that noise as if it were quality.
- **A confidence interval is printed next to the point estimate**, by paired
  bootstrap over topics. On 20 topics the interval is roughly +-0.22 wide, so a
  variant scoring 0.55 has not beaten 0.50 and the row says so. This is the
  guard against promoting noise.
- **Word count is logged for both sides.** Result 7 found the arena verdict
  tracks *relative length* (r = -0.429 on the opponent's word count) and is
  indifferent to fact density once length is controlled. So "write longer" is
  the cheapest gradient an optimizer can find, and a win bought that way must be
  visible in the row rather than hidden inside it.

Judge-identity caveat, unchanged from ``judge_test119_arena.py``: the default
judge shares a generator family with our runs and not with the baselines, so
absolute rates carry self-preference. Use ``--judge-model`` to confirm a
promotion under a second judge before believing it.

    PYTHONPATH=src uv run --group aus-agent python \\
        tasks/task-comparison/scripts/optimize_score.py \\
        --run-id opt-evidence-dense --stage dev20 --variant evidence-dense
"""
from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import random
import re
import statistics as st
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evaluation/ragdoll/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import judge_client  # noqa: E402

EVAL = ROOT / "data/task-comparison/test119-eval"
SPLIT_DIR = ROOT / "data/task-comparison"
RESULTS = ROOT / "docs/auto-optimize/results.tsv"
JUDGE_CACHE = ROOT / "data/task-comparison/optimize-arena"
OPPONENT = "base-agentic-bm25"

COLUMNS = [
    "stage", "variant", "run_id", "topics", "wins", "splits", "losses",
    "win_rate", "ci_lo", "ci_hi", "order_consistency",
    # Filled in by optimize_support.py, which updates the row rather than
    # adding a second one — a variant is one line whichever measure ran.
    "wr_first", "wr_base", "wr_delta", "wr_lo", "wr_hi", "support_verdict",
    "words_ours", "words_base", "word_ratio", "uncited_rate",
    "cites_per_object", "digits_per_1k", "refs", "judge", "verdict", "notes",
]
_DIGIT = re.compile(r"\d")


# --------------------------------------------------------------------------
# loading


def load_split(stage: str) -> dict[str, str]:
    path = SPLIT_DIR / f"topics-{stage}.tsv"
    if not path.exists():
        raise SystemExit(f"no such split: {path}\n"
                         f"run make_optimize_splits.py first")
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            qid, _, narrative = line.partition("\t")
            rows[qid.strip()] = narrative.strip()
    return rows


def load_ours(run_id: str) -> dict[str, dict]:
    """Our artifacts for one run id, newest artifact per narrative wins."""
    from ragrun.outputs import submission_output
    newest: dict[str, tuple[str, dict]] = {}
    for path in sorted(glob.glob(str(ROOT / "data/outputs/aus_agent/*.output.json"))):
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        if obj.get("metadata", {}).get("run_id") != run_id:
            continue
        qid = obj["metadata"]["narrative_id"]
        stamp = Path(path).name.split(".")[0]
        if qid not in newest or stamp > newest[qid][0]:
            newest[qid] = (stamp, submission_output(obj))
    return {qid: row for qid, (_stamp, row) in newest.items()}


def load_opponent() -> dict[str, dict]:
    path = EVAL / f"{OPPONENT}.jsonl"
    return {json.loads(l)["metadata"]["narrative_id"]: json.loads(l)
            for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


# --------------------------------------------------------------------------
# structure (no LLM)


def answer_text(row: dict) -> str:
    """Answer prose. Citations live in a separate field, so this is unattributed."""
    return "\n".join(item["text"] for item in row["answer"])


def structure(rows: dict[str, dict], qids: list[str]) -> dict:
    """Cheap structural proxies, computed on exactly the scored topics.

    ``digits_per_1k`` counts whitespace tokens *containing* a digit rather than
    tokens that are entirely numeric. The published strict metric full-matched
    ``\\b\\d[\\d,.]*\\b`` against a whole token, so it structurally could not see
    ``$480``, ``34%`` or ``4.3x`` — and 2026-08-05 found that inverted the
    ranking of two arms, because the arms producing more figures produced them
    predominantly with units attached.
    """
    words, refs, cites, uncited, objects, digits = [], [], [], 0, 0, 0
    for qid in qids:
        row = rows[qid]
        tokens = answer_text(row).split()
        words.append(len(tokens))
        digits += sum(1 for t in tokens if _DIGIT.search(t))
        refs.append(len(row["references"]))
        for item in row["answer"]:
            n = len(item["citations"])
            cites.append(n)
            uncited += (n == 0)
            objects += 1
    return {
        "words": round(st.mean(words), 1),
        "refs": round(st.mean(refs), 1),
        "cites_per_object": round(st.mean(cites), 2),
        "uncited_rate": round(uncited / objects, 4) if objects else 0.0,
        "digits_per_1k": round(1000 * digits / sum(words), 1) if sum(words) else 0.0,
    }


# --------------------------------------------------------------------------
# judging


def load_env() -> None:
    import os
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def judge_one(api, model: str, task: dict, cache: Path) -> dict:
    from ragdoll.arena.prompts import TIE_VERDICTS, render_arena_prompt
    path = cache / f"{task['task_id']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    prompt = render_arena_prompt(query=task["query"], answer_a=task["text_a"],
                                 answer_b=task["text_b"])
    meta = {k: task[k] for k in ("task_id", "topic_id", "run_a", "run_b",
                                 "orientation")}
    try:
        raw = judge_client.complete(api, model, prompt).strip()
        verdict = parse_verdict_lenient(raw)
        if verdict is None:
            record = {**meta, "judge_verdict": None, "preferred_run_id": None,
                      "raw_output": raw[:300], "status": "unparsed"}
        else:
            preferred = (None if verdict in TIE_VERDICTS
                         else (task["run_a"] if verdict == "A" else task["run_b"]))
            record = {**meta, "judge_verdict": verdict,
                      "preferred_run_id": preferred, "raw_output": raw[:300],
                      "status": "completed"}
    except Exception as exc:  # noqa: BLE001
        record = {**meta, "judge_verdict": None, "preferred_run_id": None,
                  "raw_output": f"{type(exc).__name__}: {exc}", "status": "failed"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


_ANYWHERE = re.compile(r"\[\[(A|B|Tie|Tie \(Both Bad\))\]\]")


def parse_verdict_lenient(text: str) -> str | None:
    """RAGDoll's strict parser first, then its documented fallback.

    ``parse_verdict`` uses ``fullmatch``, so a reasoning model's trailing
    commentary drops the battle entirely. Same fallback as
    ``judge_test119_arena.py`` — keep the two in step.
    """
    from ragdoll.arena.prompts import parse_verdict
    strict = parse_verdict(text)
    if strict is not None:
        return strict
    found = _ANYWHERE.findall(text)
    return found[-1] if found else None


def adopt_published(tasks: list[dict], cache: Path, label: str, model: str) -> int:
    """Reuse the 119-topic judgments for the two runs that already have them.

    ``judge_test119_arena.py`` already judged ``ours-semantic`` and
    ``ours-keyword`` against ``base-agentic-bm25`` on all 119 topics, in both
    orders, with this judge and this prompt over these exact answers. Its cache
    keys the pair as ``{qid}__{first}__{second}__o{n}`` where ``first`` is the
    alphabetically-earlier label and orientation 0 puts ``first`` in slot A —
    identical to the convention here. So for those two labels the anchor rows in
    ``results.tsv`` cost nothing, and the loop starts against a real reference
    point rather than an assumed one.

    Anything else falls through and gets judged normally.
    """
    published = EVAL / "arena-judgments" / judge_client.canonical(model)
    if not published.is_dir():
        return 0
    adopted = 0
    for task in tasks:
        target = cache / f"{task['task_id']}.json"
        if target.exists():
            continue
        source = published / (f"{task['topic_id']}__{label}__{OPPONENT}"
                              f"__o{task['orientation']}.json")
        if not source.exists():
            continue
        rec = json.loads(source.read_text(encoding="utf-8"))
        if rec.get("status") != "completed":
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({**rec, "task_id": task["task_id"],
                                      "adopted_from": source.name},
                                     ensure_ascii=False), encoding="utf-8")
        adopted += 1
    return adopted


def run_battles(ours: dict, base: dict, topics: dict, qids: list[str],
                label: str, model: str, workers: int) -> list[dict]:
    tasks = []
    for qid in qids:
        for orientation, (a, b) in enumerate([(label, OPPONENT), (OPPONENT, label)]):
            texts = {label: answer_text(ours[qid]), OPPONENT: answer_text(base[qid])}
            tasks.append({
                "task_id": f"{qid}__{label}__o{orientation}",
                "topic_id": qid, "run_a": a, "run_b": b,
                "orientation": orientation, "query": topics[qid],
                "text_a": texts[a], "text_b": texts[b],
            })
    cache = JUDGE_CACHE / judge_client.canonical(model) / label
    reused = adopt_published(tasks, cache, label, model)
    todo = [t for t in tasks if not (cache / f"{t['task_id']}.json").exists()]
    print(f"  {len(tasks)} battles ({len(qids)} topics x 2 orders), "
          f"{reused} adopted from the published test119 judgments, "
          f"{len(todo)} to judge")
    if todo:
        api = judge_client.client()
        done, lock = 0, threading.Lock()

        def work(task):
            nonlocal done
            record = judge_one(api, model, task, cache)
            with lock:
                done += 1
                if done % 20 == 0:
                    print(f"    judged {done}/{len(todo)}", flush=True)
            return record

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in as_completed([pool.submit(work, t) for t in todo]):
                future.result()
    return [json.loads((cache / f"{t['task_id']}.json").read_text(encoding="utf-8"))
            for t in tasks]


# --------------------------------------------------------------------------
# aggregation


def per_topic_outcomes(records: list[dict], label: str) -> dict[str, float]:
    """1.0 won both orders, 0.0 lost both, 0.5 otherwise (flip or tie)."""
    seen: dict[str, dict[int, str | None]] = collections.defaultdict(dict)
    for rec in records:
        if rec["status"] == "completed":
            seen[rec["topic_id"]][rec["orientation"]] = rec["preferred_run_id"]
    out = {}
    for qid, orientations in seen.items():
        if len(orientations) < 2:
            continue
        votes = list(orientations.values())
        if all(v == label for v in votes):
            out[qid] = 1.0
        elif all(v == OPPONENT for v in votes):
            out[qid] = 0.0
        else:
            out[qid] = 0.5
    return out


def bootstrap_ci(values: list[float], draws: int = 10000) -> tuple[float, float]:
    """Percentile CI over topics. Seeded, so a row is reproducible from its inputs."""
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(20260805)
    n = len(values)
    means = sorted(st.mean(rng.choices(values, k=n)) for _ in range(draws))
    return (means[int(0.025 * draws)], means[int(0.975 * draws)])


def read_rows() -> list[dict]:
    if not RESULTS.exists():
        return []
    with RESULTS.open(encoding="utf-8", newline="") as stream:
        return [r for r in csv.DictReader(stream, delimiter="\t") if r.get("variant")]


def row_key(row: dict) -> tuple[str, str, str]:
    """What makes a results row unique: split, variant, and *judge*.

    The judge belongs in the key. The protocol calls for confirming a promotion
    under a second judge, and with a two-part key that second run would silently
    overwrite the first — destroying the very comparison it was run to make.
    """
    return (row.get("stage", ""), row.get("variant", ""), row.get("judge", ""))


def update_row(stage: str, variant: str, fields: dict, judge: str) -> bool:
    """Merge ``fields`` into the existing row, rewriting the file.

    The arena and support measures run as separate commands but describe one
    variant under one judge, and two half-filled rows for the same thing is how
    a leaderboard starts lying. Returns False when no such row exists, which is
    the caller's cue to say "score the arena first" rather than to invent a row.
    """
    rows = read_rows()
    for row in reversed(rows):
        if row_key(row) == (stage, variant, judge):
            row.update(fields)
            break
    else:
        return False
    with RESULTS.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return True


def upsert_row(row: dict) -> str:
    """Write one row per (stage, variant), replacing any earlier one in place.

    Appending would be simpler and is wrong for a loop that runs unattended: a
    variant re-run after a crash, or re-scored under a second judge, would leave
    two rows for one experiment. The chart would then show a second marker that
    reads as progress, and the goal condition's "12 distinct variants" clause
    would count the same variant twice and exhaust early. Replacing keeps the
    file's row count equal to the number of experiments actually run.

    A replacement keeps the original row's position, so the x axis stays in
    first-scored order and the chart does not reshuffle when a row is refreshed.
    """
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    rows = read_rows()
    action = "appended"
    for i, existing in enumerate(rows):
        if row_key(existing) == row_key(row):
            # Carry the support columns forward only when the answers are the
            # same ones they were computed from. A re-run under a new run id
            # produced different answers, so the old wR would be describing
            # text that no longer exists.
            carried = ({k: v for k, v in existing.items()
                        if k.startswith("wr_") or k == "support_verdict"}
                       if existing.get("run_id") == row["run_id"] else {})
            rows[i] = {**{c: "" for c in COLUMNS}, **carried, **row}
            action = "replaced"
            break
    else:
        rows.append(row)
    with RESULTS.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        for item in rows:
            writer.writerow(item)
    return action


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="aus_agent run id to score")
    parser.add_argument("--stage", required=True,
                        choices=["dev20", "confirm40", "holdout59"])
    parser.add_argument("--variant", help="prompt variant name (defaults to run id)")
    parser.add_argument("--judge-model", default=judge_client.default_model())
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--notes", default="")
    parser.add_argument("--dry-run", action="store_true",
                        help="report coverage and battle count, spend nothing")
    args = parser.parse_args()
    label = args.variant or args.run_id

    load_env()
    topics = load_split(args.stage)
    ours, base = load_ours(args.run_id), load_opponent()
    have = [q for q in topics if q in ours and q in base]
    missing = [q for q in topics if q not in ours]
    print(f"stage={args.stage} run={args.run_id} variant={label}")
    print(f"  {len(have)}/{len(topics)} topics have an artifact"
          + (f"; missing {missing[:6]}{'...' if len(missing) > 6 else ''}"
             if missing else ""))
    if missing:
        print("  REFUSING to score a partial split — a variant scored on the "
              "topics it happened to finish is not comparable to one scored on "
              "all of them. Re-run the missing topics first.")
        return 1
    if args.dry_run:
        print(f"  would judge {2 * len(have)} battles with {args.judge_model}")
        return 0

    records = run_battles(ours, base, topics, have, label, args.judge_model,
                          args.workers)
    bad = [r for r in records if r["status"] != "completed"]
    if bad:
        print(f"  WARNING: {len(bad)} battles did not complete "
              f"({collections.Counter(r['status'] for r in bad)})")

    outcomes = per_topic_outcomes(records, label)
    qids = sorted(outcomes, key=lambda q: int(q.split("-")[1]))
    values = [outcomes[q] for q in qids]
    wins = sum(1 for v in values if v == 1.0)
    losses = sum(1 for v in values if v == 0.0)
    splits = len(values) - wins - losses
    lo, hi = bootstrap_ci(values)
    ours_s = structure(ours, qids)
    base_s = structure(base, qids)

    beats = lo > 0.5
    verdict = "PROMOTE" if beats else ("KILL" if hi < 0.5 else "INCONCLUSIVE")
    row = {
        "stage": args.stage, "variant": label, "run_id": args.run_id,
        "topics": len(values), "wins": wins, "splits": splits, "losses": losses,
        "win_rate": round(st.mean(values), 4),
        "ci_lo": round(lo, 4), "ci_hi": round(hi, 4),
        "order_consistency": round((wins + losses) / len(values), 3) if values else 0,
        "words_ours": ours_s["words"], "words_base": base_s["words"],
        "word_ratio": round(ours_s["words"] / base_s["words"], 3) if base_s["words"] else 0,
        "uncited_rate": ours_s["uncited_rate"],
        "cites_per_object": ours_s["cites_per_object"],
        "digits_per_1k": ours_s["digits_per_1k"], "refs": ours_s["refs"],
        "judge": judge_client.canonical(args.judge_model),
        "verdict": verdict, "notes": args.notes,
    }
    action = upsert_row(row)

    print(f"\n  both-order win rate {row['win_rate']:.3f} "
          f"[{lo:.3f}, {hi:.3f}]   {wins}W-{splits}S-{losses}L")
    print(f"  words {ours_s['words']} vs {base_s['words']} "
          f"({row['word_ratio']:.2f}x)   uncited {ours_s['uncited_rate']:.1%}   "
          f"cites/object {ours_s['cites_per_object']}   "
          f"digits/1k {ours_s['digits_per_1k']}")
    print(f"  verdict: {verdict}")
    if verdict == "INCONCLUSIVE":
        print(f"    the interval straddles 0.5 — on {len(values)} topics this is "
              f"the expected outcome for anything short of a large effect, and "
              f"it is NOT evidence the variant helped.")
    if row["word_ratio"] > 1.15 and row["win_rate"] > 0.5:
        print(f"    CAUTION: this variant is {row['word_ratio']:.2f}x the "
              f"baseline's length. Result 7 showed the judge tracks relative "
              f"length; check the win survives a length-matched comparison.")
    print(f"\n  {action} the {args.stage}/{label} row in {RESULTS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
