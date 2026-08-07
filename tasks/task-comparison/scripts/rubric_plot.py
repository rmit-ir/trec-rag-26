#!/usr/bin/env python3
"""Render ``rubric-results.jsonl`` to ``docs/auto-optimize/progress.svg``.

Six panels, stdlib only (no matplotlib to fail mid-loop). What it shows is
chosen so the chart cannot flatter the run:

- **The goal line and the noise band are drawn together.** Every arm so far
  moves the mean by ~0.014 against a judge whose per-topic spread is ~0.07;
  plotting the effects without the band they sit inside would show a rising
  staircase that is mostly resampling noise. The shaded band is the smallest
  effect this instrument can resolve, so a bar inside it means "cannot tell".
- **The two safety conditions get their own panels**, because they are gates
  rather than scores: a variant that lifts the mean while committing more
  serious errors has not improved.
- **Spend is plotted against the cap**, so the budget is visible next to the
  progress it bought.

    uv run --no-project python tasks/task-comparison/scripts/rubric_plot.py
"""
from __future__ import annotations

import argparse
import html
import json
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "docs/auto-optimize/rubric-results.jsonl"
OUT = ROOT / "docs/auto-optimize/progress.svg"
GOAL, FLOOR, BUDGET = 0.80, 0.65, 300.0
# One panel per row, full bleed. Two columns worked at 6 arms and stopped
# working at 15: bar labels collided with each other and value labels collided
# with the bars above them. A chart you have to squint at gets skimmed, and a
# skimmed chart is where "every bar is inside the noise band" goes unnoticed.
W, PAD, PANEL_H = 1360, 56, 208
PANEL_W = W - 2 * PAD
H = 124 + 6 * (PANEL_H + 68) + 30
CONTROL = "v2l-default"
# Only the current instrument and the current harness era are comparable.
# Rows from before the UTC/locale fix, or graded by a different judge, are
# real data but belong to a different experiment -- plotting them on one axis
# invites exactly the comparison that is invalid.
JUDGE = "gpt-5.6-sol"
ERA_PREFIXES = ("v2l-", "sol-", "v2-")
COMBO = "#c2410c"
ARM = "#2f6fb5"
BASE = "#9aa5b1"


def load(path: Path, judge: str = JUDGE, all_eras: bool = False) -> list[dict]:
    if not path.exists():
        return []
    seen: dict[str, dict] = {}
    dropped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("judge") != judge or (
                not all_eras and not row["variant"].startswith(ERA_PREFIXES)):
            dropped += 1
            continue
        seen[row["variant"]] = row              # last write wins
    if dropped:
        print(f"  omitted {dropped} row(s) from an earlier judge or harness era "
              f"(pass --all-eras to include)")
    order = ([seen[CONTROL]] if CONTROL in seen else [])
    order += [r for v, r in seen.items() if v != CONTROL]
    return order


def colour(row: dict) -> str:
    if row["variant"] == CONTROL:
        return BASE
    return COMBO if row["variant"].startswith("combo") else ARM


