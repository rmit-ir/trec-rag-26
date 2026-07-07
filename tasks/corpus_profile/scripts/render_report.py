#!/usr/bin/env python3
"""Render Markdown report and figures from corpus profiling stats."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import seaborn as sns  # noqa: E402


PLOT_PALETTE = [
    "#4C78A8",
    "#F58518",
    "#54A24B",
    "#E45756",
    "#72B7B2",
    "#B279A2",
    "#FF9DA6",
    "#9D755D",
]

sns.set_theme(
    style="whitegrid",
    context="talk",
    rc={
        "figure.dpi": 140,
        "savefig.dpi": 180,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "axes.titleweight": "bold",
        "axes.labelsize": 12,
        "axes.titlesize": 15,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "font.family": "DejaVu Sans",
    },
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", type=Path, required=True)
    ap.add_argument("--run-config", type=Path, required=True)
    ap.add_argument("--download-summary", type=Path, required=True)
    ap.add_argument("--examples-dir", type=Path, required=True)
    ap.add_argument("--reports-dir", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--report-name", default="corpus_profile.md")
    return ap.parse_args()


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return default or {}
    return json.loads(path.read_text(encoding="utf-8"))


def fmt_num(x: float | int) -> str:
    if isinstance(x, float) and not x.is_integer():
        return f"{x:,.2f}"
    return f"{int(x):,}"


def metric_table(stats: dict[str, Any], metric: str) -> str:
    m = stats["metrics"][metric]
    p = m["percentiles"]
    rows = [
        ("mean", m["mean"]),
        ("p50", p["p50"]),
        ("p75", p["p75"]),
        ("p90", p["p90"]),
        ("p95", p["p95"]),
        ("p99", p["p99"]),
        ("max", p["max"]),
    ]
    out = ["| statistic | value |", "|---|---:|"]
    out.extend(f"| `{k}` | {fmt_num(v)} |" for k, v in rows)
    return "\n".join(out)


def clean_label(label: str) -> str:
    return label.replace("_", " ")


def markdown_relpath(target: Path, base_dir: Path) -> str:
    return Path(
        os.path.relpath(
            target.resolve(strict=False),
            start=base_dir.resolve(strict=False),
        )
    ).as_posix()


def add_percent_labels(ax: plt.Axes, values: list[float], *, xpad: float = 0.004) -> None:
    xmax = max(values) if values else 1.0
    for patch, val in zip(ax.patches, values):
        x = patch.get_width()
        y = patch.get_y() + patch.get_height() / 2
        ax.text(
            min(x + xpad, max(xmax * 1.12, 0.05)),
            y,
            f"{val:.2%}",
            va="center",
            ha="left",
            fontsize=9,
            color="#2b2b2b",
        )


def horizontal_percent_chart(
    labels: list[str],
    values: list[float],
    title: str,
    out: Path,
    *,
    sort: bool = True,
    x_limit: float | None = None,
) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    pairs = list(zip(labels, values))
    if sort:
        pairs.sort(key=lambda x: x[1], reverse=True)
    plot_labels = [clean_label(p[0]) for p in pairs]
    plot_values = [p[1] for p in pairs]
    height = max(4.8, 0.56 * len(plot_labels) + 1.5)
    fig, ax = plt.subplots(figsize=(10.8, height))
    sns.barplot(
        x=plot_values,
        y=plot_labels,
        hue=plot_labels,
        palette=PLOT_PALETTE[: len(plot_labels)] if len(plot_labels) <= len(PLOT_PALETTE) else "tab20",
        legend=False,
        ax=ax,
    )
    ax.set_title(title, loc="left", pad=12)
    ax.set_xlabel("Share of sampled documents")
    ax.set_ylabel("")
    upper = x_limit if x_limit is not None else max(plot_values) * 1.18 if plot_values else 1.0
    ax.set_xlim(0, min(max(upper, 0.05), 1.0))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0%}"))
    add_percent_labels(ax, plot_values)
    ax.grid(axis="x", color="#dddddd", linewidth=0.8)
    ax.grid(axis="y", visible=False)
    plt.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close()


def percentile_chart(stats: dict[str, Any], metric: str, title: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    p = stats["metrics"][metric]["percentiles"]
    labels = ["p50", "p75", "p90", "p95", "p99", "max"]
    values = [p[k] for k in labels]
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    sns.lineplot(
        x=labels,
        y=values,
        marker="o",
        linewidth=2.4,
        markersize=8,
        color="#4C78A8",
        ax=ax,
    )
    ax.set_title(title, loc="left", pad=12)
    ax.set_xlabel("Percentile")
    ax.set_ylabel(metric)
    ax.set_yscale("log")
    ax.grid(axis="y", color="#dddddd", linewidth=0.8)
    ax.grid(axis="x", visible=False)
    for label, val in zip(labels, values):
        ax.annotate(
            fmt_num(val),
            (label, val),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=8,
            color="#333333",
        )
    plt.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close()


def load_metric_values(stats: dict[str, Any], metric: str) -> np.ndarray:
    chunks = []
    for shard in stats.get("shards", []):
        path = shard.get("metrics_npz")
        if not path:
            continue
        try:
            with np.load(path) as npz:
                chunks.append(npz[metric])
        except Exception as e:  # noqa: BLE001
            print(f"[report] warning: could not load {metric} from {path}: {e!r}", flush=True)
    if not chunks:
        return np.asarray([], dtype=np.float64)
    return np.concatenate(chunks)


def token_bucket_counts(stats: dict[str, Any]) -> list[tuple[str, int, float]]:
    vals = load_metric_values(stats, "approx_token_count")
    if vals.size == 0:
        return []
    bins = [0, 128, 256, 512, 1024, 2048, 4096, 8192, 10**18]
    labels = ["<=128", "129-256", "257-512", "513-1024", "1025-2048",
              "2049-4096", "4097-8192", ">8192"]
    counts, _ = np.histogram(vals, bins=bins)
    total = max(int(counts.sum()), 1)
    return [(label, int(count), int(count) / total) for label, count in zip(labels, counts)]


def top_long_docs(stats: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    category_names = stats.get("category_names", [])
    for shard in stats.get("shards", []):
        path = shard.get("metrics_npz")
        filename = shard.get("filename", "")
        stem = filename.removesuffix(".parquet")
        if not path:
            continue
        try:
            with np.load(path) as npz:
                char_count = npz["char_count"]
                approx_tokens = npz["approx_token_count"]
                category_id = npz["category_id"]
                if "row_number" in npz:
                    row_number = npz["row_number"]
                else:
                    row_number = np.arange(char_count.size)
                take = np.argsort(char_count)[-limit:][::-1]
                for idx in take:
                    row_i = int(row_number[idx])
                    cat_i = int(category_id[idx])
                    rows.append({
                        "docid": f"{stem}_{row_i}",
                        "filename": filename,
                        "row_number": row_i,
                        "category": category_names[cat_i] if cat_i < len(category_names) else str(cat_i),
                        "char_count": int(char_count[idx]),
                        "approx_token_count": int(approx_tokens[idx]),
                    })
        except Exception as e:  # noqa: BLE001
            print(f"[report] warning: could not inspect long docs from {path}: {e!r}", flush=True)
    rows.sort(key=lambda r: r["char_count"], reverse=True)
    return rows[:limit]


def log_histogram(values: np.ndarray, title: str, xlabel: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if values.size == 0:
        return
    clipped = np.maximum(values.astype(np.float64), 1.0)
    log_values = np.log10(clipped)
    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    sns.histplot(log_values, bins=60, color="#4C78A8", edgecolor="#ffffff", linewidth=0.25, ax=ax)
    median = float(np.median(log_values))
    p95 = float(np.percentile(log_values, 95))
    ax.axvline(median, color="#F58518", linestyle="--", linewidth=1.8, label="median")
    ax.axvline(p95, color="#E45756", linestyle="--", linewidth=1.8, label="p95")
    ax.set_title(title, loc="left", pad=12)
    plt.xlabel(f"log10({xlabel}, clipped at 1)")
    plt.ylabel("document count")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", color="#dddddd", linewidth=0.8)
    ax.grid(axis="x", visible=False)
    plt.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close()


def render_figures(args: argparse.Namespace, stats: dict[str, Any]) -> dict[str, str]:
    fig_dir = args.reports_dir / "figures" / args.run_id
    report_dir = (args.reports_dir / args.report_name).parent
    cats = stats.get("primary_category_counts", {})
    total = max(int(stats.get("processed_docs", 0)), 1)
    labels = list(cats.keys())
    rates = [cats[k] / total for k in labels]
    paths = {
        "structure": fig_dir / "structure_category_rates.png",
        "non_clean_structure": fig_dir / "non_clean_structure_category_rates.png",
        "char_hist": fig_dir / "char_count_log_histogram.png",
        "token_hist": fig_dir / "approx_token_log_histogram.png",
        "token_buckets": fig_dir / "approx_token_bucket_rates.png",
        "char_percentiles": fig_dir / "char_count_percentiles.png",
        "token_percentiles": fig_dir / "approx_token_percentiles.png",
    }
    if labels:
        horizontal_percent_chart(
            labels,
            rates,
            "Primary structure category rates",
            paths["structure"],
        )
        small = [(label, rate) for label, rate in zip(labels, rates) if label != "clean_text"]
        if small:
            small_labels, small_rates = zip(*small)
            horizontal_percent_chart(
                list(small_labels),
                list(small_rates),
                "Non-clean primary category rates",
                paths["non_clean_structure"],
                x_limit=max(small_rates) * 1.3,
            )
    buckets = token_bucket_counts(stats)
    if buckets:
        horizontal_percent_chart(
            [b[0] for b in buckets],
            [b[2] for b in buckets],
            "Approximate token bucket distribution",
            paths["token_buckets"],
            sort=False,
        )
    log_histogram(
        load_metric_values(stats, "char_count"),
        "Document char-count distribution",
        "char_count",
        paths["char_hist"],
    )
    log_histogram(
        load_metric_values(stats, "approx_token_count"),
        "Approximate token-count distribution",
        "approx_token_count",
        paths["token_hist"],
    )
    percentile_chart(stats, "char_count", "Document char-count percentiles", paths["char_percentiles"])
    percentile_chart(stats, "approx_token_count", "Approximate token-count percentiles", paths["token_percentiles"])
    return {k: markdown_relpath(v, report_dir) for k, v in paths.items()}


def example_paths(args: argparse.Namespace, category: str) -> list[Path]:
    d = args.examples_dir / category
    if not d.exists():
        return []
    return sorted(d.glob("*.txt"))


def example_links(args: argparse.Namespace, category: str, limit: int = 5) -> list[str]:
    links = []
    report_dir = (args.reports_dir / args.report_name).parent
    for path in example_paths(args, category)[:limit]:
        rel = markdown_relpath(path, report_dir)
        links.append(f"- [{path.name}]({rel})")
    return links


def spot_check_links(args: argparse.Namespace, category: str) -> list[str]:
    paths = example_paths(args, category)
    if not paths:
        return []
    idxs = sorted({0, len(paths) // 2, len(paths) - 1})
    links = []
    report_dir = (args.reports_dir / args.report_name).parent
    for idx in idxs:
        path = paths[idx]
        rel = markdown_relpath(path, report_dir)
        links.append(f"[{path.name}]({rel})")
    return links


def chunking_implications(stats: dict[str, Any]) -> list[str]:
    p = stats["metrics"]["approx_token_count"]["percentiles"]
    cats = stats.get("primary_category_rates", {})
    flags = stats.get("flag_rates", {})
    notes = []
    p50 = p.get("p50", 0)
    p95 = p.get("p95", 0)
    p99 = p.get("p99", 0)
    if p50 <= 512:
        notes.append("Median documents are short enough that full-document embedding should be included as a baseline.")
    else:
        notes.append("Median documents exceed 512 approximate tokens; full-document embedding may dilute topics or hit encoder truncation.")
    if p95 >= 2000:
        notes.append("The upper tail is long; fixed-size chunking and paragraph-aware chunking should both be tested.")
    if p99 >= 8000:
        notes.append("Very long documents exist in the sample; first-window-only strategies are risky for recall and citation coverage.")
    markup_rate = cats.get("html_or_markup_like", cats.get("html_like", 0.0))
    url_rate = flags.get("url_heavy", cats.get("url_heavy", 0.0))
    boilerplate_rate = flags.get("boilerplate_signal", cats.get("boilerplate_heavy", 0.0))
    if max(markup_rate, url_rate, boilerplate_rate) >= 0.05 or (markup_rate + url_rate + boilerplate_rate) >= 0.10:
        notes.append("Markup, URL-heavy, or boilerplate signals exist; cleaning and structure-aware chunking should be evaluated.")
    else:
        notes.append("Markup, URL-heavy, and boilerplate signals are not dominant in this sample, but examples should still be inspected.")
    return notes


def main() -> int:
    args = parse_args()
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    stats = load_json(args.stats)
    config = load_json(args.run_config)
    download = load_json(args.download_summary, default={"available": "unknown", "failed": "unknown"})
    figs = render_figures(args, stats)

    report = args.reports_dir / args.report_name
    total_docs = int(stats.get("processed_docs", 0))
    total_shards = int(stats.get("processed_shards", 0))

    lines: list[str] = []
    lines.append("# ClimbMix Corpus Profiling Report")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    token_p = stats["metrics"]["approx_token_count"]["percentiles"]
    lines.append(f"- Run ID: `{args.run_id}`.")
    lines.append(f"- Processed `{total_docs:,}` documents from `{total_shards:,}` parquet shards.")
    lines.append(f"- Download availability: `{download.get('available')}` available, `{download.get('failed')}` failed.")
    if stats.get("structure_rule_version"):
        lines.append(f"- Structure rule set: `{stats.get('structure_rule_version')}`.")
    lines.append(
        "- Length profile: "
        f"p50 `{fmt_num(token_p['p50'])}`, p95 `{fmt_num(token_p['p95'])}`, "
        f"p99 `{fmt_num(token_p['p99'])}`, max `{fmt_num(token_p['max'])}` approximate tokens."
    )
    for note in chunking_implications(stats):
        lines.append(f"- {note}")
    lines.append("")

    lines.append("## Sample Design")
    lines.append("")
    lines.append("| field | value |")
    lines.append("|---|---:|")
    for key in ("profile_run", "seed", "total_shards", "sample_shards", "max_docs_per_shard"):
        lines.append(f"| `{key}` | `{config.get(key)}` |")
    lines.append(f"| `repo_id` | `{config.get('repo_id')}` |")
    lines.append("")
    lines.append("### Limitations")
    lines.append("")
    lines.append("- This is a pilot sample for corpus understanding, not a final full-corpus estimate.")
    lines.append("- Sampling is shard-level uniform sampling, with a per-shard document cap.")
    lines.append("- Token counts are approximate (`ceil(char_count / 4)`) and should be replaced with model-tokenizer counts before final context-budget decisions.")
    lines.append("- Structure labels are heuristic signals for corpus profiling, not gold document-type labels.")
    lines.append("- Primary structure categories are mutually exclusive; noise flags are non-exclusive.")
    lines.append("- Representative examples use per-category reservoir sampling.")
    lines.append("")

    lines.append("## Document Length Distribution")
    lines.append("")
    lines.append("### Character Count")
    lines.append("")
    lines.append(metric_table(stats, "char_count"))
    lines.append("")
    lines.append(f"![Character count log histogram]({figs['char_hist']})")
    lines.append("")
    lines.append(f"![Character count percentiles]({figs['char_percentiles']})")
    lines.append("")
    lines.append("### Approximate Token Count")
    lines.append("")
    lines.append("Approximate tokens use `ceil(char_count / 4)`. Treat these as profiling estimates, not exact tokenizer counts.")
    lines.append("")
    lines.append(metric_table(stats, "approx_token_count"))
    lines.append("")
    lines.append(f"![Approximate token log histogram]({figs['token_hist']})")
    lines.append("")
    lines.append(f"![Approximate token percentiles]({figs['token_percentiles']})")
    lines.append("")
    lines.append("### Approximate Token Buckets")
    lines.append("")
    lines.append("| bucket | count | rate |")
    lines.append("|---|---:|---:|")
    for label, count, rate in token_bucket_counts(stats):
        lines.append(f"| `{label}` | {count:,} | {rate:.2%} |")
    lines.append("")
    lines.append(f"![Approximate token bucket rates]({figs['token_buckets']})")
    lines.append("")
    lines.append("### Long-Tail Outliers")
    lines.append("")
    lines.append("The longest documents are important because they can dominate embedding truncation and chunking behavior.")
    lines.append("")
    lines.append("| rank | docid | category | chars | approx tokens |")
    lines.append("|---:|---|---|---:|---:|")
    for rank, row in enumerate(top_long_docs(stats, limit=15), start=1):
        lines.append(
            f"| {rank} | `{row['docid']}` | `{row['category']}` | "
            f"{row['char_count']:,} | {row['approx_token_count']:,} |"
        )
    lines.append("")

    lines.append("## Structure And Format")
    lines.append("")
    lines.append("Primary categories are mutually exclusive. URL-heavy and boilerplate signals are reported below as non-exclusive flags, not as primary document types.")
    lines.append("")
    lines.append("| primary category | count | rate |")
    lines.append("|---|---:|---:|")
    counts = stats.get("primary_category_counts", {})
    for name, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
        rate = count / max(total_docs, 1)
        lines.append(f"| `{name}` | {count:,} | {rate:.2%} |")
    lines.append("")
    lines.append(f"![Structure category rates]({figs['structure']})")
    lines.append("")
    lines.append("The overall chart is dominated by `clean_text`; the next figure zooms in on non-clean categories for slide readability.")
    lines.append("")
    lines.append(f"![Non-clean structure category rates]({figs['non_clean_structure']})")
    lines.append("")

    lines.append("## Noise Flags")
    lines.append("")
    lines.append("Flags are non-exclusive; one document can count toward multiple rows. They should be interpreted as signals, not document types.")
    lines.append("")
    lines.append("| flag | count | rate |")
    lines.append("|---|---:|---:|")
    flags = stats.get("flag_counts", {})
    for name, count in sorted(flags.items(), key=lambda kv: kv[1], reverse=True):
        rate = count / max(total_docs, 1)
        lines.append(f"| `{name}` | {count:,} | {rate:.2%} |")
    lines.append("")

    lines.append("## Representative Examples")
    lines.append("")
    lines.append("Examples are clipped and stored as text files with JSON headers containing metrics, heuristic features, and sampling metadata.")
    lines.append("For manual auditing, inspect first/middle/last saved examples per primary category. These files come from a per-category reservoir sample.")
    lines.append("")
    lines.append("| category | suggested spot-check files |")
    lines.append("|---|---|")
    for category in stats.get("category_names", []):
        links = spot_check_links(args, category)
        if links:
            lines.append(f"| `{category}` | {'<br>'.join(links)} |")
    lines.append("")
    for category in stats.get("category_names", []):
        links = example_links(args, category)
        if not links:
            continue
        lines.append(f"### `{category}`")
        lines.append("")
        lines.extend(links)
        lines.append("")

    lines.append("## Implications For Chunking")
    lines.append("")
    for note in chunking_implications(stats):
        lines.append(f"- {note}")
    lines.append("- A single first-500-token strategy would truncate or ignore meaningful later content for a large fraction of documents.")
    lines.append("- The small but extreme long tail should be handled with a separate long-document path rather than by tuning around the median.")
    lines.append("")
    lines.append("Recommended next chunking comparisons:")
    lines.append("")
    lines.append("- Full-document embedding for short documents, especially documents under 512 approximate tokens.")
    lines.append("- First 512 approximate tokens as a cheap baseline, with explicit inspection of missed later evidence.")
    lines.append("- Fixed 512-token chunks with 64-token overlap.")
    lines.append("- Fixed 1024-token chunks with 128-token overlap.")
    lines.append("- Paragraph-aware chunks capped at 512 or 1024 approximate tokens.")
    lines.append("- Long-document fallback: cap max chunks per parent document and preserve parent ClimbMix docid for final citations.")
    lines.append("")

    lines.append("## Slide-Ready Assets")
    lines.append("")
    lines.append(f"- Overall structure rates: `{figs['structure']}`")
    lines.append(f"- Non-clean category rates: `{figs['non_clean_structure']}`")
    lines.append(f"- Approximate token distribution: `{figs['token_hist']}`")
    lines.append(f"- Approximate token bucket rates: `{figs['token_buckets']}`")
    lines.append(f"- Approximate token percentiles: `{figs['token_percentiles']}`")
    lines.append("")

    lines.append("## Reproducibility")
    lines.append("")
    lines.append(f"- Run config: `{args.run_config}`")
    lines.append(f"- Aggregate stats: `{args.stats}`")
    lines.append(f"- Examples: `{args.examples_dir}`")
    lines.append("")

    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"[report] wrote {report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
