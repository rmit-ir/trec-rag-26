#!/usr/bin/env python3
"""Re-derive every number in the 2026-07-31 hand-grading read-through.

This is the surviving evidence behind PLAN §3.3b's gate constants. Two parts:

  1. `resample()` — the exact sampler that produced the two asset JSONs, so the
     22 passages can be regenerated from the labeled input file.
  2. `tally()` — the grade matrix, the class breakdown, both reweightings, the
     agent-agreement table, and the Wilson CIs.

The grades in `MY_GRADES` were assigned by reading each passage against its
narrative *before* the agent's label was revealed (grades 1-14 in one pass,
15-22 in a second), then compared. They are a human judgment, not a computed
quantity — nothing re-derives them.

Run from the repo root:
    uv run --no-project python worklogs/assets/2026-07-31-hand-grade-tally.py
"""
from __future__ import annotations

import collections
import json
import math
import pathlib
import random
import sys

ASSETS = pathlib.Path(__file__).resolve().parent
LABELED = ("data/bm25-tune/inputs/"
           "trec-rag26-test119-search-labeled.jsonl")

#: Hand-assigned grades, 0-3, keyed by the `n` field in the asset JSONs.
MY_GRADES = {1: 2, 2: 1, 3: 3, 4: 2, 5: 0, 6: 3, 7: 2, 8: 0, 9: 0, 10: 3,
             11: 2, 12: 2, 13: 3, 14: 1, 15: 2, 16: 1, 17: 2, 18: 1, 19: 1,
             20: 2, 21: 3, 22: 2}

#: Observed label mix over all 8,580 (topic, chunk) pairs — the reweighting basis.
POOL_MIX = {"positive": 2368, "negative": 6638, "unjudged": 202}
#: The 280-pair calibration sample's mix (positives enriched ~1.8x by design).
SAMPLE_MIX = {"positive": 0.425, "negative": 0.546, "unjudged": 0.029}


def resample() -> None:
    """Regenerate the two samples. Requires the labeled input + bm25tune on path."""
    sys.path.insert(0, "tasks/bm25_tune")
    from bm25tune.extract import strip_page_prefix

    hits = []
    for line in open(LABELED):
        r = json.loads(line)
        if r["engine"] != "keyword":
            continue
        for h in r["results"]:
            hits.append((r["query_id"], r["topic"], r["search_query"],
                         r.get("k"), h))
    print(f"total keyword hits: {len(hits)}")

    # Pass 1 (seed 1729): stratified 5 positive / 7 negative / 2 unjudged.
    rng = random.Random(1729)
    by = {c: [h for h in hits if h[4]["label"] == c]
          for c in ("positive", "negative", "unjudged")}
    sample = (rng.sample(by["positive"], 5) + rng.sample(by["negative"], 7) +
              rng.sample(by["unjudged"], 2))
    rng.shuffle(sample)
    first = _records(sample, 1, strip_page_prefix, rich=True)

    # Pass 2 (seed 90210): 8 more negatives, excluding pass 1's chunk ids —
    # added because 3-of-7 negatives at >=2 was too thin a base for the gate.
    rng2 = random.Random(90210)
    seen = {o["chunk"] for o in first}
    negs = [h for h in hits if h[4]["label"] == "negative"]
    extra = []
    while len(extra) < 8:
        c = rng2.choice(negs)
        if c[4]["id"] in seen:
            continue
        seen.add(c[4]["id"])
        extra.append(c)
    second = _records(extra, 15, strip_page_prefix, rich=False)

    for name, recs in (("2026-07-31-judge-sample-14-stratified.json", first),
                       ("2026-07-31-judge-sample-neg8.json", second)):
        print(f"{name}: {len(recs)} records")
        for o in recs:
            print(f"  {o['n']:2d} {o['qid']:12s} rank={o['rank']:2d} "
                  f"bm25={o['score']:6.2f} chars={len(o['text'])}")


