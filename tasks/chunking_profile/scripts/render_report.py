#!/usr/bin/env python3
"""Render chunking comparison reports and figures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns


STRATEGY_ORDER = [
    "first_512",
    "first_1024",
    "fixed_512_overlap_64",
    "fixed_1024_overlap_128",
    "paragraph_aware_512",
    "paragraph_aware_1024",
    "hybrid_short_whole_long_chunk",
]

SHORT_LABELS = {
    "first_512": "first 512",
    "first_1024": "first 1024",
    "fixed_512_overlap_64": "fixed 512+64",
    "fixed_1024_overlap_128": "fixed 1024+128",
    "paragraph_aware_512": "para 512",
    "paragraph_aware_1024": "para 1024",
    "hybrid_short_whole_long_chunk": "hybrid",
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--sample-summary", type=Path, required=True)
    ap.add_argument("--reports-dir", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--report-name", default="chunking_comparison.md")
    return ap.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fmt_num(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return f"{value:,}"
    if abs(value) >= 100:
        return f"{value:,.1f}"
    return f"{value:,.{digits}f}"


def fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{100.0 * value:.{digits}f}%"


def safe_get(dct: dict[str, Any] | None, *keys: str) -> Any:
    cur: Any = dct
    for key in keys:
        if cur is None or key not in cur:
            return None
        cur = cur[key]
    return cur


def strategy_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name in STRATEGY_ORDER:
        if name not in summary["strategies"]:
            continue
        overall = summary["strategies"][name]["overall"]
        rows.append({
            "strategy": name,
            "label": SHORT_LABELS[name],
            "chunks_per_doc_mean": overall["chunks_per_doc_mean"],
            "chunks_per_doc_p95": safe_get(overall, "chunks_per_doc_percentiles", "p95"),
            "tokens_per_chunk_p50": safe_get(overall, "tokens_per_chunk_percentiles", "p50"),
            "tokens_per_chunk_p95": safe_get(overall, "tokens_per_chunk_percentiles", "p95"),
            "retained_token_rate": overall["retained_token_rate"],
            "truncation_rate": overall["truncation_rate"],
            "chunk_token_multiplier": overall["chunk_token_multiplier"],
            "overlap_overhead_rate": overall["overlap_overhead_rate"],
            "empty_or_tiny_chunk_rate": overall["empty_or_tiny_chunk_rate"],
        })
    return rows


def plot_bar(rows: list[dict[str, Any]], key: str, ylabel: str, title: str, path: Path, pct: bool = False) -> None:
    labels = [r["label"] for r in rows]
    values = [float(r[key]) for r in rows]
    sns.set_theme(style="whitegrid", context="talk")
    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=160)
    colors = sns.color_palette("Set2", n_colors=len(values))
    ax.bar(labels, values, color=colors)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.tick_params(axis="x", labelrotation=25)
    if pct:
        ax.set_ylim(0, max(values) * 1.25 if values else 1)
        ax.yaxis.set_major_formatter(lambda x, _pos: f"{100*x:.0f}%")
    for i, value in enumerate(values):
        label = fmt_pct(value, 1) if pct else fmt_num(value, 2)
        ax.text(i, value, label, ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_chunks_mean_p95(rows: list[dict[str, Any]], path: Path) -> None:
    labels = [r["label"] for r in rows]
    mean_values = [float(r["chunks_per_doc_mean"]) for r in rows]
    p95_values = [float(r["chunks_per_doc_p95"] or 0) for r in rows]
    x = np.arange(len(labels))
    width = 0.38
    sns.set_theme(style="whitegrid", context="talk")
    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=160)
    ax.bar(x - width / 2, mean_values, width, label="mean", color="#6BAED6")
    ax.bar(x + width / 2, p95_values, width, label="p95", color="#FD8D3C")
    ax.set_title("Chunks Per Document")
    ax.set_ylabel("chunks/doc")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.legend()
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_long_doc(summary: dict[str, Any], path: Path) -> bool:
    rows = []
    for name in STRATEGY_ORDER:
        if name not in summary["strategies"]:
            continue
        long_doc = summary["strategies"][name].get("long_doc_behavior")
        if not long_doc:
            continue
        rows.append({
            "label": SHORT_LABELS[name],
            "chunks_p95": safe_get(long_doc, "chunks_per_doc_percentiles", "p95") or 0,
            "retained": long_doc["retained_token_rate"],
        })
    if not rows:
        return False
    labels = [r["label"] for r in rows]
    x = np.arange(len(labels))
    sns.set_theme(style="whitegrid", context="talk")
    fig, ax1 = plt.subplots(figsize=(11, 5.5), dpi=160)
    ax1.bar(x, [r["chunks_p95"] for r in rows], color="#9ECAE1", label="p95 chunks/doc")
    ax1.set_ylabel("p95 chunks/doc")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=25, ha="right")
    ax2 = ax1.twinx()
    ax2.plot(x, [r["retained"] for r in rows], color="#E6550D", marker="o", label="retained token rate")
    ax2.set_ylabel("retained token rate")
    ax2.yaxis.set_major_formatter(lambda val, _pos: f"{100*val:.0f}%")
    ax1.set_title("Long-Document Behavior (>8192 Approx Tokens)")
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper left")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return True


def render_markdown(summary: dict[str, Any], sample_summary: dict[str, Any], figure_dir: Path) -> str:
    rows = strategy_rows(summary)
    lines: list[str] = []
    lines.append("# ClimbMix Chunking Comparison")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"- Run ID: `{summary['run_id']}`.")
    lines.append(f"- Input docs: `{summary['input_docs']:,}`; processed docs: `{summary['processed_docs']:,}`.")
    lines.append(f"- Processed shards: `{summary['processed_shards']}`.")
    lines.append(f"- Sample mode: `{sample_summary.get('mode', 'unknown')}`; seed: `{sample_summary.get('seed', 'unknown')}`.")
    if summary.get("errors"):
        lines.append(f"- Errors: `{len(summary['errors'])}`. Inspect stats errors before using this report.")
    else:
        lines.append("- Errors: `0`.")
    lines.append("")
    lines.append("## Strategy Summary")
    lines.append("")
    lines.append("| strategy | chunks/doc mean | chunks/doc p95 | chunk tokens p50 | chunk tokens p95 | retained tokens | truncated docs | token multiplier | overlap overhead | tiny chunk rate |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        lines.append(
            "| "
            + " | ".join([
                f"`{row['strategy']}`",
                fmt_num(row["chunks_per_doc_mean"]),
                fmt_num(row["chunks_per_doc_p95"]),
                fmt_num(row["tokens_per_chunk_p50"]),
                fmt_num(row["tokens_per_chunk_p95"]),
                fmt_pct(row["retained_token_rate"]),
                fmt_pct(row["truncation_rate"]),
                fmt_num(row["chunk_token_multiplier"]),
                fmt_pct(row["overlap_overhead_rate"]),
                fmt_pct(row["empty_or_tiny_chunk_rate"]),
            ])
            + " |"
        )
    lines.append("")
    lines.append("## Figures")
    lines.append("")
    figure_rel = f"figures/{summary['run_id']}"
    lines.append(f"![Retained token rate]({figure_rel}/retained_token_rate.png)")
    lines.append("")
    lines.append(f"![Truncation rate]({figure_rel}/truncation_rate.png)")
    lines.append("")
    lines.append(f"![Chunks per document]({figure_rel}/chunks_per_doc.png)")
    lines.append("")
    lines.append(f"![Token multiplier]({figure_rel}/chunk_token_multiplier.png)")
    if (figure_dir / "long_doc_behavior.png").exists():
        lines.append("")
        lines.append(f"![Long document behavior]({figure_rel}/long_doc_behavior.png)")
    lines.append("")
    lines.append("## Long-Document Behavior")
    lines.append("")
    lines.append("| strategy | long-doc chunks/doc p95 | retained tokens | truncated docs | token multiplier |")
    lines.append("|---|---:|---:|---:|---:|")
    for name in STRATEGY_ORDER:
        if name not in summary["strategies"]:
            continue
        long_doc = summary["strategies"][name].get("long_doc_behavior")
        if not long_doc:
            continue
        lines.append(
            "| "
            + " | ".join([
                f"`{name}`",
                fmt_num(safe_get(long_doc, "chunks_per_doc_percentiles", "p95")),
                fmt_pct(long_doc["retained_token_rate"]),
                fmt_pct(long_doc["truncation_rate"]),
                fmt_num(long_doc["chunk_token_multiplier"]),
            ])
            + " |"
        )
    lines.append("")
    lines.append("## Example Files")
    lines.append("")
    lines.append("Before/after chunk previews are stored under:")
    lines.append("")
    lines.append(f"```text\nexamples/{summary['run_id']}/\n```")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Token counts use the same approximate convention as corpus profiling: `ceil(chars / 4)`.")
    lines.append("- Prefix strategies are baselines, not recommended final systems.")
    lines.append("- Retrieval quality still needs a later embedding/index experiment after the chunking choice is narrowed.")
    lines.append("")
    return "\n".join(lines)


def render_teams_post(summary: dict[str, Any]) -> str:
    rows = strategy_rows(summary)
    by_name = {row["strategy"]: row for row in rows}
    hybrid = by_name.get("hybrid_short_whole_long_chunk")
    first512 = by_name.get("first_512")
    fixed512 = by_name.get("fixed_512_overlap_64")
    lines = [
        "# Local chunking comparison update",
        "",
        f"Run: `{summary['run_id']}`, docs processed: {summary['processed_docs']:,}, errors: {len(summary.get('errors', []))}.",
        "",
        "Initial observations:",
    ]
    if first512:
        lines.append(
            f"- `first_512` retains {fmt_pct(first512['retained_token_rate'])} of approximate tokens "
            f"and truncates {fmt_pct(first512['truncation_rate'])} of docs. This is useful as a baseline, not as the main strategy."
        )
    if fixed512:
        lines.append(
            f"- `fixed_512_overlap_64` keeps {fmt_pct(fixed512['retained_token_rate'])} coverage "
            f"with {fmt_num(fixed512['chunk_token_multiplier'])}x token multiplier from chunking/overlap."
        )
    if hybrid:
        lines.append(
            f"- `hybrid_short_whole_long_chunk` keeps {fmt_pct(hybrid['retained_token_rate'])} coverage "
            f"with {fmt_num(hybrid['chunks_per_doc_mean'])} mean chunks/doc."
        )
    lines.extend([
        "",
        "Suggested figures to attach:",
        "- retained_token_rate.png",
        "- truncation_rate.png",
        "- chunks_per_doc.png",
        "- long_doc_behavior.png",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    summary = read_json(args.summary)
    sample_summary = read_json(args.sample_summary)
    reports_dir = args.reports_dir
    figure_dir = reports_dir / "figures" / args.run_id
    figure_dir.mkdir(parents=True, exist_ok=True)
    rows = strategy_rows(summary)

    plot_bar(rows, "retained_token_rate", "retained token rate", "Retained Token Rate", figure_dir / "retained_token_rate.png", pct=True)
    plot_bar(rows, "truncation_rate", "truncated docs", "Truncation Rate", figure_dir / "truncation_rate.png", pct=True)
    plot_chunks_mean_p95(rows, figure_dir / "chunks_per_doc.png")
    plot_bar(rows, "chunk_token_multiplier", "chunk token multiplier", "Chunk Token Multiplier", figure_dir / "chunk_token_multiplier.png")
    plot_long_doc(summary, figure_dir / "long_doc_behavior.png")

    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / args.report_name
    report_path.write_text(render_markdown(summary, sample_summary, figure_dir), encoding="utf-8")
    teams_path = reports_dir / "teams_post.md"
    teams_path.write_text(render_teams_post(summary), encoding="utf-8")
    print(f"[render_report] wrote {report_path}")
    print(f"[render_report] wrote {teams_path}")
    print(f"[render_report] figures: {figure_dir}")


if __name__ == "__main__":
    main()
