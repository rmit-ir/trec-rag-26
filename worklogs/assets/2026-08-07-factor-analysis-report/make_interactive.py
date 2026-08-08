#!/usr/bin/env python3
"""Interactive (Plotly) mirrors of make_figures.py's 4 static PDF figures --
same data, same palette, hover tooltips added (the dataviz skill's default
for anything actually interactive; the static PDF figures skip this since a
printed page can't act on it). Self-contained HTML (plotly.js inlined, no
CDN/network needed to view).

Run: uv run --group notebook python worklogs/assets/2026-08-07-factor-analysis-report/make_interactive.py
"""
from __future__ import annotations

import json
from pathlib import Path

import plotly.graph_objects as go

REPO = Path(__file__).resolve().parents[3]
DIR = REPO / "evaluation-results/factorial"
OUT = Path(__file__).resolve().parent / "interactive"
OUT.mkdir(exist_ok=True)

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
VIOLET = "#4a3aa7"
GREEN = "#008300"
RED = "#e34948"
MUTED = "#9a9a94"
GRID = "#e3e2dc"
TEXT2 = "#52514e"

TEMPLATE = go.layout.Template(
    layout=go.Layout(
        font=dict(family="Arial, sans-serif", size=13, color="#0b0b0b"),
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
        yaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
    )
)


def score(run_id: str) -> dict:
    return json.load(open(DIR / run_id / "summary.json"))


BASE = score("br-model-main-sol-exp15-b1")["overall_mean"]
NOISE = abs(score("br-replicate-sol-rerun-exp15")["overall_mean"] - BASE)

HTML_KW = dict(include_plotlyjs="inline", full_html=True, config={"displaylogo": False})

# ---------------------------------------------------------------------------
# Figure 1: all cells, sorted, hover shows run_id + delta vs base.
# ---------------------------------------------------------------------------
cells = [
    ("sol + round B  (BASE, BEST)", "br-model-main-sol-exp15-b1"),
    ("sol + commit_release", "br-hillclimb-sol-commitrelease-exp15"),
    ("sol + jrel + commit_release", "br-hillclimb-sol-jrelcommit-exp15"),
    ("sol + closure critic", "br-hillclimb-sol-closurecritic-exp15"),
    ("sol, adjacent-fetch OFF", "br-hillclimb-sol-adjoff-exp15"),
    ("sol + no_stage_search_results", "br-hillclimb-sol-nostage-exp15"),
    ("sol + judge_relevance_tool", "br-hillclimb-sol-jrel-exp15"),
    ("sol, rerun (same topics)", "br-replicate-sol-rerun-exp15"),
    ("sol + analyst=terra", "br-analystsweep-terra-exp15"),
    ("sol + analyst=gpt-oss-120b", "br-analystsweep-oss120b-exp15"),
    ("sol + analyst=qwen", "br-analystsweep-qwen-exp15"),
    ("luna, iteration-1 (old ref, no round B)", "brief-revise-iter1-exp15"),
    ("sol, new 15 topics", "br-replicate-sol-new15"),
    ("sol + search_preview_chars", "br-hillclimb-sol-preview-exp15"),
    ("sol + wider retrieval_engine_set", "br-hillclimb-sol-widerengines-exp15"),
    ("luna, new 15 topics", "br-replicate-luna-new15"),
    ("luna, current code (round B on)", "br-luna-current-code-exp15"),
    ("terra + round B", "br-model-main-terra-exp15-b1"),
    ("qwen + round B", "br-model-main-qwen-exp15-b1"),
    ("qwen, adjacent-fetch OFF", "br-divergent-anchor-qwen-adj0-k10-exp15"),
    ("gpt-oss-120b + round B", "br-model-main-oss120b-exp15-b1"),
    ("sol + engine=hybrid (best non-model)", "br-enginesweep-hybrid-exp15"),
    ("sol + engine=keyword", "br-enginesweep-keyword-exp15"),
    ("sol + engine=semantic", "br-enginesweep-semantic-exp15"),
    ("sol + engine=hybrid+HyDE", "br-enginesweep-hyde-exp15"),
    ("sol + best-of-4 ensemble", "br-ensemble-bestof4-exp15"),
]
vals = [(label, rid, score(rid)["overall_mean"]) for label, rid in cells]
vals.sort(key=lambda x: x[2])
colors = [BLUE if v == BASE else MUTED for _, _, v in vals]
customdata = [[rid, v - BASE] for _, rid, v in vals]

fig1 = go.Figure(go.Bar(
    x=[v for _, _, v in vals], y=[label for label, _, _ in vals], orientation="h",
    marker_color=colors, customdata=customdata,
    hovertemplate="<b>%{y}</b><br>run_id: %{customdata[0]}<br>"
                 "score: %{x:.3f}<br>vs base: %{customdata[1]:+.3f}<extra></extra>",
))
fig1.add_vline(x=BASE, line_dash="dash", line_color=BLUE,
               annotation_text=f"base = {BASE:.3f}", annotation_position="top right")