def _records(sample, start, strip_page_prefix, *, rich):
    out = []
    for i, (qid, topic, sq, k, h) in enumerate(sample, start):
        text, stripped = strip_page_prefix(h["text"], h.get("prefix_chars"))
        rec = dict(n=i, qid=qid, topic=topic, search_query=sq, chunk=h["id"],
                   rank=h["rank"], score=h["score"], reason=h.get("reason"),
                   text=text)
        if rich:
            rec.update(k=k, label=h["label"], stripped=stripped,
                       commit_reason=h.get("commit_reason"))
        out.append(rec)
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — the small-n proportion CI the plan quotes."""
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return centre - half, centre + half


def tally() -> None:
    """Every figure PLAN §3.3b cites, recomputed from the asset JSONs."""
    a = json.load(open(ASSETS / "2026-07-31-judge-sample-14-stratified.json"))
    b = json.load(open(ASSETS / "2026-07-31-judge-sample-neg8.json"))
    recs = [(o["n"], o["label"], MY_GRADES[o["n"]]) for o in a]
    recs += [(o["n"], "negative", MY_GRADES[o["n"]]) for o in b]
    recs.sort()

    print("ALL 22 (my grade vs agent label)")
    for n, lab, g in recs:
        print(f"  {n:2d} {lab:9s} grade={g}")

    d = collections.Counter(g for _, _, g in recs)
    n = len(recs)
    print(f"\n--- raw tally (STRATIFIED, not a base-rate estimate) ---")
    print({k: d[k] for k in range(4)}, f"n={n}")
    print(f"  modal {max(d.values()) / n:.3f}  "
          f">=2 {(d[2] + d[3]) / n:.3f}  =3 {d[3] / n:.3f}")

    print("\n--- by agent class ---")
    for cls in ("positive", "negative", "unjudged"):
        sub = [g for _, l, g in recs if l == cls]
        dd = collections.Counter(sub)
        print(f"  {cls:9s} n={len(sub):2d} dist={ {k: dd[k] for k in range(4)} } "
              f">=2 {sum(1 for g in sub if g >= 2) / len(sub):.3f} "
              f"mean {sum(sub) / len(sub):.2f}")

    for label, weights in (("POOL class mix (2368/6638/202)", POOL_MIX),
                           ("280-SAMPLE mix (42.5/54.6/2.9)", SAMPLE_MIX)):
        total = sum(weights.values())
        est = collections.Counter()
        for cls, w in weights.items():
            sub = [g for _, l, g in recs if l == cls]
            dd = collections.Counter(sub)
            for gr in range(4):
                est[gr] += (w / total) * dd[gr] / len(sub)
        print(f"\n--- reweighted to the {label} ---")
        print({k: round(est[k], 3) for k in range(4)})
        print(f"  >=2 {est[2] + est[3]:.3f}   =3 {est[3]:.3f}   "
              f"modal {max(est.values()):.3f}")

    print("\n--- agreement with the agent's staging decision ---")
    tab = collections.Counter()
    for _, l, g in recs:
        if l == "unjudged":
            continue
        tab[(l, "ge2" if g >= 2 else "lt2")] += 1
    print(dict(tab))
    pos = [g for _, l, g in recs if l == "positive"]
    neg = [g for _, l, g in recs if l == "negative"]
    print(f"  mean grade: committed {sum(pos) / len(pos):.2f}  "
          f"rejected {sum(neg) / len(neg):.2f}")
    print(f"  committed I also call >=2: "
          f"{sum(1 for g in pos if g >= 2) / len(pos):.2f}")
    print(f"  rejected I still call >=2: "
          f"{sum(1 for g in neg if g >= 2) / len(neg):.2f}")

    print("\n--- Wilson 95 % CIs on the raw stratified tally (n=22) ---")
    for k, lbl in ((d[2] + d[3], "share >=2"), (d[3], "share =3")):
        lo, hi = wilson(k, n)
        print(f"  {lbl:10s} {k}/{n} = {k / n:.3f}  [{lo:.3f}, {hi:.3f}]")


if __name__ == "__main__":
    if "--resample" in sys.argv:
        resample()
    else:
        tally()
