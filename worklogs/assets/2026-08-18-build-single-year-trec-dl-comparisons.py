#!/usr/bin/env python3
"""Build standalone TREC-DL 2022 and 2023 relevance-comparison notebooks."""
from __future__ import annotations

from pathlib import Path

import nbformat


REPO_ROOT = Path(__file__).resolve().parents[2]
YEARS = (2022, 2023)


def code(source: str) -> nbformat.NotebookNode:
    """Create a code cell with normalized surrounding whitespace."""
    return nbformat.v4.new_code_cell(source.strip() + "\n")


def markdown(source: str) -> nbformat.NotebookNode:
    """Create a Markdown cell with normalized surrounding whitespace."""
    return nbformat.v4.new_markdown_cell(source.strip() + "\n")


def build_notebook(year: int) -> nbformat.NotebookNode:
    """Return one self-contained single-year comparison notebook."""
    notebook = nbformat.v4.new_notebook()
    notebook.cells = [
        markdown(
            f"""
# Keyword vs Yun Yi injection under Bing and PromptArmor v4 ({year})

This notebook applies the same comparison used for TREC-DL 2021 to TREC-DL
{year}. It audits every expected ledger, keeps the latest completed 0–3 judgment
per `(qid, docid)`, compares relevance-label distributions, and pairs each
available injected run with the uninjected Original + Bing baseline.

Missing ledgers remain visible in the audit and result tables instead of causing
the notebook to fail.
"""
        ),
        code(
            f"""
from pathlib import Path
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from IPython.display import display

sns.set_theme(style="whitegrid", context="notebook", palette="colorblind")
pd.set_option("display.max_colwidth", 180)


def find_repo_root(start=Path.cwd()):
    for candidate in (start, *start.parents):
        if (candidate / "evaluation-results").exists() and (candidate / "tasks").exists():
            return candidate
    raise FileNotFoundError("Could not locate the repository root")


REPO_ROOT = find_repo_root()
RESULTS_ROOT = REPO_ROOT / "evaluation-results" / "llm-judge-robustness"
YEAR = {year}
EXPECTED_TASKS = {2655 if year == 2022 else 2460}
RUN_ORDER = [
    "Original + Bing",
    "Keyword + Bing",
    "Keyword + v4",
    "Yun Yi + Bing",
    "Yun Yi + v4",
]
INJECTED_RUN_ORDER = [name for name in RUN_ORDER if name != "Original + Bing"]
LABEL_ORDER = [0, 1, 2, 3]
KEY = ["qid", "docid"]

RUN_PATHS = {{
    "Original + Bing": RESULTS_ROOT / "original" / "gpt-oss-20b" / f"{{YEAR}}.judgments.jsonl",
    "Keyword + Bing": RESULTS_ROOT / "keywords" / "gpt-oss-20b" / "bing" / f"{{YEAR}}" / f"{{YEAR}}.judgments.jsonl",
    "Keyword + v4": RESULTS_ROOT / "keywords" / "gpt-oss-20b" / "promptarmor-v4" / f"{{YEAR}}" / "judgments.jsonl",
    "Yun Yi + Bing": RESULTS_ROOT / "yun_yi" / "gpt-oss-20b" / "bing" / f"{{YEAR}}" / "judgments.jsonl",
    "Yun Yi + v4": RESULTS_ROOT / "yun_yi" / "gpt-oss-20b" / "promptarmor-v4-corrected" / f"{{YEAR}}" / "judgments.jsonl",
}}


def read_jsonl(path):
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                row = json.loads(line)
                row["_line_number"] = line_number
                rows.append(row)
    return pd.DataFrame(rows)


def latest_completed(frame):
    required = {{"qid", "docid", "judgment"}}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Result file is missing columns: {{sorted(missing)}}")
    status = frame.get("status", pd.Series("", index=frame.index)).copy()
    if "result_status" in frame.columns:
        result_status = frame["result_status"]
        status = result_status.where(result_status.notna() & result_status.ne(""), status)
    judgment = pd.to_numeric(frame["judgment"], errors="coerce")
    completed = frame[status.eq("completed") & judgment.isin(LABEL_ORDER)].copy()
    completed["judgment"] = pd.to_numeric(completed["judgment"]).astype(int)
    completed["qid"] = completed["qid"].astype(str)
    completed["docid"] = completed["docid"].astype(str)
    return completed.sort_values("_line_number").drop_duplicates(KEY, keep="last")


raw = {{}}
runs = {{}}
audit_rows = []
for run_name in RUN_ORDER:
    path = RUN_PATHS[run_name]
    if path.exists():
        frame = read_jsonl(path)
        cleaned = latest_completed(frame)
        raw[run_name] = frame
        runs[run_name] = cleaned
        audit_rows.append({{
            "run": run_name,
            "available": True,
            "file_rows": len(frame),
            "completed_unique_tasks": len(cleaned),
            "discarded_or_duplicate_rows": len(frame) - len(cleaned),
            "queries": cleaned["qid"].nunique(),
            "coverage_pct": 100 * len(cleaned) / EXPECTED_TASKS,
            "path": str(path.relative_to(REPO_ROOT)),
        }})
    else:
        audit_rows.append({{
            "run": run_name,
            "available": False,
            "file_rows": 0,
            "completed_unique_tasks": 0,
            "discarded_or_duplicate_rows": 0,
            "queries": 0,
            "coverage_pct": 0.0,
            "path": str(path.relative_to(REPO_ROOT)),
        }})

audit = pd.DataFrame(audit_rows)
audit_display = audit.copy()
audit_display["coverage_pct"] = audit_display["coverage_pct"].map("{{:.1f}}%".format)
display(audit_display)

missing = audit.loc[~audit["available"], ["run", "path"]]
if len(missing):
    print(f"Unavailable ledgers: {{len(missing)}}. They remain explicit below.")
    display(missing)

available_injected = [name for name in INJECTED_RUN_ORDER if name in runs]
common_keys = set.intersection(*(
    set(map(tuple, runs[name][KEY].itertuples(index=False, name=None)))
    for name in available_injected
))
common_index = pd.MultiIndex.from_tuples(sorted(common_keys), names=KEY)
aligned = pd.DataFrame(index=common_index)
for name in available_injected:
    aligned[name] = runs[name].set_index(KEY)["judgment"].reindex(common_index).astype(int)
print(f"{{len(aligned):,}} tasks shared by {{len(available_injected)}} available injected runs")
"""
        ),
        markdown(
            """
## Relevance-label distributions

Available injected runs use their shared `(qid, docid)` set. Original + Bing is
shown from its full completed ledger. The table's `Basis` column makes the
different denominators explicit.
"""
        ),
        code(
            """
distribution_rows = []
if "Original + Bing" in runs:
    counts = runs["Original + Bing"]["judgment"].value_counts().reindex(LABEL_ORDER, fill_value=0)
    for judgment, count in counts.items():
        distribution_rows.append({
            "Run": "Original + Bing",
            "Judgment": judgment,
            "Count": count,
            "Basis": "full available ledger",
        })

for run_name in aligned.columns:
    counts = aligned[run_name].value_counts().reindex(LABEL_ORDER, fill_value=0)
    for judgment, count in counts.items():
        distribution_rows.append({
            "Run": run_name,
            "Judgment": judgment,
            "Count": count,
            "Basis": f"{len(aligned):,} shared injected tasks",
        })

distribution = pd.DataFrame(distribution_rows)
display(distribution.pivot_table(
    index=["Run", "Basis"],
    columns="Judgment",
    values="Count",
    fill_value=0,
))

figure, axis = plt.subplots(figsize=(11, 5.5))
sns.barplot(
    data=distribution,
    x="Run",
    y="Count",
    hue="Judgment",
    order=[name for name in RUN_ORDER if name in distribution["Run"].unique()],
    hue_order=LABEL_ORDER,
    ax=axis,
)
axis.set_title(f"TREC-DL {YEAR} relevance judgment distributions")
axis.set_xlabel("Run")
axis.set_ylabel("Count")
axis.tick_params(axis="x", rotation=30)
for label in axis.get_xticklabels():
    label.set_horizontalalignment("right")
figure.tight_layout()
plt.show()
"""
        ),
        markdown(
            """
## Baseline-paired coverage

Each injected condition is joined to Original + Bing by `(qid, docid)`. Missing
runs and zero-overlap conditions are reported as statuses.
"""
        ),
        code(
            """
baseline = runs.get("Original + Bing")
matched_pairs = {}
pairing_rows = []
for run_name in INJECTED_RUN_ORDER:
    comparison = runs.get(run_name)
    if baseline is None and comparison is None:
        status = "missing baseline and run"
        matched = pd.DataFrame()
    elif baseline is None:
        status = "missing baseline"
        matched = pd.DataFrame()
    elif comparison is None:
        status = "missing run"
        matched = pd.DataFrame()
    else:
        matched = baseline[KEY + ["judgment"]].merge(
            comparison[KEY + ["judgment"]],
            on=KEY,
            how="inner",
            suffixes=("_original", "_run"),
            validate="one_to_one",
        )
        status = "ok" if len(matched) else "zero task overlap"
    matched_pairs[run_name] = matched
    pairing_rows.append({"run": run_name, "status": status, "matched_tasks": len(matched)})

pairing_audit = pd.DataFrame(pairing_rows)
display(pairing_audit)
"""
        ),
        markdown("## Cohen's kappa"),
        code(
            """
def cohen_kappa(first, second, labels=LABEL_ORDER):
    confusion = pd.crosstab(first, second).reindex(index=labels, columns=labels, fill_value=0)
    total = confusion.to_numpy().sum()
    if total == 0:
        return np.nan
    observed = np.trace(confusion.to_numpy()) / total
    expected = (confusion.sum(axis=1).to_numpy() * confusion.sum(axis=0).to_numpy()).sum() / total**2
    return (observed - expected) / (1 - expected) if expected < 1 else np.nan


kappa_rows = []
for run_name, matched in matched_pairs.items():
    kappa_rows.append({
        "run": run_name,
        "matched_tasks": len(matched),
        "cohen_kappa": (
            cohen_kappa(matched["judgment_original"], matched["judgment_run"])
            if len(matched)
            else np.nan
        ),
    })

kappa_results = pd.DataFrame(kappa_rows)
display(kappa_results.round({"cohen_kappa": 4}))
"""
        ),
        markdown("## Mean judgment difference"),
        code(
            """
mean_rows = []
for run_name, matched in matched_pairs.items():
    differences = (
        matched["judgment_run"] - matched["judgment_original"]
        if len(matched)
        else pd.Series(dtype=float)
    )
    mean_rows.append({
        "run": run_name,
        "matched_tasks": len(matched),
        "original_mean": matched["judgment_original"].mean() if len(matched) else np.nan,
        "run_mean": matched["judgment_run"].mean() if len(matched) else np.nan,
        "mean_difference": differences.mean(),
    })

mean_results = pd.DataFrame(mean_rows)
display(mean_results.round({
    "original_mean": 3,
    "run_mean": 3,
    "mean_difference": 3,
}))
"""
        ),
    ]
    return notebook


for target_year in YEARS:
    destination = (
        REPO_ROOT
        / "tmp"
        / f"compare_{target_year}_keywords_before_after_promptarmor_v4.ipynb"
    )
    nbformat.write(build_notebook(target_year), destination)
    print(f"Wrote {destination}")