fig1.update_layout(
    template=TEMPLATE, title="All 21 scored cells — standalone rubric overall score",
    xaxis_title="Standalone rubric score (0–3 scale, gpt-5.6-terra judge)",
    xaxis_range=[0, 3], height=700, margin=dict(l=280),
)
fig1.write_html(OUT / "fig1_all_cells.html", **HTML_KW)

# ---------------------------------------------------------------------------
# Figure 2: factor effects, grouped, hover shows exact delta + verdict.
# ---------------------------------------------------------------------------
groups = [
    ("Generator model", BLUE, [
        ("terra", score("br-model-main-terra-exp15-b1")["overall_mean"] - BASE),
        ("qwen", score("br-model-main-qwen-exp15-b1")["overall_mean"] - BASE),
        ("gpt-oss-120b", score("br-model-main-oss120b-exp15-b1")["overall_mean"] - BASE),
        ("luna (fair, current code)", score("br-luna-current-code-exp15")["overall_mean"] - BASE),
    ]),
    ("Adjacent-page fetch OFF", ORANGE, [
        ("sol", score("br-hillclimb-sol-adjoff-exp15")["overall_mean"] - BASE),
        ("qwen", score("br-divergent-anchor-qwen-adj0-k10-exp15")["overall_mean"]
         - score("br-model-main-qwen-exp15-b1")["overall_mean"]),
    ]),
    ("Generic harness factor (sol)", AQUA, [
        ("search_preview_chars", score("br-hillclimb-sol-preview-exp15")["overall_mean"] - BASE),
        ("no_stage_search_results", score("br-hillclimb-sol-nostage-exp15")["overall_mean"] - BASE),
        ("judge_relevance_tool", score("br-hillclimb-sol-jrel-exp15")["overall_mean"] - BASE),
        ("commit_release", score("br-hillclimb-sol-commitrelease-exp15")["overall_mean"] - BASE),
        ("wider retrieval_engine_set", score("br-hillclimb-sol-widerengines-exp15")["overall_mean"] - BASE),
        ("jrel + commit_release", score("br-hillclimb-sol-jrelcommit-exp15")["overall_mean"] - BASE),
    ]),
    ("Brief-analyst model (sol)", YELLOW, [
        ("terra", score("br-analystsweep-terra-exp15")["overall_mean"] - BASE),
        ("gpt-oss-120b", score("br-analystsweep-oss120b-exp15")["overall_mean"] - BASE),
        ("qwen", score("br-analystsweep-qwen-exp15")["overall_mean"] - BASE),
    ]),
    ("Closure critic (sol)", VIOLET, [
        ("overclaim + contradiction check", score("br-hillclimb-sol-closurecritic-exp15")["overall_mean"] - BASE),
    ]),
    ("Search engine (sol, single-engine)", RED, [
        ("hybrid alone", score("br-enginesweep-hybrid-exp15")["overall_mean"] - BASE),
        ("keyword alone", score("br-enginesweep-keyword-exp15")["overall_mean"] - BASE),
        ("semantic alone", score("br-enginesweep-semantic-exp15")["overall_mean"] - BASE),
        ("hybrid + HyDE query style", score("br-enginesweep-hyde-exp15")["overall_mean"] - BASE),
    ]),
    ("Ensemble (sol)", GREEN, [
        ("best-of-4 selector", score("br-ensemble-bestof4-exp15")["overall_mean"] - BASE),
    ]),
]
rows = []
for gname, color, points in groups:
    for i, (plabel, effect) in enumerate(points):
        rows.append((gname, plabel, effect, color))
rows.reverse()
ylabels = [f"{g}: {p}" for g, p, _, _ in rows]

fig2 = go.Figure()
fig2.add_vrect(x0=-NOISE, x1=NOISE, fillcolor=GRID, opacity=0.7, line_width=0,
              annotation_text=f"noise band (±{NOISE:.3f})", annotation_position="bottom left")
for i, (gname, plabel, effect, color) in enumerate(rows):
    fig2.add_trace(go.Scatter(
        x=[0, effect], y=[ylabels[i], ylabels[i]], mode="lines",
        line=dict(color=color, width=1.4), opacity=0.55, showlegend=False,
        hoverinfo="skip"))
    signal = "beyond noise" if abs(effect) > NOISE else "noise-level"
    fig2.add_trace(go.Scatter(
        x=[effect], y=[ylabels[i]], mode="markers",
        marker=dict(color=color, size=13, line=dict(color="white", width=1)),
        showlegend=False,
        hovertemplate=f"<b>{gname}: {plabel}</b><br>effect: {effect:+.3f}<br>"
                     f"{signal}<extra></extra>"))
fig2.add_vline(x=0, line_color=TEXT2, line_width=1)
fig2.update_layout(
    template=TEMPLATE, title="Factor effects — dominant driver is generator-model choice",
    xaxis_title="Effect on standalone overall score vs. base cell (2.267)",
    height=650, margin=dict(l=320),
)
fig2.write_html(OUT / "fig2_factor_effects.html", **HTML_KW)

