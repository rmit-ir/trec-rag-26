#!/usr/bin/env python3
"""Render ``docs/auto-optimize/results.tsv`` to ``docs/auto-optimize/progress.svg``.

Six panels, laid out like ``tmp/retrieval-autoresearch/progress.svg``: one point
per scored variant in the order it was scored, a running-best line, and a dashed
reference line for the thing that would count as parity.

Written with the standard library only — no matplotlib, no env to activate. That
is deliberate: this runs inside the ``/goal`` loop after every variant, and a
plot step that can fail on a missing dependency would stall the loop for a
cosmetic reason.

**The length panel is not decoration.** Result 7 found the arena judge's verdict
tracks relative answer length (r = -0.429 on the opponent's word count) and is
blind to fact density once length is controlled, so the cheapest way for an
optimizer to raise the arena panel is to write longer answers. Plotting the
length ratio on the same page makes that failure mode visible next to the number
it would corrupt.

    uv run --no-project python tasks/task-comparison/scripts/optimize_plot.py
"""
from __future__ import annotations

import argparse
import csv
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "docs/auto-optimize/results.tsv"
OUT = ROOT / "docs/auto-optimize/progress.svg"

# (column, title, reference line, reference label, higher_is_better)
#
# Order matters — the primary measure leads. Weighted citation recall is the
# track's announced measure, it is where the deficit is unambiguous, and it is
# the one that resolves at n=20: on dev20 the arena reads 0.450 [0.250, 0.650]
# for the same run whose support delta reads -0.073 [-0.134, -0.020].
PANELS = [
    ("wr_delta", "Weighted citation recall - baseline (paired)", 0.0, "parity",
     True),
    ("win_rate", "Both-order arena win rate vs base-agentic-bm25", 0.5, "parity",
     True),
    ("word_ratio", "Answer length / baseline length", 1.0, "length parity", None),
    ("uncited_rate", "Uncited answer objects", 0.0, "baselines (0%)", False),
    ("cites_per_object", "Citations per answer object", 1.72,
     "base-agentic-bm25", True),
    ("digits_per_1k", "Figures per 1k words (any-digit token)", 19.2,
     "base-agentic-bm25", True),
]
# Panels whose point estimate carries a bootstrap interval -> column pair.
WHISKERS = {"win_rate": ("ci_lo", "ci_hi"), "wr_delta": ("wr_lo", "wr_hi")}
STAGE_COLOUR = {"dev20": "#9aa5b1", "confirm40": "#2f6fb5", "holdout59": "#c2410c"}
W, PAD, PANEL_H = 1240, 62, 218
ROWS = (len(PANELS) + 1) // 2
H = 96 + ROWS * (PANEL_H + PAD) + 20
PANEL_W = (W - 3 * PAD) // 2


def load(path: Path) -> list[dict]:
    """Rows in scoring order, one per (stage, variant), last write winning.

    ``optimize_score.py`` upserts, but a results file edited by hand or carried
    over from an older run can still hold duplicates. Two markers for one
    variant would make a re-score look like progress, so collapse here too and
    say how many were dropped.
    """
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as stream:
        rows = [r for r in csv.DictReader(stream, delimiter="\t") if r.get("variant")]
    def key(row):
        return (row.get("stage", ""), row["variant"], row.get("judge", ""))

    seen: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        seen[key(row)] = row
    if len(seen) != len(rows):
        print(f"  collapsed {len(rows) - len(seen)} duplicate "
              f"(stage, variant, judge) row(s)")
    return [r for r in rows if seen.get(key(r)) is r]


