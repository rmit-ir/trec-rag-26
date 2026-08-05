#!/usr/bin/env python3
"""Compare aus_agent prompt variants on trajectory shape AND answer shape.

Extends `2026-08-04-search-strategy-diagnosis.py` (Result 9) with the metrics
the three new variants are each supposed to move, so an arm that changed
nothing is visible as such before any judge is paid:

- `paired-lead`     -> both-eng %, same-lead %, engine mix, leads/round
- `done-condition`  -> rounds, searches, commits, get_documents calls and how
                       many of them fetched a page ADJACENT to a prior hit
- `evidence-dense`  -> uncited-object rate, numerals/1k, modals/1k, refs,
                       cites/object, words

Trajectory shape is read from `*.trajectory.json` `raw_messages` (the provider's
own record of what the model emitted); answer shape from the matching
`*.output.json`. A "round" is a maximal run of consecutive `search` calls
delimited by a reasoning item or a `commit_context` call — the unit
`commit_context` reviews at once.

    uv run --no-project python \
        worklogs/assets/2026-08-05-prompt-variant-comparison.py \
        promptab0805-default promptab0805-paired-lead \
        promptab0805-done-condition promptab0805-evidence-dense
"""
from __future__ import annotations

import collections
import glob
import itertools
import json
import re
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "data/outputs/aus_agent"
PAIR_THRESHOLD = 0.5
MODALS = {"should", "may", "can", "might", "could", "would"}
_NUMERAL_RE = re.compile(r"\b\d[\d,.]*\b")
_PAGE_RE = re.compile(r"^(.*)_p(\d+)$")


def query_similarity(a: str, b: str) -> float:
    xs, ys = set(a.lower().split()), set(b.lower().split())
    return len(xs & ys) / len(xs | ys) if xs | ys else 0.0


def walk_calls(traj: dict):
    """Yield (tool_name, arguments_dict, is_reasoning) in emission order."""
    for msg in traj.get("raw_messages", []):
        if not isinstance(msg, dict):
            continue
        name = msg.get("name")
        if name in ("search", "get_documents", "commit_context"):
            try:
                args = json.loads(msg.get("arguments") or "{}")
            except (TypeError, ValueError):
                args = {}
            yield name, args, False
        elif msg.get("type") == "reasoning":
            yield None, {}, True


def analyse_trajectory(traj: dict) -> dict:
    rounds: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    commits = getdocs = getdoc_ids = adjacent_ids = 0

    # Docids the run ever surfaced. This has to be built BEFORE the walk: an
    # earlier version populated it afterwards, which made `adjacent` structurally
    # zero and would have read as "done-condition changed nothing".
    #
    # It is the run-level set, not an incremental one, because `raw_messages`
    # carries the model's tool CALLS and not the staged ids in their outputs —
    # so a page fetched before its parent was surfaced still counts. That
    # over-counts in the generous direction, which is the safe way round for a
    # metric being read as evidence that a variant DID something.
    seen_docs: set[str] = set()
    seen_ids: set[str] = set()
    for did in traj.get("retrieved_docids") or []:
        m = _PAGE_RE.match(str(did))
        seen_docs.add(m.group(1) if m else str(did))
        seen_ids.add(str(did))

    for name, args, is_reasoning in walk_calls(traj):
        if name == "search":
            current.append((args.get("search_engine"), args.get("query", "")))
            continue
        if name == "get_documents":
            getdocs += 1
            for uid in args.get("ids") or []:
                getdoc_ids += 1
                m = _PAGE_RE.match(str(uid))
                # "adjacent" = a NEW page of a document some hit already
                # surfaced; that is the reading-deeper behaviour, as opposed to
                # re-fetching an id the agent was already handed.
                if m and m.group(1) in seen_docs and str(uid) not in seen_ids:
                    adjacent_ids += 1
        if name == "commit_context":
            commits += 1
        if is_reasoning or name == "commit_context":
            if current:
                rounds.append(current)
                current = []
    if current:
        rounds.append(current)

    engines: collections.Counter = collections.Counter()
    dual = paired = 0
    for group in rounds:
        engines.update(e for e, _ in group)
        if len({e for e, _ in group}) > 1:
            dual += 1
            best = max((query_similarity(q1, q2)
                        for (e1, q1), (e2, q2) in itertools.combinations(group, 2)
                        if e1 != e2), default=0.0)
            if best >= PAIR_THRESHOLD:
                paired += 1
    return {
        "n_rounds": len(rounds),
        "n_searches": sum(len(r) for r in rounds),
        "round_sizes": [len(r) for r in rounds],
        "commits": commits,
        "getdocs": getdocs,
        "getdoc_ids": getdoc_ids,
        "adjacent_ids": adjacent_ids,
        "dual": dual,
        "paired": paired,
        "engines": engines,
        "status": traj.get("status"),
    }


