#!/usr/bin/env python3
"""Copy the 2021 comparison notebook and generalize it to TREC-DL 2021–2023."""
from __future__ import annotations

import copy
from pathlib import Path

import nbformat


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "tmp" / "compare_2021_keywords_before_after_promptarmor_v4.ipynb"
DESTINATION = REPO_ROOT / "tmp" / "compare_trec_dl.ipynb"


def code(source: str) -> nbformat.NotebookNode:
    """Create one code cell with normalized surrounding whitespace."""
    return nbformat.v4.new_code_cell(source.strip() + "\n")


def markdown(source: str) -> nbformat.NotebookNode:
    """Create one markdown cell with normalized surrounding whitespace."""
    return nbformat.v4.new_markdown_cell(source.strip() + "\n")


source_notebook = nbformat.read(SOURCE, as_version=4)
notebook = copy.deepcopy(source_notebook)
notebook.cells = [
    markdown(
        """
# Keyword vs Yun Yi injection under Bing and PromptArmor v4 (TREC-DL 2021–2023)

This notebook extends the 2021 comparison across TREC-DL 2021, 2022, and 2023.
It audits every expected ledger, deduplicates repeated attempts, retains completed
0–3 judgments, and uses the intersection of `(qid, docid)` tasks among available
injected runs within each year for fair distributions. Missing runs remain visible
in the audit instead of being silently omitted.
"""
    ),
    code(
        """
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
YEARS = [2021, 2022, 2023]
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
EXPECTED_TASKS = {2021: 2395, 2022: 2655, 2023: 2460}

# The canonical keyword tree groups both prompts under the model. The copied
# 2021 comparison uses the archived pre-uppercase Bing run so it remains
# input-matched to the pre-uppercase PromptArmor v4 run.
RUN_PATHS = {
    2021: {
        "Original + Bing": RESULTS_ROOT / "original" / "gpt-oss-20b" / "2021.judgments.jsonl",
        "Keyword + Bing": RESULTS_ROOT / "keywords" / "gpt-oss-20b" / "archive" / "bing-pre-uppercase" / "2021.judgments.jsonl",
        "Keyword + v4": RESULTS_ROOT / "keywords" / "gpt-oss-20b" / "promptarmor-v4" / "2021" / "judgments.jsonl",
        "Yun Yi + Bing": RESULTS_ROOT / "yun_yi" / "gpt-oss-20b" / "bing" / "2021" / "judgments.jsonl",
        "Yun Yi + v4": RESULTS_ROOT / "yun_yi" / "gpt-oss-20b" / "promptarmor-v4-corrected" / "2021" / "judgments.jsonl",
    },
    2022: {
        "Original + Bing": RESULTS_ROOT / "original" / "gpt-oss-20b" / "2022.judgments.jsonl",
        "Keyword + Bing": RESULTS_ROOT / "keywords" / "gpt-oss-20b" / "bing" / "2022" / "2022.judgments.jsonl",
        "Keyword + v4": RESULTS_ROOT / "keywords" / "gpt-oss-20b" / "promptarmor-v4" / "2022" / "judgments.jsonl",
        "Yun Yi + Bing": RESULTS_ROOT / "yun_yi" / "gpt-oss-20b" / "bing" / "2022" / "judgments.jsonl",
        "Yun Yi + v4": RESULTS_ROOT / "yun_yi" / "gpt-oss-20b" / "promptarmor-v4-corrected" / "2022" / "judgments.jsonl",
    },
    2023: {
        "Original + Bing": RESULTS_ROOT / "original" / "gpt-oss-20b" / "2023.judgments.jsonl",
        "Keyword + Bing": RESULTS_ROOT / "keywords" / "gpt-oss-20b" / "bing" / "2023" / "2023.judgments.jsonl",
        "Keyword + v4": RESULTS_ROOT / "keywords" / "gpt-oss-20b" / "promptarmor-v4" / "2023" / "judgments.jsonl",
        "Yun Yi + Bing": RESULTS_ROOT / "yun_yi" / "gpt-oss-20b" / "bing" / "2023" / "judgments.jsonl",
        "Yun Yi + v4": RESULTS_ROOT / "yun_yi" / "gpt-oss-20b" / "promptarmor-v4-corrected" / "2023" / "judgments.jsonl",
    },
}


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
    required = {"qid", "docid", "judgment"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Result file is missing columns: {sorted(missing)}")
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


raw = {}
runs = {}
audit_rows = []
for year in YEARS:
    for run_name in RUN_ORDER:
        path = RUN_PATHS[year][run_name]
        if path.exists():
            frame = read_jsonl(path)
            cleaned = latest_completed(frame)
            raw[(year, run_name)] = frame
            runs[(year, run_name)] = cleaned
            audit_rows.append({
                "year": year,
                "run": run_name,
                "available": True,
                "file_rows": len(frame),
                "completed_unique_tasks": len(cleaned),
                "discarded_or_duplicate_rows": len(frame) - len(cleaned),
                "queries": cleaned["qid"].nunique(),
                "coverage_pct": 100 * len(cleaned) / EXPECTED_TASKS[year],
                "path": str(path.relative_to(REPO_ROOT)),
            })
        else:
            audit_rows.append({
                "year": year,
                "run": run_name,
                "available": False,
                "file_rows": 0,
                "completed_unique_tasks": 0,
                "discarded_or_duplicate_rows": 0,
                "queries": 0,
                "coverage_pct": 0.0,
                "path": str(path.relative_to(REPO_ROOT)),
            })

audit = pd.DataFrame(audit_rows)
audit_display = audit.copy()
audit_display["coverage_pct"] = audit_display["coverage_pct"].map("{:.1f}%".format)
display(audit_display)

missing = audit.loc[~audit["available"], ["year", "run", "path"]]
if len(missing):
    print(f"Unavailable ledgers: {len(missing)}. Their comparisons remain explicit below.")
    display(missing)

# Align all available injected runs within each year on one fair task intersection.
aligned_by_year = {}
for year in YEARS:
    available = [name for name in INJECTED_RUN_ORDER if (year, name) in runs]
    if not available:
        continue
    common_keys = set.intersection(*(
        set(map(tuple, runs[(year, name)][KEY].itertuples(index=False, name=None)))
        for name in available
    ))
    if not common_keys:
        print(f"{year}: available injected runs have no common tasks")
        continue
    common_index = pd.MultiIndex.from_tuples(sorted(common_keys), names=KEY)
    aligned = pd.DataFrame(index=common_index)
    for name in available:
        aligned[name] = runs[(year, name)].set_index(KEY)["judgment"].reindex(common_index).astype(int)
    aligned_by_year[year] = aligned
    print(f"{year}: {len(aligned):,} tasks shared by {len(available)} available injected runs")
"""
    ),
    markdown(
        """
## Relevance-label distributions

Within each year, available injected runs use their shared `(qid, docid)` set.
Original + Bing is shown from its full ledger when available. Missing conditions
remain empty in the corresponding facet and are documented in the audit.
"""
    ),
    code(
        """
distribution_rows = []
for year in YEARS:
    if (year, "Original + Bing") in runs:
        counts = runs[(year, "Original + Bing")]["judgment"].value_counts().reindex(LABEL_ORDER, fill_value=0)
        for judgment, count in counts.items():
            distribution_rows.append({
                "Year": year,
                "Run": "Original + Bing",
                "Judgment": judgment,
                "Count": count,
                "Basis": "full available ledger",
            })
    aligned = aligned_by_year.get(year)
    if aligned is not None:
        for run_name in aligned.columns:
            counts = aligned[run_name].value_counts().reindex(LABEL_ORDER, fill_value=0)
            for judgment, count in counts.items():
                distribution_rows.append({
                    "Year": year,
                    "Run": run_name,
                    "Judgment": judgment,
                    "Count": count,
                    "Basis": f"{len(aligned):,} shared injected tasks",
                })

distribution = pd.DataFrame(distribution_rows)
display(distribution.pivot_table(
    index=["Year", "Run", "Basis"],
    columns="Judgment",
    values="Count",
    fill_value=0,
))

g = sns.catplot(
    data=distribution,
    x="Run",
    y="Count",
    hue="Judgment",
    col="Year",
    kind="bar",
    order=RUN_ORDER,
    hue_order=LABEL_ORDER,
    col_order=YEARS,
    height=4.2,
    aspect=1.15,
    sharey=False,
)
g.set_axis_labels("Run", "Count")
g.set_titles("TREC-DL {col_name}")
for axis in g.axes.flat:
    axis.tick_params(axis="x", rotation=35)
    for label in axis.get_xticklabels():
        label.set_horizontalalignment("right")
g.figure.subplots_adjust(top=0.82)
g.figure.suptitle("Relevance judgment distributions by year")
plt.show()
"""
    ),
    markdown(
        """
## Baseline-paired coverage and Cohen's kappa

Each injected condition is paired to Original + Bing by `(qid, docid)` within
year. A missing baseline, missing run, or zero-overlap candidate set is reported
as a status rather than converted into a misleading score.
"""
    ),
    code(
        """
matched_pairs = {}
pairing_rows = []
for year in YEARS:
    baseline = runs.get((year, "Original + Bing"))
    for run_name in INJECTED_RUN_ORDER:
        comparison = runs.get((year, run_name))
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
        matched_pairs[(year, run_name)] = matched
        pairing_rows.append({
            "year": year,
            "run": run_name,
            "status": status,
            "matched_tasks": len(matched),
        })

pairing_audit = pd.DataFrame(pairing_rows)
display(pairing_audit)
"""
    ),
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
for (year, run_name), matched in matched_pairs.items():
    kappa_rows.append({
        "year": year,
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
mean_difference_rows = []
for (year, run_name), matched in matched_pairs.items():
    differences = (
        matched["judgment_run"] - matched["judgment_original"]
        if len(matched)
        else pd.Series(dtype=float)
    )
    mean_difference_rows.append({
        "year": year,
        "run": run_name,
        "matched_tasks": len(matched),
        "original_mean": matched["judgment_original"].mean() if len(matched) else np.nan,
        "run_mean": matched["judgment_run"].mean() if len(matched) else np.nan,
        "mean_difference": differences.mean(),
    })

mean_difference_results = pd.DataFrame(mean_difference_rows)
display(mean_difference_results.round({
    "original_mean": 3,
    "run_mean": 3,
    "mean_difference": 3,
}))
"""
    ),
]

for cell in notebook.cells:
    if cell.cell_type == "code":
        cell.execution_count = None
        cell.outputs = []

nbformat.write(notebook, DESTINATION)
print(f"Wrote {DESTINATION}")