def for_judge(rows: list[dict], judge: str | None) -> tuple[list[dict], str | None]:
    """One judge's rows. Mixing judges on one axis would compare incomparables.

    Defaults to whichever judge scored first, so the chart tracks the primary
    measurement and a second-judge confirmation run does not silently interleave
    two different instruments into one series.
    """
    if not rows:
        return rows, None
    chosen = judge or rows[0].get("judge", "")
    kept = [r for r in rows if r.get("judge", "") == chosen]
    dropped = len(rows) - len(kept)
    if dropped:
        others = sorted({r.get("judge", "") for r in rows} - {chosen})
        print(f"  plotting judge {chosen}; {dropped} row(s) from {others} "
              f"omitted (pass --judge to switch)")
    return kept, chosen


def shown(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise.

    ``Path.relative_to`` *raises* on a path outside the repo, which turned a
    ``--out /tmp/...`` run into a traceback after the file had already been
    written successfully. A progress-log line must never be able to fail a step
    that worked.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def number(row: dict, key: str) -> float | None:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None


def nice_bounds(values: list[float], reference: float,
                extra: list[float] | None = None) -> tuple[float, float]:
    """Axis range covering the data, the reference line, and any whiskers.

    ``extra`` carries the confidence-interval endpoints. Leaving them out was a
    real defect: with points at 0.450/0.425 against a 0.5 reference the axis
    spanned [0.419, 0.506] while the arena CIs ran [0.250, 0.650], so the
    whiskers were drawn at y = 618 and y = -173 on a panel 218px tall — off the
    canvas and straight through the panel below. A drawn element must always be
    inside the range that scales it.
    """
    pool = [v for v in values if v is not None] + [reference]
    pool += [v for v in (extra or []) if v is not None]
    lo, hi = min(pool), max(pool)
    if hi - lo < 1e-9:
        lo, hi = lo - 0.5, hi + 0.5
    margin = 0.08 * (hi - lo)
    return lo - margin, hi + margin


def marker_geometry(n: int) -> tuple[float, bool, int]:
    """(radius, draw whiskers, x-label stride) for ``n`` variants.

    The panel gives ~433px of plotting width, so at n=50 the points are 8.7px
    apart and a 4.5px-radius marker already touches its neighbours. Shrink the
    marker as the run grows and drop the whiskers once they would merge into a
    grey band that reads as a fill rather than as intervals.
    """
    if n <= 24:
        return 4.5, True, 1
    if n <= 60:
        return 3.2, True, 5
    return 2.2, False, 10


def panel(rows: list[dict], key: str, title: str, reference: float,
          ref_label: str, higher: bool | None, ox: float, oy: float,
          index: int) -> list[str]:
    out: list[str] = []
    clip = f"panel{index}"
    out.append(f'<clipPath id="{clip}"><rect x="{ox}" y="{oy}" '
               f'width="{PANEL_W}" height="{PANEL_H}"/></clipPath>')
    out.append(f'<rect x="{ox}" y="{oy}" width="{PANEL_W}" height="{PANEL_H}" '
               f'fill="#ffffff" stroke="#d5dae1"/>')
    out.append(f'<text x="{ox}" y="{oy - 12}" font-size="15" font-weight="600" '
               f'fill="#1f2933">{html.escape(title)}</text>')

    values = [number(r, key) for r in rows]
    n = max(len(rows), 1)
    radius, whiskers, stride = marker_geometry(len(rows))
    bounds_extra: list[float] = []
    if key in WHISKERS and whiskers:
        lo_key, hi_key = WHISKERS[key]
        for row in rows:
            bounds_extra += [number(row, lo_key), number(row, hi_key)]
    lo, hi = nice_bounds(values, reference, bounds_extra)
    # Everything data-driven is clipped to the panel, so an unforeseen outlier
    # degrades to a truncated mark instead of scribbling over the whole page.
    out.append(f'<g clip-path="url(#{clip})">')

    def px(i: int) -> float:
        return ox + 42 + (PANEL_W - 62) * ((i + 0.5) / n)

    def py(value: float) -> float:
        return oy + PANEL_H - 30 - (PANEL_H - 46) * ((value - lo) / (hi - lo))

    for step in range(5):
        value = lo + (hi - lo) * step / 4
        y = py(value)
        out.append(f'<line x1="{ox + 42}" y1="{y:.1f}" x2="{ox + PANEL_W - 20}" '
                   f'y2="{y:.1f}" stroke="#eef1f4"/>')
        out.append(f'<text x="{ox + 38}" y="{y + 4:.1f}" font-size="11" '
                   f'text-anchor="end" fill="#7b8794">{value:.2f}</text>')

    yref = py(reference)
    out.append(f'<line x1="{ox + 42}" y1="{yref:.1f}" x2="{ox + PANEL_W - 20}" '
               f'y2="{yref:.1f}" stroke="#e0245e" stroke-width="1.4" '
               f'stroke-dasharray="6 4"/>')
    out.append(f'<text x="{ox + PANEL_W - 22}" y="{yref - 6:.1f}" font-size="11" '
               f'text-anchor="end" fill="#e0245e">{html.escape(ref_label)}</text>')

    # Confidence-interval whiskers on the two judged measures only — the
    # structural panels are deterministic given the answers and carry no
    # sampling error, so a whisker there would imply a precision that is not
    # what those numbers are uncertain about.
    if key in WHISKERS and whiskers:
        lo_key, hi_key = WHISKERS[key]
        for i, row in enumerate(rows):
            ci_lo, ci_hi = number(row, lo_key), number(row, hi_key)
            if ci_lo is None or ci_hi is None:
                continue
            x = px(i)
            out.append(f'<line x1="{x:.1f}" y1="{py(ci_lo):.1f}" x2="{x:.1f}" '
                       f'y2="{py(ci_hi):.1f}" stroke="#b8c1cc" '
                       f'stroke-width="{1.6 if radius > 3 else 1.0}"/>')

    best, best_points = None, []
    for i, (row, value) in enumerate(zip(rows, values)):
        if value is None:
            continue
        if higher is not None:
            best = value if best is None else (max(best, value) if higher
                                               else min(best, value))
            best_points.append((px(i), py(best)))
        colour = STAGE_COLOUR.get(row.get("stage", ""), "#9aa5b1")
        # Filled by the *primary* measure. A variant that cleared the arena
        # while losing support has not cleared its stage, and drawing it filled
        # would say it had.
        promoted = row.get("support_verdict") == "PROMOTE"
        out.append(f'<circle cx="{px(i):.1f}" cy="{py(value):.1f}" '
                   f'r="{radius * 1.35 if promoted else radius:.1f}" '
                   f'fill="{colour}" '
                   f'fill-opacity="{1.0 if promoted else 0.75}" '
                   f'stroke="#ffffff" stroke-width="{1.2 if radius > 3 else 0.6}"/>')
    if len(best_points) > 1:
        path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}"
                        for i, (x, y) in enumerate(best_points))
        out.append(f'<path d="{path}" fill="none" stroke="#1f9d55" '
                   f'stroke-width="1.8" stroke-opacity="0.85"/>')
    out.append("</g>")

    # Variant index ticks, thinned as the run grows — without them a 40-row
    # chart shows a shape with no way back to which variant made it.
    for i in range(0, len(rows), stride):
        out.append(f'<text x="{px(i):.1f}" y="{oy + PANEL_H - 16:.1f}" '
                   f'font-size="9" text-anchor="middle" fill="#9aa5b1">{i + 1}</text>')
    out.append(f'<text x="{ox + PANEL_W / 2}" y="{oy + PANEL_H - 4}" '
               f'font-size="11" text-anchor="middle" fill="#7b8794">'
               f'variant, in the order it was scored</text>')
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--judge", help="plot only this judge's rows "
                                        "(default: whichever scored first)")
    args = parser.parse_args()

    rows, judge = for_judge(load(args.results), args.judge)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}" font-family="-apple-system,Segoe UI,'
             f'Helvetica,Arial,sans-serif">',
             f'<rect width="{W}" height="{H}" fill="#f7f8fa"/>',
             f'<text x="{PAD}" y="34" font-size="19" font-weight="700" '
             f'fill="#1f2933">aus_agent prompt optimization</text>']
    if rows:
        subtitle = (f'{len(rows)} scored variants, judge {judge}; '
                    f'{sum(1 for r in rows if r.get("support_verdict") == "PROMOTE")} '
                    f'cleared their stage')
    else:
        subtitle = "no variants scored yet"
    parts.append(f'<text x="{PAD}" y="54" font-size="12.5" fill="#616e7c">'
                 f'{html.escape(subtitle)} &#183; filled markers cleared the '
                 f'stage &#183; whiskers are 95% bootstrap CI &#183; '
                 f'green line is running best</text>')

    for index, (key, title, reference, ref_label, higher) in enumerate(PANELS):
        x, y = index % 2, index // 2
        parts += panel(rows, key, title, reference, ref_label, higher,
                       PAD + x * (PANEL_W + PAD), 96 + y * (PANEL_H + PAD),
                       index)

    legend_y = H - 22
    for i, (stage, colour) in enumerate(STAGE_COLOUR.items()):
        cx = PAD + i * 150
        parts.append(f'<circle cx="{cx}" cy="{legend_y - 4}" r="5" fill="{colour}"/>')
        parts.append(f'<text x="{cx + 12}" y="{legend_y}" font-size="12" '
                     f'fill="#3e4c59">{stage}</text>')
    parts.append("</svg>")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {shown(args.out)} ({len(rows)} variants)")
    if update_leaderboard(rows, args.out.parent / "README.md"):
        print(f"refreshed the leaderboard block in "
              f"{shown(args.out.parent / "README.md")}")
    return 0