def analyse_answer(out: dict) -> dict:
    answer = out.get("answer") or []
    refs = out.get("references") or []
    texts = [str(a.get("text", "")) for a in answer]
    uncited = sum(1 for a in answer if not (a.get("citations") or []))
    cites = sum(len(a.get("citations") or []) for a in answer)
    words = " ".join(texts).split()
    lower = [w.strip(".,;:()").lower() for w in words]
    n = max(len(words), 1)
    return {
        "objects": len(answer),
        "words": len(words),
        "refs": len(refs),
        "uncited": uncited,
        "cites_per_object": cites / max(len(answer), 1),
        "numerals_1k": 1000 * sum(bool(_NUMERAL_RE.fullmatch(w)) for w in lower) / n,
        "modals_1k": 1000 * sum(w in MODALS for w in lower) / n,
    }


def analyse_run(run_id: str) -> dict | None:
    traj_rows, ans_rows = [], []
    for path in sorted(glob.glob(str(OUTPUTS / "*.output.json"))):
        out = json.load(open(path, encoding="utf-8"))
        if (out.get("metadata") or {}).get("run_id") != run_id:
            continue
        try:
            traj = json.load(open(path.replace(".output.json", ".trajectory.json"),
                                  encoding="utf-8"))
        except FileNotFoundError:
            continue
        traj_rows.append(analyse_trajectory(traj))
        ans_rows.append(analyse_answer(out))
    if not traj_rows:
        return None
    all_rounds = sum(r["n_rounds"] for r in traj_rows) or 1
    sizes = [s for r in traj_rows for s in r["round_sizes"]]
    engines: collections.Counter = collections.Counter()
    for r in traj_rows:
        engines.update(r["engines"])
    mean = lambda rows, k: st.mean(x[k] for x in rows)  # noqa: E731
    return {
        "topics": len(traj_rows),
        "completed": sum(r["status"] == "completed" for r in traj_rows),
        "rounds": mean(traj_rows, "n_rounds"),
        "searches": mean(traj_rows, "n_searches"),
        "per_round": st.mean(sizes) if sizes else 0.0,
        "commits": mean(traj_rows, "commits"),
        "dual": sum(r["dual"] for r in traj_rows) / all_rounds,
        "paired": sum(r["paired"] for r in traj_rows) / all_rounds,
        "getdocs": mean(traj_rows, "getdocs"),
        "getdoc_ids": mean(traj_rows, "getdoc_ids"),
        "adjacent": mean(traj_rows, "adjacent_ids"),
        "engines": dict(engines),
        "objects": mean(ans_rows, "objects"),
        "words": mean(ans_rows, "words"),
        "refs": mean(ans_rows, "refs"),
        "uncited_rate": (sum(a["uncited"] for a in ans_rows)
                         / max(sum(a["objects"] for a in ans_rows), 1)),
        "cites_per_object": mean(ans_rows, "cites_per_object"),
        "numerals_1k": mean(ans_rows, "numerals_1k"),
        "modals_1k": mean(ans_rows, "modals_1k"),
    }


def main(argv: list[str]) -> int:
    runs = argv[1:] or [
        "promptab0805-default", "promptab0805-paired-lead",
        "promptab0805-done-condition", "promptab0805-evidence-dense"]
    rows = {r: analyse_run(r) for r in runs}
    rows = {k: v for k, v in rows.items() if v}
    if not rows:
        print("no matching runs under", OUTPUTS)
        return 1

    def table(title: str, cols: list[tuple[str, str, str]]) -> None:
        print(f"\n{title}")
        head = f"{'run':30s}" + "".join(f"{c[0]:>12s}" for c in cols)
        print(head)
        print("-" * len(head))
        for run_id, row in rows.items():
            line = f"{run_id:30s}"
            for _, key, fmt in cols:
                line += f"{row[key]:>12{fmt}}"
            print(line)

    table("TRAJECTORY SHAPE  (paired-lead and done-condition move these)", [
        ("topics", "topics", "d"), ("done", "completed", "d"),
        ("rounds", "rounds", ".1f"), ("searches", "searches", ".1f"),
        ("/round", "per_round", ".1f"), ("commits", "commits", ".1f"),
    ])
    table("ENGINE PAIRING  (paired-lead's target)", [
        ("both-eng", "dual", ".0%"), ("same-lead", "paired", ".0%"),
    ])
    table("READING DEEPER  (done-condition's target)", [
        ("getdoc/topic", "getdocs", ".1f"), ("ids/topic", "getdoc_ids", ".1f"),
        ("adjacent", "adjacent", ".1f"),
    ])
    table("ANSWER SHAPE  (evidence-dense's target)", [
        ("words", "words", ".0f"), ("objects", "objects", ".1f"),
        ("refs", "refs", ".1f"), ("uncited", "uncited_rate", ".1%"),
        ("cites/obj", "cites_per_object", ".2f"),
        ("num/1k", "numerals_1k", ".1f"), ("modal/1k", "modals_1k", ".1f"),
    ])
    print("\nengine mix:")
    for run_id, row in rows.items():
        total = sum(row["engines"].values()) or 1
        mix = "  ".join(f"{e}={n} ({n / total:.0%})"
                        for e, n in sorted(row["engines"].items()))
        print(f"  {run_id:30s} {mix}")
    print("\nboth-eng  = share of rounds touching more than one engine")
    print(f"same-lead = share of rounds where two searches to DIFFERENT engines "
          f"had query Jaccard >= {PAIR_THRESHOLD}")
    print("adjacent  = get_documents ids that are a NEW page of a document an "
          "earlier hit already surfaced (reading deeper, not re-fetching)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
