#!/usr/bin/env python3
"""Static figures for the brief_revise_agent factorial hill-climb lab report.
Run: uv run --group notebook python worklogs/assets/2026-08-07-factor-analysis-report/make_figures.py
Reads evaluation-results/factorial/*/summary.json (gitignored/synced data
dir) -- figures + the numbers they were built from are committed; the raw
scores are not (per repo convention, data/ and evaluation-results/ stay out
of git).
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

REPO = Path(__file__).resolve().parents[3]
DIR = REPO / "evaluation-results/factorial"
OUT = Path(__file__).resolve().parent / "figures"
OUT.mkdir(exist_ok=True)

# Palette (dataviz skill reference/palette.md, light mode, used verbatim --
# no new hex chosen, so no re-validation needed).
BLUE = "#2a78d6"      # accent / slot 1
ORANGE = "#eb6834"    # slot 2
AQUA = "#1baf7a"       # slot 3
YELLOW = "#eda100"    # slot 4
MAGENTA = "#e87ba4"   # slot 5
GREEN = "#008300"     # slot 6 / status good
VIOLET = "#4a3aa7"    # slot 7
RED = "#e34948"       # slot 8 / status bad
MUTED = "#9a9a94"     # de-emphasis gray
GRID = "#e3e2dc"
TEXT = "#0b0b0b"
TEXT2 = "#52514e"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 11,
    "text.color": TEXT,
    "axes.edgecolor": GRID,
    "axes.labelcolor": TEXT2,
    "xtick.color": TEXT2,
    "ytick.color": TEXT2,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
})


def score(run_id: str) -> dict:
    return json.load(open(DIR / run_id / "summary.json"))


BASE = score("br-model-main-sol-exp15-b1")["overall_mean"]
NOISE = abs(score("br-replicate-sol-rerun-exp15")["overall_mean"] - BASE)

# ---------------------------------------------------------------------------
# Figure 1: per-cell overall standalone score, sorted, base cell emphasized.
# Form: emphasis (one series is the point, rest are context).
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
vals = [(label, score(rid)["overall_mean"]) for label, rid in cells]
vals.sort(key=lambda x: x[1])

fig, ax = plt.subplots(figsize=(8.5, 7.5))
colors = [BLUE if v == BASE else MUTED for _, v in vals]
y = range(len(vals))
bars = ax.barh(y, [v for _, v in vals], color=colors, height=0.62,
               edgecolor="none", zorder=3)
ax.set_yticks(list(y))
ax.set_yticklabels([label for label, _ in vals], fontsize=9.5)
ax.set_xlabel("Standalone rubric score (0–3 scale, gpt-5.6-terra judge)")
ax.set_xlim(0, 3)
ax.axvline(BASE, color=BLUE, linewidth=1, linestyle=(0, (2, 2)), zorder=2)
ax.text(BASE + 0.03, len(vals) - 0.3, f"base = {BASE:.3f}",
       color=BLUE, fontsize=9, va="center")
for i, (label, v) in enumerate(vals):
    ax.text(v + 0.04, i, f"{v:.3f}", va="center", fontsize=8.5, color=TEXT2)
ax.grid(axis="y", visible=False)
ax.set_title("All 21 scored cells — standalone rubric overall score",
            fontsize=12.5, color=TEXT, loc="left", pad=12)
fig.tight_layout()
fig.savefig(OUT / "fig1_all_cells.pdf")
plt.close(fig)

# ---------------------------------------------------------------------------
# Figure 2: factor-effect dot plot, grouped by factor, vs base + noise band.
# Form: diverging-from-baseline / Cleveland dot plot, categorical by group.
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

rows = []  # (group_label_or_None, point_label, effect, color)
for gname, color, points in groups:
    for i, (plabel, effect) in enumerate(points):
        rows.append((gname if i == 0 else None, plabel, effect, color, gname))
rows.reverse()

fig, ax = plt.subplots(figsize=(8.5, 6.5))
ax.axvspan(-NOISE, NOISE, color=GRID, alpha=0.7, zorder=1,
          label=f"noise band (±{NOISE:.3f})")
ax.axvline(0, color=TEXT2, linewidth=1, zorder=2)

y = range(len(rows))
for i, (_, plabel, effect, color, gname) in enumerate(rows):
    ax.scatter([effect], [i], color=color, s=70, zorder=4,
              edgecolor="white", linewidth=0.8)
    ax.plot([0, effect], [i, i], color=color, linewidth=1.4, zorder=3, alpha=0.55)
ax.set_yticks(list(y))
ax.set_yticklabels([f"{gname}: {plabel}" if gname else f"    {plabel}"
                    for _, plabel, _, _, gname in rows], fontsize=9)
ax.set_xlabel("Effect on standalone overall score vs. base cell (2.267)")
ax.set_title("Factor effects — dominant driver is generator-model choice",
            fontsize=12.5, color=TEXT, loc="left", pad=12)
ax.grid(axis="y", visible=False)
ax.legend(loc="lower left", frameon=False, fontsize=9)
fig.tight_layout()
fig.savefig(OUT / "fig2_factor_effects.pdf")
plt.close(fig)

# ---------------------------------------------------------------------------
# Figure 3: cell x axis heatmap (sequential blue).
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
import numpy as np
matrix = np.array([[score(rid)["axis_means"].get(a, np.nan) for a in axes_order]
                   for _, rid in heat_cells])

fig, ax = plt.subplots(figsize=(8.5, 4.8))
im = ax.imshow(matrix, cmap="Blues", vmin=0, vmax=2, aspect="auto")
ax.set_xticks(range(len(axes_order)))
ax.set_xticklabels([a.replace(" & ", " &\n").replace(" ", "\n", 1) if len(a) > 18
                    else a for a in axes_order], fontsize=8.5)
ax.set_yticks(range(len(heat_cells)))
ax.set_yticklabels([label for label, _ in heat_cells], fontsize=9.5)
for i in range(matrix.shape[0]):
    for j in range(matrix.shape[1]):
        v = matrix[i, j]
        color = "white" if v > 1.1 else TEXT
        ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8.5, color=color)
ax.set_xticks(np.arange(-0.5, len(axes_order), 1), minor=True)
ax.set_yticks(np.arange(-0.5, len(heat_cells), 1), minor=True)
ax.grid(which="minor", color="white", linewidth=2)
ax.grid(which="major", visible=False)
ax.tick_params(which="minor", bottom=False, left=False)
cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
cbar.set_label("axis mean (0–2)", fontsize=9, color=TEXT2)
ax.set_title("Rubric axis scores by cell — References & Citation Quality is "
            "weak everywhere", fontsize=12, color=TEXT, loc="left", pad=12)
fig.tight_layout()
fig.savefig(OUT / "fig3_axis_heatmap.pdf")
plt.close(fig)

# ---------------------------------------------------------------------------
# Figure 4: arena result, status-colored 100% stacked bar.
# ---------------------------------------------------------------------------
arena = json.load(open(DIR / "arena-sol-vs-aus-agent-v2-exp15/summary.json")) \
    if (DIR / "arena-sol-vs-aus-agent-v2-exp15/summary.json").exists() else None

fig, ax = plt.subplots(figsize=(7.2, 2.0))
# clean 15-topic breakdown from the worklog: 4W-7L-4A for brief_revise_agent
win, loss, amb = 4, 7, 4
total = win + loss + amb
left = 0
for label, count, color in [("brief_revise_agent wins", win, GREEN),
                            ("ambiguous (order flips)", amb, MUTED),
                            ("aus_agent_v2 wins", loss, RED)]:
    frac = count / total
    ax.barh([0], [frac], left=left, color=color, height=0.55, edgecolor="white",
           linewidth=1.5)
    if frac > 0.06:
        ax.text(left + frac / 2, 0, f"{count}", ha="center", va="center",
               color="white", fontsize=11, fontweight="bold")
    left += frac
ax.set_xlim(0, 1)
ax.set_ylim(-0.6, 0.6)
ax.set_yticks([])
ax.set_xticks([])
for spine in ax.spines.values():
    spine.set_visible(False)
ax.set_title("Arena, base cell vs aus_agent_v2 — 15 topics, clean "
            "per-topic agreement", fontsize=11.5, color=TEXT, loc="left", pad=10)
handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (GREEN, MUTED, RED)]
ax.legend(handles, ["brief_revise_agent wins (4)", "ambiguous (4)",
                    "aus_agent_v2 wins (7)"],
         loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=3, frameon=False,
         fontsize=9)
fig.tight_layout()
fig.savefig(OUT / "fig4_arena.pdf")
plt.close(fig)

# ---------------------------------------------------------------------------
# Figure 6: second arena result -- hybrid-alone vs aus_agent_v2 (WORSE than
# the base cell's own arena result, despite scoring higher on standalone).
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(7.2, 2.0))
win2, loss2, amb2 = 2, 7, 6
total2 = win2 + loss2 + amb2
left = 0
for label, count, color in [("brief_revise_agent wins", win2, GREEN),
                            ("ambiguous (order flips)", amb2, MUTED),
                            ("aus_agent_v2 wins", loss2, RED)]:
    frac = count / total2
    ax.barh([0], [frac], left=left, color=color, height=0.55, edgecolor="white",
           linewidth=1.5)
    if frac > 0.06:
        ax.text(left + frac / 2, 0, f"{count}", ha="center", va="center",
               color="white", fontsize=11, fontweight="bold")
    left += frac
ax.set_xlim(0, 1)
ax.set_ylim(-0.6, 0.6)
ax.set_yticks([])
ax.set_xticks([])
for spine in ax.spines.values():
    spine.set_visible(False)
ax.set_title("Arena, hybrid-alone vs aus_agent_v2 — worse than the base cell",
            fontsize=11.5, color=TEXT, loc="left", pad=10)
handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (GREEN, MUTED, RED)]
ax.legend(handles, ["brief_revise_agent wins (2)", "ambiguous (6)",
                    "aus_agent_v2 wins (7)"],
         loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=3, frameon=False,
         fontsize=9)
fig.tight_layout()
fig.savefig(OUT / "fig6_arena_hybrid.pdf")
plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 5: PRODUCTION running cost -- $/topic vs standalone score, one
# point per component/level (cost_analysis.py, judging excluded --
# per-topic generation cost only, what the deployed system actually pays).
# Form: scatter (two independent-scale magnitudes -> not a dual-axis
# chart), categorical color per component family, base cell emphasized.
# ---------------------------------------------------------------------------
cost_data = json.loads((Path(__file__).resolve().parent / "cost_by_run.json").read_text())
base_cost = cost_data["base_cost_per_topic_usd"]
base_score = cost_data["base_score"]

COMPONENT_COLORS = {
    "generator_model": BLUE, "adjacent_page_fetch": ORANGE,
    "search_preview_chars": AQUA, "stage_search_results": AQUA,
    "judge_relevance_tool": AQUA, "commit_release": AQUA,
    "judge_relevance+commit_release": AQUA, "retrieval_engine_set": RED,
    "brief_analyst_model": YELLOW, "closure_critic": VIOLET,
}

fig, ax = plt.subplots(figsize=(9, 6.8))
ax.axhline(base_score, color=GRID, linewidth=1, zorder=1)
ax.axvline(base_cost, color=GRID, linewidth=1, zorder=1)

scored = [r for r in cost_data["rows"] if r["score"] is not None]
# The 5 generator_model points are widely separated (the real story: model
# choice dominates both axes) -- direct-label those plus the base star and
# the one standout structural point (hybrid: cheaper AND better). Every
# other structural/harness point clusters tightly near the base (that
# clustering IS the finding: none of them move either axis much) --
# leaving 14 of them unlabeled avoids the collision a full label set had;
# their exact $/topic and score are in the accompanying table instead.
DIRECT_LABEL = {"sol (BASE)", "terra", "gpt-oss-120b", "qwen", "luna",
                "hybrid only"}
FAMILY_LEGEND = [
    ("generator_model", BLUE, "generator model"),
    ("adjacent_page_fetch", ORANGE, "adjacent-page fetch"),
    ("retrieval_engine_set", RED, "retrieval engine set"),
    ("brief_analyst_model", YELLOW, "brief-analyst model"),
    ("closure_critic", VIOLET, "closure critic"),
    ("__harness__", AQUA, "other agent_harness toggle"),
]
OFFSETS = {"sol (BASE)": (12, 6), "terra": (10, -16), "gpt-oss-120b": (10, -16),
          "qwen": (10, -16), "luna": (-58, 10), "hybrid only": (-70, 14)}
for r in scored:
    is_harness = r["component"] in {"search_preview_chars", "stage_search_results",
                                    "judge_relevance_tool", "commit_release",
                                    "judge_relevance+commit_release"}
    color = AQUA if is_harness else COMPONENT_COLORS.get(r["component"], MUTED)
    is_base = "BASE" in r["level"]
    x, y = r["cost_per_topic_usd"], r["score"]
    ax.scatter([x], [y], s=190 if is_base else 90,
              color=color, edgecolor="white", linewidth=1.1,
              zorder=4 if is_base else 3, marker="*" if is_base else "o")
    label = r["level"].split(" (default")[0]
    # "gpt-oss-120b"/"qwen"/"terra" also appear as brief_analyst_model
    # sweep levels (same text, different component) -- restrict direct
    # labels to the generator_model family (+ the one retrieval_engine_set
    # standout) so two same-text points never collide.
    if label in DIRECT_LABEL and r["component"] in ("generator_model", "retrieval_engine_set"):
        dx, dy = OFFSETS.get(label, (10, 8))
        ax.annotate(label, (x, y), textcoords="offset points", xytext=(dx, dy),
                   fontsize=9, color=TEXT, zorder=5,
                   arrowprops=dict(arrowstyle="-", color=MUTED, linewidth=0.6,
                                   shrinkA=4, shrinkB=4))
ax.annotate("14 structural/harness cells cluster here\n(all within $0.4/topic "
           "and 0.13 score of base --\nsee accompanying table for exact values)",
           (1.15, 2.13), textcoords="offset points", xytext=(-40, -55),
           fontsize=8, color=TEXT2, ha="left",
           arrowprops=dict(arrowstyle="-", color=MUTED, linewidth=0.6))
handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=c,
                      markersize=8, label=lbl) for _, c, lbl in FAMILY_LEGEND]
ax.legend(handles=handles, loc="lower right", frameon=False, fontsize=8)
ax.set_xlabel("Production running cost, $/topic (generation only, no judging — estimate, see report caveat)")
ax.set_ylabel("Standalone rubric score (0–3)")
ax.set_title("Component running cost vs. score — cheaper is left, better is up",
            fontsize=12.3, color=TEXT, loc="left", pad=12)
ax.set_ylim(1.05, 2.55)
fig.tight_layout()
fig.savefig(OUT / "fig5_cost_effectiveness.pdf")
plt.close(fig)

print("wrote figures to", OUT)
for p in sorted(OUT.glob("*.pdf")):
    print(" -", p.name)