# ---------------------------------------------------------------------------
# Figure 3: axis heatmap, hover shows exact value.
# ---------------------------------------------------------------------------
axes_order = ["Communication Quality", "Explicit Criteria", "Implicit Criteria",
              "Instruction Following", "References & Citation Quality",
              "Synthesis of Information"]
heat_cells = [
    ("sol + round B (BASE)", "br-model-main-sol-exp15-b1"),
    ("terra + round B", "br-model-main-terra-exp15-b1"),
    ("qwen + round B", "br-model-main-qwen-exp15-b1"),
    ("gpt-oss-120b + round B", "br-model-main-oss120b-exp15-b1"),
    ("luna, current code", "br-luna-current-code-exp15"),
    ("luna, iteration-1 (old ref)", "brief-revise-iter1-exp15"),
    ("sol, adjacent-fetch OFF", "br-hillclimb-sol-adjoff-exp15"),
    ("sol + closure critic", "br-hillclimb-sol-closurecritic-exp15"),
    ("sol + commit_release", "br-hillclimb-sol-commitrelease-exp15"),
]
matrix = [[score(rid)["axis_means"].get(a) for a in axes_order] for _, rid in heat_cells]
fig3 = go.Figure(go.Heatmap(
    z=matrix, x=axes_order, y=[label for label, _ in heat_cells],
    colorscale="Blues", zmin=0, zmax=2,
    text=[[f"{v:.2f}" for v in row] for row in matrix], texttemplate="%{text}",
    hovertemplate="<b>%{y}</b><br>%{x}: %{z:.3f}<extra></extra>",
    colorbar=dict(title="axis mean<br>(0–2)"),
))
fig3.update_layout(
    template=TEMPLATE,
    title="Rubric axis scores by cell — References & Citation Quality is weak everywhere",
    height=520, margin=dict(l=200),
)
fig3.write_html(OUT / "fig3_axis_heatmap.html", **HTML_KW)

# ---------------------------------------------------------------------------
# Figure 4: arena, status-colored stacked bar.
# ---------------------------------------------------------------------------
win, loss, amb = 4, 7, 4
fig4 = go.Figure()
left = 0
for label, count, color in [("brief_revise_agent wins", win, GREEN),
                            ("ambiguous (order flips)", amb, MUTED),
                            ("aus_agent_v2 wins", loss, RED)]:
    fig4.add_trace(go.Bar(
        x=[count], y=["arena"], orientation="h", name=f"{label} ({count})",
        marker_color=color, base=left,
        hovertemplate=f"<b>{label}</b>: {count} of 15 topics<extra></extra>",
    ))
    left += count
fig4.update_layout(
    template=TEMPLATE, barmode="stack",
    title="Arena, base cell vs aus_agent_v2 — 15 topics, clean per-topic agreement",
    height=260, showlegend=True, legend=dict(orientation="h", y=-0.3),
    yaxis=dict(visible=False), xaxis=dict(visible=False),
)
fig4.write_html(OUT / "fig4_arena.html", **HTML_KW)

# ---------------------------------------------------------------------------
# Figure 5: cost-effectiveness scatter, hover shows n_cells + exact $/score.
# ---------------------------------------------------------------------------
cost_data = json.loads((Path(__file__).resolve().parent / "cost_by_run.json").read_text())
gs = cost_data["group_summary"]
GROUP_COLORS = {
    "generator_model": BLUE, "generator_model (BASE)": BLUE,
    "adjacent_fetch": ORANGE, "generic_harness": AQUA,
    "brief_analyst_model": YELLOW, "closure_critic": VIOLET,
    "replication": MUTED, "ensemble": GREEN, "ensemble_selector": GREEN,
    "search_engine": RED, "search_engine (BEST NON-MODEL)": RED,
    "block0_reused": MUTED, "baseline_reused": MUTED,
}
fig5 = go.Figure()
for g, row in gs.items():
    if row["avg_score"] is None:
        continue
    is_base = "BASE" in g
    fig5.add_trace(go.Scatter(
        x=[row["avg_cost_usd"]], y=[row["avg_score"]], mode="markers+text",
        text=[g.replace(" (BASE)", "").replace(" (BEST NON-MODEL)", "")],
        textposition="top center", showlegend=False,
        marker=dict(color=GROUP_COLORS.get(g, MUTED),
                   size=22 if is_base else 15,
                   symbol="star" if is_base else "circle",
                   line=dict(color="white", width=1.5)),
        hovertemplate=f"<b>{g}</b><br>n_cells: {row['n_cells']}<br>"
                     f"avg cost: ${row['avg_cost_usd']:.2f}<br>"
                     f"avg score: {row['avg_score']:.3f}<extra></extra>",
    ))
fig5.update_layout(
    template=TEMPLATE,
    title="Cost-effectiveness by factor group — model choice dominates both axes",
    xaxis_title="Average cost per 15-topic cell ($, estimate -- see report caveat)",
    yaxis_title="Average standalone rubric score (0–3)",
    height=650,
)
fig5.write_html(OUT / "fig5_cost_effectiveness.html", **HTML_KW)

print("wrote interactive figures to", OUT)
for p in sorted(OUT.glob("*.html")):
    print(" -", p.name)