def bars(rows, key, title, ox, oy, *, goal=None, band=None, lower_better=False,
         fmt="{:.3f}", axis_max=None, ceiling=None, ceiling_label="",
         subtitle=""):
    """``goal`` is a target to reach; ``ceiling`` is a limit not to cross.

    They are drawn differently on purpose. An earlier version passed the
    1,024-word cap as ``goal``, which drew it as a dashed target and shaded a
    bar "good" only once it REACHED the cap -- i.e. the chart rewarded padding
    toward the limit. Length is a constraint, never an objective.
    """
    out = [f'<rect x="{ox}" y="{oy}" width="{PANEL_W}" height="{PANEL_H}" '
           f'fill="#ffffff" stroke="#d5dae1"/>',
           f'<text x="{ox}" y="{oy - 26}" font-size="14.5" font-weight="600" '
           f'fill="#1f2933">{html.escape(title)}</text>']
    if subtitle:
        out.append(f'<text x="{ox}" y="{oy - 10}" font-size="11" '
                   f'fill="#7b8794">{html.escape(subtitle)}</text>')
    values = [row.get(key) for row in rows]
    numeric = [v for v in values if isinstance(v, (int, float))]
    top = axis_max if axis_max is not None else max(
        numeric + ([goal] if goal else []) + [1e-9]) * 1.15
    n = max(len(rows), 1)
    plot_h, base_y = PANEL_H - 60, oy + PANEL_H - 40
    slot = (PANEL_W - 70) / n

    def y(v):
        return base_y - plot_h * (min(v, top) / top if top else 0)

    for step in range(4):
        v = top * step / 3
        out.append(f'<line x1="{ox+44}" y1="{y(v):.1f}" x2="{ox+PANEL_W-14}" '
                   f'y2="{y(v):.1f}" stroke="#eef1f4"/>')
        out.append(f'<text x="{ox+40}" y="{y(v)+4:.1f}" font-size="10.5" '
                   f'text-anchor="end" fill="#7b8794">{fmt.format(v)}</text>')

    # The band a result must escape to mean anything.
    if band:
        lo, hi = band
        out.append(f'<rect x="{ox+44}" y="{y(hi):.1f}" width="{PANEL_W-58}" '
                   f'height="{max(1.0, y(lo)-y(hi)):.1f}" fill="#e0245e" '
                   f'fill-opacity="0.07"/>')
    if goal is not None:
        out.append(f'<line x1="{ox+44}" y1="{y(goal):.1f}" x2="{ox+PANEL_W-14}" '
                   f'y2="{y(goal):.1f}" stroke="#e0245e" stroke-width="1.5" '
                   f'stroke-dasharray="6 4"/>')
        out.append(f'<text x="{ox+PANEL_W-16}" y="{y(goal)-5:.1f}" font-size="10.5" '
                   f'text-anchor="end" fill="#e0245e">goal {fmt.format(goal)}</text>')
    if ceiling is not None:
        # Solid, with the forbidden region shaded above it. Nothing about this
        # should read as somewhere to get to.
        out.append(f'<rect x="{ox+44}" y="{oy+8:.1f}" width="{PANEL_W-58}" '
                   f'height="{max(0.0, y(ceiling)-oy-8):.1f}" fill="#e0245e" '
                   f'fill-opacity="0.06"/>')
        out.append(f'<line x1="{ox+44}" y1="{y(ceiling):.1f}" x2="{ox+PANEL_W-14}" '
                   f'y2="{y(ceiling):.1f}" stroke="#e0245e" stroke-width="2"/>')
        out.append(f'<text x="{ox+PANEL_W-16}" y="{y(ceiling)-6:.1f}" font-size="10.5" '
                   f'text-anchor="end" fill="#e0245e">'
                   f'{html.escape(ceiling_label)}</text>')

    show_values = len(rows) <= 20
    for i, (row, v) in enumerate(zip(rows, values)):
        if not isinstance(v, (int, float)):
            continue
        x = ox + 58 + i * slot
        bw = max(8.0, slot * 0.62)
        if ceiling is not None:
            good = v <= ceiling            # compliant, not "close to the limit"
        else:
            good = (v <= (goal or 0)) if lower_better else (v >= (goal or 1e9))
        tooltip = (f'{row["variant"]} | n={row.get("topics", "?")} | '
                   f'{key}={fmt.format(v)}')
        out.append(f'<rect x="{x:.1f}" y="{y(v):.1f}" width="{bw:.1f}" '
                   f'height="{max(1.0, base_y - y(v)):.1f}" fill="{colour(row)}" '
                   f'fill-opacity="{1.0 if good else 0.8}"><title>'
                   f'{html.escape(tooltip)}</title></rect>')
        if show_values:
            out.append(f'<text x="{x + bw/2:.1f}" y="{y(v)-4:.1f}" font-size="10" '
                       f'text-anchor="middle" fill="#3e4c59">{fmt.format(v)}</text>')
        # Long variant names stopped fitting once the log reached 39 arms.
        # A compact arm-id/topic-count label remains legible; the full name and
        # value are available as the SVG hover title on every bar.
        label = f'{i + 1}·{row.get("topics", "?")}'
        out.append(f'<text x="{x + bw/2:.1f}" y="{base_y+15:.1f}" font-size="8.5" '
                   f'text-anchor="middle" fill="#5c6b7a">'
                   f'{html.escape(label)}</text>')
    return out


