#!/usr/bin/env python3
"""Stream-profile sampled ClimbMix parquet shards."""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq


PRIMARY_CATEGORY_NAMES = [
    "empty_or_tiny",
    "html_or_markup_like",
    "strong_code_like",
    "table_or_record_like",
    "outline_or_markdown_like",
    "clean_text",
]
CATEGORY_NAMES = PRIMARY_CATEGORY_NAMES
CATEGORY_TO_ID = {name: i for i, name in enumerate(PRIMARY_CATEGORY_NAMES)}

FLAG_NAMES = [
    "empty_or_tiny",
    "html_or_markup_like",
    "strong_code_like",
    "table_or_record_like",
    "outline_or_markdown_like",
    "url_heavy",
    "boilerplate_signal",
    "long_tail_outlier",
]
FLAG_TO_ID = {name: i for i, name in enumerate(FLAG_NAMES)}

URL_RE = re.compile(r"https?://|www\.", re.I)
TAG_RE = re.compile(r"<[a-zA-Z][^>\n]{0,120}>")
WORD_RE = re.compile(r"\b[\w'-]+\b", re.UNICODE)
HTML_ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot|apos|nbsp|#\d+);", re.I)
BOILERPLATE_RE = re.compile(
    r"\b(cookie|privacy policy|terms of service|subscribe|sign in|log in|login|"
    r"all rights reserved|newsletter|advertisement|navigation|menu|accept all)\b",
    re.I,
)
BOILERPLATE_STRONG_RE = re.compile(
    r"\b(cookie|privacy policy|terms of service|subscribe|sign in|log in|login|"
    r"all rights reserved|newsletter|advertisement|accept all)\b",
    re.I,
)
CODE_LINE_RE = re.compile(
    r"^\s*(?:"
    r"```|"
    r"from\s+\S+\s+import\s+\S+|"
    r"import\s+\S+|"
    r"def\s+\w+\s*\(|"
    r"class\s+[A-Za-z_]\w*(?:\s*\([^)]*\)\s*:|\s*:|\s*\{)|"
    r"function\s+[A-Za-z_$][\w$]*\s*\(|"
    r"(?:var|let|const)\s+\w+\s*=|"
    r"public\s+static\b|"
    r"#include\s*[<\"]|"
    r"console\.log\s*\(|"
    r"print\s*\(|"
    r"[A-Za-z_]\w*\s*=\s*(?:input|len|range|int|float|str|list|dict|set|np\.|pd\.|[A-Za-z_]\w+\()|"
    r"(?:if|elif|else|for|while|try|except)\b.*:\s*$|"
    r"return\b.+"
    r")",
)
SQL_CODE_LINE_RE = re.compile(
    r"^\s*SELECT\s+.+\s+FROM\b",
    re.I,
)
DOCID_RE = re.compile(r"^(?P<stem>.+)_(?P<row>\d+)$")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--stats-dir", type=Path, required=True)
    ap.add_argument("--examples-dir", type=Path, required=True)
    ap.add_argument("--errors-jsonl", type=Path, required=True)
    ap.add_argument("--max-docs-per-shard", type=int, default=10000)
    ap.add_argument("--batch-size", type=int, default=8192)
    ap.add_argument("--examples-per-category", type=int, default=20)
    ap.add_argument("--example-chars", type=int, default=6000)
    ap.add_argument("--example-seed", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    return ap.parse_args()


def load_manifest(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"manifest is empty: {path}")
    return rows


def write_jsonl(path: Path, rec: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("at", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def count_paragraphs(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return len([p for p in re.split(r"\n\s*\n+", stripped) if p.strip()])


def duplicate_line_ratio(text: str) -> float:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 3:
        return 0.0
    return 1.0 - (len(set(lines)) / len(lines))


def code_line_stats(nonempty_lines: list[str]) -> tuple[int, int, int]:
    code_like_lines = 0
    code_fence_lines = 0
    indented_code_lines = 0
    for line in nonempty_lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            code_fence_lines += 1
            code_like_lines += 1
            continue
        if CODE_LINE_RE.search(line) or SQL_CODE_LINE_RE.search(line):
            code_like_lines += 1
            if line.startswith(("    ", "\t")):
                indented_code_lines += 1
            continue
        if line.startswith(("    ", "\t")) and re.search(r"(==|!=|<=|>=|=>|->|::|[{};=])", stripped):
            code_like_lines += 1
            indented_code_lines += 1
    return code_like_lines, code_fence_lines, indented_code_lines


def structure_features(text: str) -> dict[str, float | int | bool]:
    stripped = text.strip()
    char_count = len(text)
    lines = text.splitlines()
    nonempty_lines = [ln for ln in lines if ln.strip()]
    n_lines = len(lines) if text else 0
    n_nonempty = len(nonempty_lines)
    url_count = len(URL_RE.findall(text))
    tag_count = len(TAG_RE.findall(text))
    entity_count = len(HTML_ENTITY_RE.findall(text))
    boilerplate_hits = len(BOILERPLATE_RE.findall(text))
    boilerplate_strong_hits = len(BOILERPLATE_STRONG_RE.findall(text))
    markdown_lines = sum(
        1 for ln in nonempty_lines
        if ln.lstrip().startswith(("#", "- ", "* ", "> ", "```"))
        or re.match(r"^\s*\d+\.\s+", ln)
        or ("[" in ln and "](" in ln)
    )
    table_lines = sum(1 for ln in nonempty_lines if ln.count("|") >= 2 or ln.count("\t") >= 2)
    indented_lines = sum(1 for ln in nonempty_lines if ln.startswith(("    ", "\t")))
    code_like_lines, code_fence_lines, indented_code_lines = code_line_stats(nonempty_lines)
    brace_count = text.count("{") + text.count("}") + text.count(";")
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    control = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t")

    denom = max(char_count, 1)
    line_denom = max(n_nonempty, 1)
    return {
        "is_empty_or_tiny": len(stripped) < 100,
        "url_count": url_count,
        "tag_count": tag_count,
        "html_entity_count": entity_count,
        "boilerplate_hits": boilerplate_hits,
        "boilerplate_strong_hits": boilerplate_strong_hits,
        "markdown_line_ratio": markdown_lines / line_denom,
        "table_line_ratio": table_lines / line_denom,
        "indented_line_ratio": indented_lines / line_denom,
        "code_like_line_count": code_like_lines,
        "code_fence_line_count": code_fence_lines,
        "indented_code_line_count": indented_code_lines,
        "code_line_ratio": code_like_lines / line_denom,
        "brace_density": brace_count / denom,
        "non_ascii_ratio": non_ascii / denom,
        "control_char_ratio": control / denom,
        "duplicate_line_ratio": duplicate_line_ratio(text),
    }


def flags_and_category(text: str) -> tuple[int, str, dict[str, float | int | bool]]:
    f = structure_features(text)
    char_count = len(text)
    approx_tokens = int(math.ceil(char_count / 4.0))
    html_or_markup = (
        f["tag_count"] >= 5
        or f["html_entity_count"] >= 5
        or "<html" in text[:2000].lower()
        or "</div>" in text[:5000].lower()
    )
    outline_or_markdown = f["markdown_line_ratio"] >= 0.25 and char_count >= 200
    table_or_record = f["table_line_ratio"] >= 0.20 and char_count >= 200
    strong_code = (
        (
            f["code_fence_line_count"] >= 1
            or f["indented_code_line_count"] >= 3
            or (f["code_like_line_count"] >= 6 and f["code_line_ratio"] >= 0.15)
            or (f["code_like_line_count"] >= 2 and f["brace_density"] > 0.010)
        )
        and char_count >= 200
    )
    url_heavy = f["url_count"] >= 5 or (f["url_count"] >= 2 and char_count < 1000)
    boilerplate_signal = (
        f["boilerplate_strong_hits"] >= 3
        or (f["boilerplate_hits"] >= 6 and f["duplicate_line_ratio"] >= 0.10)
    )
    long_tail_outlier = approx_tokens > 8192

    flags = 0
    checks = {
        "empty_or_tiny": bool(f["is_empty_or_tiny"]),
        "html_or_markup_like": html_or_markup,
        "strong_code_like": strong_code,
        "table_or_record_like": table_or_record,
        "outline_or_markdown_like": outline_or_markdown,
        "url_heavy": url_heavy,
        "boilerplate_signal": boilerplate_signal,
        "long_tail_outlier": long_tail_outlier,
    }
    for name, enabled in checks.items():
        if enabled:
            flags |= 1 << FLAG_TO_ID[name]

    for name in PRIMARY_CATEGORY_NAMES[:-1]:
        if checks.get(name, False):
            return flags, name, f
    return flags, "clean_text", f


def metric_arrays_empty() -> dict[str, list[int]]:
    return {
        "char_count": [],
        "byte_count": [],
        "word_count": [],
        "line_count": [],
        "paragraph_count": [],
        "approx_token_count": [],
        "category_id": [],
        "flags": [],
        "row_number": [],
    }


def doc_metrics(text: str) -> tuple[dict[str, int], str, int, dict[str, float | int | bool]]:
    char_count = len(text)
    metrics = {
        "char_count": char_count,
        "byte_count": len(text.encode("utf-8", errors="ignore")),
        "word_count": len(WORD_RE.findall(text)),
        "line_count": text.count("\n") + 1 if text else 0,
        "paragraph_count": count_paragraphs(text),
        "approx_token_count": int(math.ceil(char_count / 4.0)),
    }
    flags, category, features = flags_and_category(text)
    return metrics, category, flags, features


def docid_sort_key(docid: str) -> tuple[str, int]:
    match = DOCID_RE.match(docid)
    if not match:
        return docid, -1
    return match.group("stem"), int(match.group("row"))


class CategoryReservoir:
    """Uniformly sample up to k examples per category during streaming."""

    def __init__(self, limit: int, example_chars: int, seed: int) -> None:
        self.limit = max(limit, 0)
        self.example_chars = max(example_chars, 0)
        self.seed = seed
        self.seen: Counter = Counter()
        self.samples: dict[str, list[dict[str, Any]]] = {name: [] for name in PRIMARY_CATEGORY_NAMES}
        self.rngs = {name: random.Random(f"{seed}:{name}") for name in PRIMARY_CATEGORY_NAMES}

    @property
    def total_seen(self) -> int:
        return sum(self.seen.values())

    def offer(
        self,
        category: str,
        docid: str,
        text: str,
        metrics: dict[str, int],
        features: dict[str, float | int | bool],
    ) -> None:
        if self.limit <= 0:
            return
        self.seen[category] += 1
        seen = self.seen[category]
        record = {
            "docid": docid,
            "category": category,
            "metrics": metrics,
            "features": features,
            "category_seen_ordinal": seen,
            "clipped_text": text[:self.example_chars],
        }
        bucket = self.samples[category]
        if len(bucket) < self.limit:
            bucket.append(record)
            return
        replace_at = self.rngs[category].randrange(seen)
        if replace_at < self.limit:
            bucket[replace_at] = record

    def write(self, examples_dir: Path) -> None:
        examples_dir.mkdir(parents=True, exist_ok=True)
        for category in PRIMARY_CATEGORY_NAMES:
            out_dir = examples_dir / category
            out_dir.mkdir(parents=True, exist_ok=True)
            for stale in out_dir.glob("*.txt"):
                stale.unlink()
            records = sorted(self.samples[category], key=lambda rec: docid_sort_key(rec["docid"]))
            for idx, rec in enumerate(records, start=1):
                path = out_dir / f"{idx:03d}_{rec['docid']}.txt"
                header = {
                    "docid": rec["docid"],
                    "category": category,
                    "metrics": rec["metrics"],
                    "features": rec["features"],
                    "sample_method": "per_category_reservoir_sampling",
                    "example_seed": self.seed,
                    "examples_per_category": self.limit,
                    "category_seen_total": int(self.seen[category]),
                    "category_seen_ordinal": int(rec["category_seen_ordinal"]),
                    "selection_index": idx,
                    "truncated_to_chars": self.example_chars,
                }
                path.write_text(
                    json.dumps(header, indent=2, sort_keys=True) + "\n\n" + rec["clipped_text"],
                    encoding="utf-8",
                    errors="replace",
                )
            print(
                f"[profile] examples category={category} "
                f"seen={int(self.seen[category])} saved={len(records)}",
                flush=True,
            )


def profile_one_shard(args: argparse.Namespace, filename: str,
                      example_sampler: CategoryReservoir) -> dict[str, Any] | None:
    stem = Path(filename).stem
    parquet_path = args.raw_dir / filename
    shard_dir = args.stats_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    metrics_npz = shard_dir / f"{stem}.metrics.npz"
    summary_json = shard_dir / f"{stem}.summary.json"

    if metrics_npz.exists() and summary_json.exists() and not args.force:
        print(f"[profile] reuse {filename}", flush=True)
        return json.loads(summary_json.read_text(encoding="utf-8"))

    if not parquet_path.exists() or parquet_path.stat().st_size == 0:
        write_jsonl(args.errors_jsonl, {
            "filename": filename,
            "stage": "open",
            "error": f"missing or empty parquet: {parquet_path}",
        })
        print(f"[profile] missing {filename}", flush=True)
        return None

    t0 = time.time()
    arrays = metric_arrays_empty()
    feature_sums: Counter = Counter()
    primary_categories: Counter = Counter()
    flag_counts: Counter = Counter()
    n_docs = 0
    row_seen = 0
    n_errors = 0

    try:
        pf = pq.ParquetFile(parquet_path)
        schema_names = set(pf.schema_arrow.names)
        if "text" not in schema_names:
            raise ValueError(f"parquet has no text column; columns={sorted(schema_names)}")
        for batch in pf.iter_batches(batch_size=args.batch_size, columns=["text"]):
            texts = batch.column("text").to_pylist()
            for text in texts:
                if args.max_docs_per_shard > 0 and n_docs >= args.max_docs_per_shard:
                    break
                row_number = row_seen
                row_seen += 1
                docid = f"{stem}_{row_number}"
                try:
                    if text is None:
                        text = ""
                    if not isinstance(text, str):
                        text = str(text)
                    metrics, category, flags, features = doc_metrics(text)
                    for k, v in metrics.items():
                        arrays[k].append(int(v))
                    arrays["category_id"].append(CATEGORY_TO_ID[category])
                    arrays["flags"].append(flags)
                    arrays["row_number"].append(row_number)
                    primary_categories[category] += 1
                    for name in FLAG_NAMES:
                        if flags & (1 << FLAG_TO_ID[name]):
                            flag_counts[name] += 1
                    for fk, fv in features.items():
                        if isinstance(fv, bool):
                            feature_sums[fk] += int(fv)
                        elif isinstance(fv, (int, float)):
                            feature_sums[fk] += float(fv)
                    example_sampler.offer(category, docid, text, metrics, features)
                    n_docs += 1
                except Exception as e:  # noqa: BLE001
                    n_errors += 1
                    write_jsonl(args.errors_jsonl, {
                        "filename": filename,
                        "stage": "row",
                        "row_number": row_number,
                        "error": repr(e),
                    })
            if args.max_docs_per_shard > 0 and n_docs >= args.max_docs_per_shard:
                break
    except Exception as e:  # noqa: BLE001
        write_jsonl(args.errors_jsonl, {
            "filename": filename,
            "stage": "shard",
            "error": repr(e),
        })
        print(f"[profile] FAILED {filename}: {e!r}", flush=True)
        return None

    if n_docs == 0:
        write_jsonl(args.errors_jsonl, {
            "filename": filename,
            "stage": "summary",
            "error": "no documents processed",
        })
        return None

    tmp_npz = metrics_npz.with_suffix(".npz.tmp")
    tmp_summary = summary_json.with_suffix(".json.tmp")
    np.savez_compressed(
        tmp_npz,
        char_count=np.asarray(arrays["char_count"], dtype=np.uint64),
        byte_count=np.asarray(arrays["byte_count"], dtype=np.uint64),
        word_count=np.asarray(arrays["word_count"], dtype=np.uint32),
        line_count=np.asarray(arrays["line_count"], dtype=np.uint32),
        paragraph_count=np.asarray(arrays["paragraph_count"], dtype=np.uint32),
        approx_token_count=np.asarray(arrays["approx_token_count"], dtype=np.uint32),
        category_id=np.asarray(arrays["category_id"], dtype=np.uint8),
        flags=np.asarray(arrays["flags"], dtype=np.uint16),
        row_number=np.asarray(arrays["row_number"], dtype=np.uint32),
    )
    # np.savez_compressed appends .npz if the path is a string without that suffix.
    if not tmp_npz.exists() and Path(str(tmp_npz) + ".npz").exists():
        Path(str(tmp_npz) + ".npz").replace(tmp_npz)

    summary = {
        "filename": filename,
        "path": str(parquet_path),
        "processed_docs": n_docs,
        "row_errors": n_errors,
        "elapsed_s": round(time.time() - t0, 3),
        "primary_categories": dict(primary_categories),
        "flag_counts": dict(flag_counts),
        "feature_means": {k: v / n_docs for k, v in feature_sums.items()},
        "metrics_npz": str(metrics_npz),
    }
    tmp_summary.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_npz, metrics_npz)
    os.replace(tmp_summary, summary_json)
    print(f"[profile] done {filename} docs={n_docs} elapsed={summary['elapsed_s']}s", flush=True)
    return summary


def percentiles(values: np.ndarray) -> dict[str, float]:
    if values.size == 0:
        return {}
    ps = [0, 1, 5, 25, 50, 75, 90, 95, 99, 100]
    qs = np.percentile(values, ps)
    names = ["p0", "p1", "p5", "p25", "p50", "p75", "p90", "p95", "p99", "max"]
    return {name: float(val) for name, val in zip(names, qs)}


def aggregate(args: argparse.Namespace, shard_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = [
        "char_count",
        "byte_count",
        "word_count",
        "line_count",
        "paragraph_count",
        "approx_token_count",
    ]
    values: dict[str, list[np.ndarray]] = {name: [] for name in metric_names}
    categories = Counter()
    flags = Counter()
    n_docs = 0

    for summary in shard_summaries:
        npz = np.load(summary["metrics_npz"])
        n = int(npz["char_count"].size)
        n_docs += n
        for name in metric_names:
            values[name].append(npz[name])
        for cid in npz["category_id"]:
            categories[PRIMARY_CATEGORY_NAMES[int(cid)]] += 1
        for mask in npz["flags"]:
            mask_i = int(mask)
            for name in FLAG_NAMES:
                if mask_i & (1 << FLAG_TO_ID[name]):
                    flags[name] += 1

    if n_docs == 0:
        raise SystemExit("no documents processed; cannot aggregate")

    metric_stats = {}
    for name, chunks in values.items():
        arr = np.concatenate(chunks) if chunks else np.asarray([], dtype=np.uint64)
        metric_stats[name] = {
            "mean": float(np.mean(arr)) if arr.size else 0.0,
            "percentiles": percentiles(arr),
        }

    stats = {
        "processed_shards": len(shard_summaries),
        "processed_docs": n_docs,
        "max_docs_per_shard": args.max_docs_per_shard,
        "category_names": PRIMARY_CATEGORY_NAMES,
        "flag_names": FLAG_NAMES,
        "structure_rule_version": "tightened-primary",
        "primary_category_counts": dict(categories),
        "flag_counts": dict(flags),
        "primary_category_rates": {k: v / n_docs for k, v in categories.items()},
        "flag_rates": {k: v / n_docs for k, v in flags.items()},
        "metrics": metric_stats,
        "shards": shard_summaries,
    }
    out = args.stats_dir / "corpus_stats.json"
    out.write_text(json.dumps(stats, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[profile] wrote aggregate stats {out}", flush=True)
    return stats


def main() -> int:
    args = parse_args()
    args.stats_dir.mkdir(parents=True, exist_ok=True)
    args.examples_dir.mkdir(parents=True, exist_ok=True)
    args.errors_jsonl.parent.mkdir(parents=True, exist_ok=True)
    if args.errors_jsonl.exists() and args.force:
        args.errors_jsonl.unlink()

    rows = load_manifest(args.manifest)
    example_sampler = CategoryReservoir(
        limit=args.examples_per_category,
        example_chars=args.example_chars,
        seed=args.example_seed,
    )
    summaries = []
    t0 = time.time()
    for i, row in enumerate(rows, start=1):
        filename = row["filename"]
        print(f"[profile] {i}/{len(rows)} {filename}", flush=True)
        summary = profile_one_shard(args, filename, example_sampler)
        if summary is not None:
            summaries.append(summary)
    if example_sampler.total_seen > 0:
        example_sampler.write(args.examples_dir)
    else:
        print("[profile] no rows scanned for examples; existing examples left unchanged", flush=True)
    stats = aggregate(args, summaries)
    print(
        f"[profile] complete shards={stats['processed_shards']} docs={stats['processed_docs']} "
        f"elapsed={time.time() - t0:.1f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