LEADERBOARD_COLUMNS = [
    ("stage", "stage"), ("variant", "variant"), ("topics", "n"),
    ("wr_first", "wR"), ("wr_delta", "wR &Delta;"), ("wr_lo", "lo"),
    ("wr_hi", "hi"), ("support_verdict", "support"),
    ("win_rate", "arena"), ("ci_lo", "lo"), ("ci_hi", "hi"),
    ("verdict", "arena verdict"),
    ("word_ratio", "len x base"), ("uncited_rate", "uncited"),
    ("cites_per_object", "cites/obj"), ("digits_per_1k", "digits/1k"),
]
BEGIN, END = "<!-- LEADERBOARD:BEGIN -->", "<!-- LEADERBOARD:END -->"


def update_leaderboard(rows: list[dict], readme: Path) -> bool:
    """Rewrite the delimited leaderboard block in the progress doc.

    Keeps the table and ``results.tsv`` from drifting: the loop regenerates
    both in one step, so a hand-maintained table can never be one iteration
    behind the data it claims to summarize.
    """
    if not readme.exists():
        return False
    text = readme.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        return False
    header = "| " + " | ".join(t for _, t in LEADERBOARD_COLUMNS) + " |"
    rule = "|" + "|".join("---" for _ in LEADERBOARD_COLUMNS) + "|"
    body = [header, rule]
    order = {"holdout59": 0, "confirm40": 1, "dev20": 2}
    for row in sorted(rows, key=lambda r: (order.get(r.get("stage", ""), 3),
                                           -float(r.get("wr_delta") or -9))):
        cells = []
        for key, _ in LEADERBOARD_COLUMNS:
            value = row.get(key, "")
            cells.append(f"**{value}**" if key == "wr_delta" else str(value))
        body.append("| " + " | ".join(cells) + " |")
    if not rows:
        body = ["_no variants scored yet_"]
    head, _, rest = text.partition(BEGIN)
    _, _, tail = rest.partition(END)
    readme.write_text(f"{head}{BEGIN}\n" + "\n".join(body) + f"\n{END}{tail}",
                      encoding="utf-8")
    return True


if __name__ == "__main__":
    raise SystemExit(main())