def axis_panel(rows, ox, oy):
    """Per-axis profile: control vs the best arm. Shows WHERE the gap is."""
    out = [f'<rect x="{ox}" y="{oy}" width="{PANEL_W}" height="{PANEL_H}" '
           f'fill="#ffffff" stroke="#d5dae1"/>',
           f'<text x="{ox}" y="{oy - 26}" font-size="14.5" font-weight="600" '
           f'fill="#1f2933">Per-axis score</text>',
           f'<text x="{ox}" y="{oy - 10}" font-size="11" fill="#7b8794">'
           f'the six rubric axes, worst first. Explicit + Implicit carry 77% of '
           f'all weight; References carries 2.2%.</text>']
    if not rows:
        return out
    full_rows = [row for row in rows if row.get("topics") == 30]
    comparison_rows = full_rows or rows
    control = next((r for r in comparison_rows if r["variant"] == CONTROL),
                   comparison_rows[0])
    best = max(comparison_rows, key=lambda r: r.get("mean_score", -9))
    axes = [a for a in control.get("axis", {}) if a != "Miscellaneous"]
    axes.sort(key=lambda a: control["axis"][a])
    row_h = (PANEL_H - 40) / max(len(axes), 1)
    for i, a in enumerate(axes):
        yy = oy + 22 + i * row_h
        c, b = control["axis"].get(a, 0), best.get("axis", {}).get(a, 0)
        out.append(f'<text x="{ox+12}" y="{yy+9:.1f}" font-size="11.5" '
                   f'fill="#3e4c59">{html.escape(a)}</text>')
        x0, width = ox + 220, PANEL_W - 300
        out.append(f'<rect x="{x0}" y="{yy:.1f}" width="{width*c:.1f}" '
                   f'height="{row_h*0.34:.1f}" fill="{BASE}"/>')
        out.append(f'<rect x="{x0}" y="{yy+row_h*0.38:.1f}" '
                   f'width="{width*b:.1f}" height="{row_h*0.34:.1f}" fill="{ARM}"/>')
        out.append(f'<text x="{x0+width+6}" y="{yy+row_h*0.5:.1f}" font-size="9.5" '
                   f'fill="#7b8794">{c:.2f}/{b:.2f}</text>')
    out.append(f'<text x="{ox+8}" y="{oy+PANEL_H-8}" font-size="10" fill="#7b8794">'
               f'grey = {html.escape(CONTROL)}, blue = '
               f'{html.escape(best["variant"])}</text>')
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", type=Path, default=RESULTS)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--all-eras", action="store_true",
                    help="include pre-UTC-fix rows (not comparable)")
    ap.add_argument("--spent", type=float, default=None,
                    help="USD spent so far (from goal_status.py)")
    a = ap.parse_args()
    rows = load(a.results, all_eras=a.all_eras)

    for row in rows:
        topic_count = max(1, int(row.get("topics") or 1))
        row["below_rate"] = row.get("topics_below_065", 0) / topic_count
        row["severe_rate"] = row.get("severe_penalties", 0) / topic_count

    full_rows = [row for row in rows if row.get("topics") == 30]
    probe_rows = [row for row in rows if row.get("topics") != 30]
    noise_rows = full_rows or rows
    noise = st.mean([r["judge_spread"] for r in noise_rows
                     if r.get("judge_spread")]) if noise_rows else 0.0
    control = next((r for r in rows if r["variant"] == CONTROL), None)
    base = control["mean_score"] if control else 0.0
    # Resolution floor on the 30-topic mean: per-topic spread, averaged over
    # `repeats` gradings and then over 30 topics.
    reps = max((r.get("repeats") or 1) for r in rows) if rows else 1
    floor_effect = noise / (reps ** 0.5) / (30 ** 0.5) * 1.96 * 3

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}" font-family="-apple-system,Segoe UI,'
             f'Helvetica,Arial,sans-serif">',
             f'<rect width="{W}" height="{H}" fill="#f7f8fa"/>',
             f'<text x="{PAD}" y="34" font-size="19" font-weight="700" '
             f'fill="#1f2933">aus_agent rubric optimization — full 30-topic runs only</text>',
             f'<text x="{PAD}" y="55" font-size="12.5" fill="#616e7c">'
             f'{len(full_rows)} comparable full-30 arms &#183; {len(probe_rows)} '
             f'subset diagnostics excluded from every bar &#183; label = arm number·30 '
             f'&#183; hover for full name</text>',
             f'<text x="{PAD}" y="74" font-size="12.5" fill="#616e7c">'
             f'best comparable full-30 '
             f'{max((r["mean_score"] for r in full_rows), default=0):.4f} '
             f'&#183; goal {GOAL:.2f} &#183; control {base:.4f}</text>']

    panels = [
        ("mean_score", "Mean weighted rubric score", dict(
            goal=GOAL, band=(base - floor_effect, base + floor_effect),
            subtitle="Only complete 30-topic runs appear here; subset gates are "
                     "diagnostics, never leaderboard scores. Verdict is "
                     "1 satisfied / 0.5 partial / 0 not. Penalty criteria "
                     "subtract when satisfied.")),
        ("below_rate", "Share of topics below 0.65", dict(
            goal=0, lower_better=True, fmt="{:.0%}", axis_max=1,
            subtitle="fraction of the same 30 dev topics below the required "
                     "per-topic floor")),
        ("severe_rate", "Serious errors per evaluated topic", dict(
            goal=0, lower_better=True, fmt="{:.0%}", axis_max=1,
            subtitle="weight 4-5 penalties the judge marked satisfied, "
                     "i.e. the answer did the bad thing: misdefined a theorem, "
                     "cited nonexistent work, gave clinical advice, contradicted "
                     "the source; normalized by topic count.")),
        ("mean_words", "Answer length", dict(
            ceiling=1024, ceiling_label="1,024-word limit",
            fmt="{:.0f}", axis_max=1100,
            subtitle="mean words across answer[].text per topic. The track "
                     "caps a response at 1,024; per-topic maxima run "
                     "1003-1022.")),
    ]
    for i, (key, title, kw) in enumerate(panels):
        parts += bars(full_rows, key, title, PAD,
                      124 + i * (PANEL_H + 68), **kw)
    parts += axis_panel(full_rows, PAD, 124 + 4 * (PANEL_H + 68))

    ox, oy = PAD, 124 + 5 * (PANEL_H + 68)
    parts.append(f'<rect x="{ox}" y="{oy}" width="{PANEL_W}" height="{PANEL_H}" '
                 f'fill="#ffffff" stroke="#d5dae1"/>')
    parts.append(f'<text x="{ox}" y="{oy-26}" font-size="14.5" font-weight="600" '
                 f'fill="#1f2933">Budget</text>')
    parts.append(f'<text x="{ox}" y="{oy-10}" font-size="11" fill="#7b8794">'
                 f'Optimization-loop generation and judging spend, priced '
                 f'from recorded token counts</text>')
    spent = a.spent if a.spent is not None else 0.0
    used = spent / BUDGET
    frac = min(used, 1.0)
    budget_fill = "#e0245e" if used >= 1 else "#1f9d55"
    parts.append(f'<rect x="{ox+20}" y="{oy+52}" width="{PANEL_W-40}" height="34" '
                 f'fill="#eef1f4"/>')
    parts.append(f'<rect x="{ox+20}" y="{oy+52}" width="{(PANEL_W-40)*frac:.1f}" '
                 f'height="34" fill="{budget_fill}"/>')
    parts.append(f'<text x="{ox+20}" y="{oy+112}" font-size="14" fill="#3e4c59">'
                 f'${spent:.2f} of ${BUDGET:.0f} ({used:.1%})</text>')
    parts.append(f'<text x="{ox+20}" y="{oy+136}" font-size="12" fill="#7b8794">'
                 f'luna generation $3.45/arm &#183; sol generation $31.88/arm '
                 f'(9x) &#183; sol grading ~$3.40/arm</text>')
    parts.append("</svg>")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {a.out} ({len(rows)} arms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
