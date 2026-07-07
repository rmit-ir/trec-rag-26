#!/usr/bin/env python3
"""Compare chunking strategies over an evaluation sample."""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pyarrow.parquet as pq


@dataclass(frozen=True)
class ChunkSpan:
    start: int
    end: int

    @property
    def chars(self) -> int:
        return max(0, self.end - self.start)


STRATEGY_CONFIGS: dict[str, dict[str, Any]] = {
    "first_512": {
        "kind": "first",
        "max_tokens": 512,
    },
    "first_1024": {
        "kind": "first",
        "max_tokens": 1024,
    },
    "fixed_512_overlap_64": {
        "kind": "fixed",
        "chunk_tokens": 512,
        "overlap_tokens": 64,
    },
    "fixed_1024_overlap_128": {
        "kind": "fixed",
        "chunk_tokens": 1024,
        "overlap_tokens": 128,
    },
    "paragraph_aware_512": {
        "kind": "paragraph",
        "chunk_tokens": 512,
    },
    "paragraph_aware_1024": {
        "kind": "paragraph",
        "chunk_tokens": 1024,
    },
    "hybrid_short_whole_long_chunk": {
        "kind": "hybrid",
        "short_whole_tokens": 512,
        "paragraph_chunk_tokens": 1024,
        "max_chunks_per_doc": 128,
        "cap_policy": "head_tail_anchors_uniform_middle",
        "head_anchor_chunks": 8,
        "tail_anchor_chunks": 8,
    },
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample-index", type=Path, required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--stats-dir", type=Path, required=True)
    ap.add_argument("--examples-dir", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--seed", type=int, default=20260703)
    ap.add_argument("--example-docs-per-strategy", type=int, default=8)
    ap.add_argument("--example-chars", type=int, default=1200)
    ap.add_argument("--force", action="store_true")
    return ap.parse_args()


def approx_tokens_from_chars(chars: int) -> int:
    return int(math.ceil(max(chars, 0) / 4.0))


def approx_tokens(text: str) -> int:
    return approx_tokens_from_chars(len(text))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def percentile(values: list[float] | list[int], q: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def percentiles(values: list[float] | list[int]) -> dict[str, float | None]:
    return {
        "p50": percentile(values, 50),
        "p75": percentile(values, 75),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": float(max(values)) if values else None,
    }


def first_spans(n_chars: int, max_tokens: int) -> list[ChunkSpan]:
    if n_chars <= 0:
        return []
    return [ChunkSpan(0, min(n_chars, max_tokens * 4))]


def fixed_spans(n_chars: int, chunk_tokens: int, overlap_tokens: int) -> list[ChunkSpan]:
    if n_chars <= 0:
        return []
    chunk_chars = chunk_tokens * 4
    overlap_chars = overlap_tokens * 4
    step = chunk_chars - overlap_chars
    if step <= 0:
        raise ValueError(f"invalid fixed chunk config: chunk={chunk_tokens}, overlap={overlap_tokens}")

    spans: list[ChunkSpan] = []
    start = 0
    while start < n_chars:
        end = min(n_chars, start + chunk_chars)
        spans.append(ChunkSpan(start, end))
        if end >= n_chars:
            break
        start += step
    return spans


def paragraph_block_spans(text: str) -> list[ChunkSpan]:
    n_chars = len(text)
    if n_chars <= 0:
        return []
    spans: list[ChunkSpan] = []
    start = 0
    for match in re.finditer(r"\n\s*\n+", text):
        end = match.end()
        if end > start:
            spans.append(ChunkSpan(start, end))
        start = end
    if start < n_chars:
        spans.append(ChunkSpan(start, n_chars))
    return spans or [ChunkSpan(0, n_chars)]


def paragraph_spans(text: str, chunk_tokens: int) -> list[ChunkSpan]:
    n_chars = len(text)
    if n_chars <= 0:
        return []
    max_chars = chunk_tokens * 4
    out: list[ChunkSpan] = []
    current_start: int | None = None
    current_end: int | None = None

    def flush() -> None:
        nonlocal current_start, current_end
        if current_start is not None and current_end is not None and current_end > current_start:
            out.append(ChunkSpan(current_start, current_end))
        current_start = None
        current_end = None

    for block in paragraph_block_spans(text):
        if block.chars > max_chars:
            flush()
            split_start = block.start
            while split_start < block.end:
                split_end = min(block.end, split_start + max_chars)
                out.append(ChunkSpan(split_start, split_end))
                split_start = split_end
            continue

        if current_start is None:
            current_start = block.start
            current_end = block.end
            continue
        assert current_end is not None
        if block.end - current_start <= max_chars:
            current_end = block.end
        else:
            flush()
            current_start = block.start
            current_end = block.end
    flush()
    return out


def evenly_spaced_indices(start: int, stop: int, k: int) -> list[int]:
    if k <= 0 or stop <= start:
        return []
    n_items = stop - start
    if k >= n_items:
        return list(range(start, stop))
    indices = [
        start + min(n_items - 1, int((i + 0.5) * n_items / k))
        for i in range(k)
    ]
    deduped = sorted(set(indices))
    if len(deduped) < k:
        for idx in range(start, stop):
            if idx not in deduped:
                deduped.append(idx)
                if len(deduped) == k:
                    break
    return sorted(deduped)


def representative_indices(n_items: int, max_items: int = 8) -> list[int]:
    if n_items <= 0:
        return []
    if n_items <= max_items:
        return list(range(n_items))
    if max_items < 4:
        return evenly_spaced_indices(0, n_items, max_items)
    selected = {0, 1, n_items - 2, n_items - 1}
    middle_slots = max_items - len(selected)
    selected.update(evenly_spaced_indices(2, n_items - 2, middle_slots))
    return sorted(selected)


def cap_with_anchors_uniform_middle(
    spans: list[ChunkSpan],
    max_chunks: int,
    head_anchor_chunks: int,
    tail_anchor_chunks: int,
) -> list[ChunkSpan]:
    if len(spans) <= max_chunks:
        return spans
    if max_chunks <= 0:
        return []

    head_n = min(head_anchor_chunks, max_chunks // 2, len(spans))
    remaining_after_head = max_chunks - head_n
    tail_n = min(tail_anchor_chunks, remaining_after_head, max(0, len(spans) - head_n))
    selected = set(range(head_n))
    selected.update(range(len(spans) - tail_n, len(spans)))

    middle_start = head_n
    middle_stop = len(spans) - tail_n
    middle_slots = max_chunks - len(selected)
    selected.update(evenly_spaced_indices(middle_start, middle_stop, middle_slots))
    return [spans[i] for i in sorted(selected)[:max_chunks]]


def chunk_spans(text: str, strategy_name: str) -> list[ChunkSpan]:
    cfg = STRATEGY_CONFIGS[strategy_name]
    kind = cfg["kind"]
    n_chars = len(text)
    if kind == "first":
        return first_spans(n_chars, int(cfg["max_tokens"]))
    if kind == "fixed":
        return fixed_spans(n_chars, int(cfg["chunk_tokens"]), int(cfg["overlap_tokens"]))
    if kind == "paragraph":
        return paragraph_spans(text, int(cfg["chunk_tokens"]))
    if kind == "hybrid":
        if approx_tokens(text) <= int(cfg["short_whole_tokens"]):
            return [ChunkSpan(0, n_chars)] if n_chars > 0 else []
        spans = paragraph_spans(text, int(cfg["paragraph_chunk_tokens"]))
        return cap_with_anchors_uniform_middle(
            spans,
            int(cfg["max_chunks_per_doc"]),
            int(cfg["head_anchor_chunks"]),
            int(cfg["tail_anchor_chunks"]),
        )
    raise ValueError(f"unknown strategy kind: {kind}")


def covered_chars(spans: list[ChunkSpan], n_chars: int) -> int:
    if not spans or n_chars <= 0:
        return 0
    clipped = sorted((max(0, s.start), min(n_chars, s.end)) for s in spans if s.end > s.start)
    if not clipped:
        return 0
    total = 0
    cur_start, cur_end = clipped[0]
    for start, end in clipped[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            total += cur_end - cur_start
            cur_start, cur_end = start, end
    total += cur_end - cur_start
    return total


class MetricAccumulator:
    def __init__(self) -> None:
        self.docs = 0
        self.total_chunks = 0
        self.total_original_tokens = 0
        self.total_unique_covered_tokens = 0
        self.total_chunk_tokens = 0
        self.total_overlap_tokens = 0
        self.truncated_docs = 0
        self.empty_or_tiny_chunks = 0
        self.chunks_per_doc: list[int] = []
        self.tokens_per_chunk: list[int] = []
        self.coverage_rates: list[float] = []
        self.overlap_overhead_rates: list[float] = []

    def add(self, rec: dict[str, Any], text: str, spans: list[ChunkSpan]) -> dict[str, Any]:
        n_chars = len(text)
        original_tokens = max(0, int(rec["approx_token_count"]))
        chunk_tokens = [approx_tokens_from_chars(span.chars) for span in spans]
        unique_covered = min(original_tokens, approx_tokens_from_chars(covered_chars(spans, n_chars)))
        total_chunk_tokens = sum(chunk_tokens)
        overlap_tokens = max(0, total_chunk_tokens - unique_covered)
        coverage_rate = 1.0 if original_tokens == 0 else unique_covered / original_tokens
        truncated = coverage_rate < 0.999
        overlap_rate = 0.0 if unique_covered == 0 else overlap_tokens / unique_covered
        empty_or_tiny = sum(
            1
            for span, toks in zip(spans, chunk_tokens)
            if toks <= 8 or not text[span.start:span.end].strip()
        )

        self.docs += 1
        self.total_chunks += len(spans)
        self.total_original_tokens += original_tokens
        self.total_unique_covered_tokens += unique_covered
        self.total_chunk_tokens += total_chunk_tokens
        self.total_overlap_tokens += overlap_tokens
        self.truncated_docs += int(truncated)
        self.empty_or_tiny_chunks += empty_or_tiny
        self.chunks_per_doc.append(len(spans))
        self.tokens_per_chunk.extend(chunk_tokens)
        self.coverage_rates.append(coverage_rate)
        self.overlap_overhead_rates.append(overlap_rate)

        return {
            "chunks": len(spans),
            "chunk_tokens": total_chunk_tokens,
            "unique_covered_tokens": unique_covered,
            "coverage_rate": coverage_rate,
            "truncated": truncated,
            "overlap_tokens": overlap_tokens,
            "empty_or_tiny_chunks": empty_or_tiny,
        }

    def summary(self) -> dict[str, Any]:
        docs = max(1, self.docs)
        total_original = max(1, self.total_original_tokens)
        total_chunks = max(1, self.total_chunks)
        return {
            "docs": self.docs,
            "total_chunks": self.total_chunks,
            "chunks_per_doc_mean": self.total_chunks / docs,
            "chunks_per_doc_percentiles": percentiles(self.chunks_per_doc),
            "tokens_per_chunk_mean": self.total_chunk_tokens / total_chunks,
            "tokens_per_chunk_percentiles": percentiles(self.tokens_per_chunk),
            "coverage_rate_mean": sum(self.coverage_rates) / docs,
            "coverage_rate_percentiles": {
                "p1": percentile(self.coverage_rates, 1),
                "p5": percentile(self.coverage_rates, 5),
                "p50": percentile(self.coverage_rates, 50),
                "p95": percentile(self.coverage_rates, 95),
            },
            "retained_token_rate": self.total_unique_covered_tokens / total_original,
            "truncated_docs": self.truncated_docs,
            "truncation_rate": self.truncated_docs / docs,
            "chunk_token_multiplier": self.total_chunk_tokens / total_original,
            "overlap_overhead_rate": self.total_overlap_tokens / max(1, self.total_unique_covered_tokens),
            "empty_or_tiny_chunks": self.empty_or_tiny_chunks,
            "empty_or_tiny_chunk_rate": self.empty_or_tiny_chunks / total_chunks,
        }


class StrategyAccumulator:
    def __init__(self) -> None:
        self.overall = MetricAccumulator()
        self.by_length_bucket: dict[str, MetricAccumulator] = defaultdict(MetricAccumulator)
        self.by_primary_category: dict[str, MetricAccumulator] = defaultdict(MetricAccumulator)
        self.long_doc = MetricAccumulator()

    def add(self, rec: dict[str, Any], text: str, spans: list[ChunkSpan]) -> dict[str, Any]:
        doc_metric = self.overall.add(rec, text, spans)
        self.by_length_bucket[rec["length_bucket"]].add(rec, text, spans)
        self.by_primary_category[rec["primary_category"]].add(rec, text, spans)
        if rec["length_bucket"] == ">8192":
            self.long_doc.add(rec, text, spans)
        return doc_metric

    def summary(self) -> dict[str, Any]:
        return {
            "overall": self.overall.summary(),
            "by_length_bucket": {
                key: acc.summary() for key, acc in sorted(self.by_length_bucket.items())
            },
            "by_primary_category": {
                key: acc.summary() for key, acc in sorted(self.by_primary_category.items())
            },
            "long_doc_behavior": self.long_doc.summary() if self.long_doc.docs else None,
        }


class PriorityExamples:
    def __init__(self, limit: int, seed: int) -> None:
        self.limit = limit
        self.seed = seed
        self.seen: Counter[str] = Counter()
        self.items: dict[str, list[tuple[tuple[int, int, int], dict[str, Any]]]] = defaultdict(list)

    def rank(self, rec: dict[str, Any], doc_metric: dict[str, Any]) -> tuple[int, int, int]:
        return (
            int(bool(doc_metric["truncated"])),
            int(rec["length_bucket"] == ">8192"),
            int(rec["approx_token_count"]),
        )

    def consider(
        self,
        strategy: str,
        rec: dict[str, Any],
        text: str,
        spans: list[ChunkSpan],
        doc_metric: dict[str, Any],
        example_chars: int,
    ) -> None:
        if self.limit <= 0:
            return
        interesting = (
            doc_metric["truncated"]
            or doc_metric["chunks"] > 1
            or rec["length_bucket"] == ">8192"
        )
        if not interesting:
            return
        self.seen[strategy] += 1
        item = {
            "doc": rec,
            "metric": doc_metric,
            "original_preview": text[:example_chars],
            "chunks": [
                {
                    "selected_chunk_position": i + 1,
                    "start": span.start,
                    "end": span.end,
                    "approx_tokens": approx_tokens_from_chars(span.chars),
                    "preview": text[span.start:span.end][:example_chars],
                }
                for i, span in [
                    (idx, spans[idx])
                    for idx in representative_indices(len(spans), max_items=8)
                ]
            ],
            "omitted_chunks": max(0, len(spans) - min(len(spans), 8)),
        }
        ranked_item = (self.rank(rec, doc_metric), item)
        bucket = self.items[strategy]
        if len(bucket) < self.limit:
            bucket.append(ranked_item)
            return
        lowest_i, lowest = min(
            enumerate(bucket),
            key=lambda pair: (pair[1][0], pair[1][1]["doc"]["docid"]),
        )
        if (ranked_item[0], item["doc"]["docid"]) > (lowest[0], lowest[1]["doc"]["docid"]):
            bucket[lowest_i] = ranked_item

    def write(self, examples_dir: Path) -> dict[str, Any]:
        examples_dir.mkdir(parents=True, exist_ok=True)
        summary: dict[str, Any] = {}
        for strategy, ranked_items in sorted(self.items.items()):
            items = [
                item for _rank, item in sorted(
                    ranked_items,
                    key=lambda pair: (pair[0], pair[1]["doc"]["docid"]),
                    reverse=True,
                )
            ]
            strategy_dir = examples_dir / strategy
            strategy_dir.mkdir(parents=True, exist_ok=True)
            summary[strategy] = {
                "seen_interesting_docs": self.seen[strategy],
                "saved_examples": len(items),
                "dir": str(strategy_dir),
            }
            for i, item in enumerate(items, start=1):
                docid = item["doc"]["docid"]
                path = strategy_dir / f"{i:03d}_{docid}.txt"
                with path.open("wt", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "doc": item["doc"],
                        "metric": item["metric"],
                        "omitted_chunks": item["omitted_chunks"],
                    }, sort_keys=True) + "\n\n")
                    f.write("## Original preview\n\n")
                    f.write(item["original_preview"])
                    f.write("\n\n## Chunk previews\n")
                    for chunk in item["chunks"]:
                        f.write("\n")
                        f.write(json.dumps({k: v for k, v in chunk.items() if k != "preview"}, sort_keys=True))
                        f.write("\n")
                        f.write(chunk["preview"])
                        f.write("\n")
        return summary


def group_records_by_shard(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_shard: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        by_shard[rec["filename"]].append(rec)
    for filename in by_shard:
        by_shard[filename].sort(key=lambda r: int(r["row_number"]))
    return dict(sorted(by_shard.items()))


def load_text_column(path: Path) -> list[str]:
    table = pq.read_table(path, columns=["text"])
    col = table.column("text")
    out: list[str] = []
    for value in col:
        text = value.as_py()
        out.append(text if isinstance(text, str) else "")
    return out


def main() -> None:
    args = parse_args()
    started = time.time()
    summary_path = args.stats_dir / "chunking_summary.json"
    if summary_path.exists() and not args.force:
        raise SystemExit(f"output already exists; use --force to overwrite: {summary_path}")

    args.stats_dir.mkdir(parents=True, exist_ok=True)
    if args.force and args.examples_dir.exists():
        shutil.rmtree(args.examples_dir)
    args.examples_dir.mkdir(parents=True, exist_ok=True)

    records = read_jsonl(args.sample_index)
    if not records:
        raise SystemExit(f"sample index is empty: {args.sample_index}")
    records_by_shard = group_records_by_shard(records)
    strategies = list(STRATEGY_CONFIGS)
    accs = {name: StrategyAccumulator() for name in strategies}
    examples = PriorityExamples(args.example_docs_per_strategy, args.seed)
    errors: list[dict[str, Any]] = []

    processed_docs = 0
    for shard_i, (filename, shard_records) in enumerate(records_by_shard.items(), start=1):
        raw_path = args.raw_dir / filename
        print(f"[compare_chunkers] {shard_i}/{len(records_by_shard)} {filename} docs={len(shard_records)}")
        try:
            texts = load_text_column(raw_path)
        except Exception as exc:  # noqa: BLE001
            errors.append({"filename": filename, "error": repr(exc)})
            continue
        for rec in shard_records:
            row_number = int(rec["row_number"])
            if row_number >= len(texts):
                errors.append({
                    "filename": filename,
                    "row_number": row_number,
                    "error": f"row_number out of range for shard rows={len(texts)}",
                })
                continue
            text = texts[row_number]
            for strategy in strategies:
                spans = chunk_spans(text, strategy)
                doc_metric = accs[strategy].add(rec, text, spans)
                examples.consider(strategy, rec, text, spans, doc_metric, args.example_chars)
            processed_docs += 1

    example_summary = examples.write(args.examples_dir)
    summary = {
        "run_id": args.run_id,
        "sample_index": str(args.sample_index),
        "raw_dir": str(args.raw_dir),
        "processed_docs": processed_docs,
        "input_docs": len(records),
        "processed_shards": len(records_by_shard),
        "strategies": {
            name: {
                "config": STRATEGY_CONFIGS[name],
                **acc.summary(),
            }
            for name, acc in accs.items()
        },
        "example_summary": example_summary,
        "errors": errors,
        "elapsed_s": round(time.time() - started, 3),
    }
    write_json(summary_path, summary)
    if errors:
        write_json(args.stats_dir / "errors.json", {"errors": errors})

    print(f"[compare_chunkers] wrote {summary_path}")
    print(f"[compare_chunkers] processed_docs={processed_docs} input_docs={len(records)} errors={len(errors)}")
    print(f"[compare_chunkers] elapsed_s={summary['elapsed_s']}")


if __name__ == "__main__":
    main()
