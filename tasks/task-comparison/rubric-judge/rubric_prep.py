"""Stage 1 — load topics + rubrics, apply the INFORMATION filter, emit
out/rubrics_info.json.

The information filter keeps ONLY criteria whose axis is in
{Explicit Criteria, Implicit Criteria, Synthesis of Information} AND whose
weight > 0 — dropping all Communication/Instruction/Citation/Misc axes and all
negative-weight penalty criteria. Those surviving positive criteria are the
"information requirements" a retrieved doc pool must cover.

Each surviving criterion gets a stable ``cid`` = its 0-based index within the
topic's filtered list, in original file order — so cids are reproducible and
downstream stages (judge/score) can reference criteria by a small integer.

Usage:
    PYTHONPATH=src uv run --group aus-agent python .../rubric_prep.py [--qids ...]
"""
from __future__ import annotations

import argparse

import common as C


def build(qids=None) -> dict:
    topics = C.load_topics()
    rubrics = C.load_rubrics()
    wanted = C.filter_qids(topics.keys(), qids)

    out: dict[str, dict] = {}
    for qid in wanted:
        row = rubrics.get(qid)
        if row is None:
            print(f"  WARN: no rubric row for {qid}, skipping")
            continue
        info = []
        for r in row.get("rubrics", []):
            if r.get("axis") in C.INFO_AXES and float(r.get("weight", 0)) > 0:
                info.append({
                    "cid": len(info),
                    "text": r["criterion"],
                    "weight": float(r["weight"]),
                    "axis": r["axis"],
                })
        out[qid] = {
            "narrative": topics[qid],
            "domain": row.get("domain"),
            "conceptual_breadth": row.get("conceptual_breadth"),
            "logical_nesting": row.get("logical_nesting"),
            "exploration": row.get("exploration"),
            "criteria": info,
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", nargs="*", default=None,
                    help="restrict to these qids (default: all)")
    args = ap.parse_args()

    out = build(args.qids)
    C.dump_json(out, C.OUT / "rubrics_info.json")

    n_crit = sum(len(t["criteria"]) for t in out.values())
    print(f"wrote {C.OUT / 'rubrics_info.json'}")
    print(f"  {len(out)} topics, {n_crit} info criteria "
          f"({n_crit / max(1, len(out)):.1f} per topic)")
    for qid, t in out.items():
        from collections import Counter
        ax = Counter(c["axis"] for c in t["criteria"])
        print(f"  {qid}  domain={t['domain']} breadth={t['conceptual_breadth']} "
              f"nesting={t['logical_nesting']} expl={t['exploration']}  "
              f"criteria={len(t['criteria'])} {dict(ax)}")


if __name__ == "__main__":
    main()
