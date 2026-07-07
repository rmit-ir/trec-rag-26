#!/usr/bin/env python3
"""Build deterministic document indexes for chunking comparison."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np


LENGTH_BUCKETS: list[tuple[str, int | None, int | None]] = [
    ("<=128", None, 128),
    ("129-256", 129, 256),
    ("257-512", 257, 512),
    ("513-1024", 513, 1024),
    ("1025-2048", 1025, 2048),
    ("2049-4096", 2049, 4096),
    ("4097-8192", 4097, 8192),
    (">8192", 8193, None),
]

MODE_TARGET_DOCS = {
    "smoke": 500,
    "sample": 5000,
    "onepct": None,
}

MODE_FORCE_LONGEST_DOCS = {
    "smoke": 20,
    "sample": 100,
    "onepct": 0,
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=sorted(MODE_TARGET_DOCS), required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--seed", type=int, default=20260703)
    ap.add_argument("--target-docs", type=int, default=None)
    ap.add_argument("--force-longest-docs", type=int, default=None)
    ap.add_argument("--profile-manifest", type=Path, required=True)
    ap.add_argument("--profile-stats-dir", type=Path, required=True)
    ap.add_argument("--out-root", type=Path, default=Path("data/chunking-profile"))
    ap.add_argument("--force", action="store_true")
    return ap.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def stable_int(text: str) -> int:
    return int(hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest(), 16)


def bucket_for_tokens(tokens: int) -> str:
    for name, low, high in LENGTH_BUCKETS:
        if (low is None or tokens >= low) and (high is None or tokens <= high):
            return name
    raise ValueError(f"no length bucket for tokens={tokens}")


def flag_names_from_bits(bits: int, flag_names: list[str]) -> list[str]:
    return [name for i, name in enumerate(flag_names) if bits & (1 << i)]


def record_from_arrays(
    *,
    filename: str,
    shard_index: int,
    sample_position: int,
    row_i: int,
    arrays: dict[str, np.ndarray],
    category_names: list[str],
    flag_names: list[str],
) -> dict[str, Any]:
    row_number = int(arrays["row_number"][row_i])
    category_id = int(arrays["category_id"][row_i])
    flags = int(arrays["flags"][row_i])
    approx_tokens = int(arrays["approx_token_count"][row_i])
    return {
        "docid": f"{Path(filename).stem}_{row_number}",
        "filename": filename,
        "shard_index": shard_index,
        "sample_position": sample_position,
        "row_number": row_number,
        "char_count": int(arrays["char_count"][row_i]),
        "byte_count": int(arrays["byte_count"][row_i]),
        "word_count": int(arrays["word_count"][row_i]),
        "line_count": int(arrays["line_count"][row_i]),
        "paragraph_count": int(arrays["paragraph_count"][row_i]),
        "approx_token_count": approx_tokens,
        "length_bucket": bucket_for_tokens(approx_tokens),
        "primary_category": category_names[category_id],
        "category_id": category_id,
        "flags": flags,
        "flag_names": flag_names_from_bits(flags, flag_names),
    }


def iter_profile_records(
    *,
    manifest_rows: list[dict[str, Any]],
    stats_dir: Path,
    category_names: list[str],
    flag_names: list[str],
) -> Any:
    shard_stats_dir = stats_dir / "shards"
    for manifest in manifest_rows:
        filename = manifest["filename"]
        metrics_path = shard_stats_dir / f"{Path(filename).stem}.metrics.npz"
        if not metrics_path.exists():
            raise FileNotFoundError(f"missing per-shard metrics: {metrics_path}")
        with np.load(metrics_path) as loaded:
            arrays = {name: loaded[name] for name in loaded.files}
            n_rows = len(arrays["row_number"])
            for row_i in range(n_rows):
                yield record_from_arrays(
                    filename=filename,
                    shard_index=int(manifest["shard_index"]),
                    sample_position=int(manifest["sample_position"]),
                    row_i=row_i,
                    arrays=arrays,
                    category_names=category_names,
                    flag_names=flag_names,
                )


def group_key(rec: dict[str, Any]) -> tuple[str, str]:
    return rec["length_bucket"], rec["primary_category"]


def choose_stratified(
    records: list[dict[str, Any]],
    target_docs: int,
    seed: int,
    force_longest_docs: int,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        groups[group_key(rec)].append(rec)

    nonempty_keys = sorted(groups)
    if target_docs >= len(records):
        return sorted(records, key=lambda r: (r["filename"], r["row_number"]))
    if target_docs < len(nonempty_keys):
        raise ValueError(
            f"target_docs={target_docs} is smaller than non-empty strata={len(nonempty_keys)}"
        )

    selected_docids: set[str] = set()
    selected: list[dict[str, Any]] = []
    if force_longest_docs > 0:
        longest = sorted(
            records,
            key=lambda r: (-int(r["approx_token_count"]), r["filename"], int(r["row_number"])),
        )
        for rec in longest[: min(force_longest_docs, target_docs)]:
            selected_docids.add(rec["docid"])
            selected.append(rec)

    remaining_target = target_docs - len(selected)
    base_quota = max(0, remaining_target // len(nonempty_keys))
    remainder = max(0, remaining_target % len(nonempty_keys))
    ranked_keys = sorted(nonempty_keys, key=lambda k: stable_int(f"{seed}:{k[0]}:{k[1]}"))

    def take_from_group(key: tuple[str, str], quota: int) -> None:
        if quota <= 0:
            return
        candidates = sorted(groups[key], key=lambda r: (r["filename"], r["row_number"]))
        rng = random.Random(seed + stable_int(f"{key[0]}:{key[1]}"))
        rng.shuffle(candidates)
        taken = 0
        for rec in candidates:
            if rec["docid"] in selected_docids:
                continue
            selected_docids.add(rec["docid"])
            selected.append(rec)
            taken += 1
            if taken >= quota:
                return

    for key in nonempty_keys:
        take_from_group(key, base_quota)
    for key in ranked_keys[:remainder]:
        take_from_group(key, 1)

    remaining = target_docs - len(selected)
    if remaining > 0:
        pool = [rec for rec in records if rec["docid"] not in selected_docids]
        pool = sorted(pool, key=lambda r: (stable_int(f"{seed}:{r['docid']}"), r["docid"]))
        for rec in pool[:remaining]:
            selected_docids.add(rec["docid"])
            selected.append(rec)

    return sorted(selected, key=lambda r: (r["filename"], r["row_number"]))


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_bucket = Counter(r["length_bucket"] for r in records)
    by_category = Counter(r["primary_category"] for r in records)
    by_group = Counter(f"{r['length_bucket']}|{r['primary_category']}" for r in records)
    by_shard = Counter(r["filename"] for r in records)
    long_docs = sum(1 for r in records if r["length_bucket"] == ">8192")
    return {
        "selected_docs": len(records),
        "length_bucket_counts": dict(sorted(by_bucket.items())),
        "primary_category_counts": dict(sorted(by_category.items())),
        "stratum_counts": dict(sorted(by_group.items())),
        "shard_counts": dict(sorted(by_shard.items())),
        "long_tail_docs": long_docs,
    }


def main() -> None:
    args = parse_args()
    started = time.time()
    target_docs = args.target_docs
    if target_docs is None:
        target_docs = MODE_TARGET_DOCS[args.mode]
    force_longest_docs = args.force_longest_docs
    if force_longest_docs is None:
        force_longest_docs = MODE_FORCE_LONGEST_DOCS[args.mode]

    out_dir = args.out_root / "samples" / args.run_id
    out_path = out_dir / "sample_index.jsonl"
    summary_path = out_dir / "sample_summary.json"
    config_path = out_dir / "sample_config.json"
    if out_path.exists() and not args.force:
        raise SystemExit(f"output already exists; use --force to overwrite: {out_path}")

    corpus_stats = read_json(args.profile_stats_dir / "corpus_stats.json")
    category_names = list(corpus_stats["category_names"])
    flag_names = list(corpus_stats["flag_names"])
    manifest_rows = read_jsonl(args.profile_manifest)
    if not manifest_rows:
        raise SystemExit(f"profile manifest is empty: {args.profile_manifest}")

    config = {
        "mode": args.mode,
        "run_id": args.run_id,
        "seed": args.seed,
        "target_docs": target_docs,
        "force_longest_docs": force_longest_docs,
        "profile_manifest": str(args.profile_manifest),
        "profile_stats_dir": str(args.profile_stats_dir),
        "source_processed_docs": corpus_stats["processed_docs"],
        "source_processed_shards": corpus_stats["processed_shards"],
        "structure_rule_version": corpus_stats.get("structure_rule_version"),
    }

    records_iter = iter_profile_records(
        manifest_rows=manifest_rows,
        stats_dir=args.profile_stats_dir,
        category_names=category_names,
        flag_names=flag_names,
    )
    if args.mode == "onepct":
        selected = list(records_iter)
    else:
        all_records = list(records_iter)
        selected = choose_stratified(
            all_records,
            int(target_docs),
            args.seed,
            int(force_longest_docs),
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".jsonl.tmp")
    with tmp_path.open("wt", encoding="utf-8") as f:
        for i, rec in enumerate(selected, start=1):
            rec = dict(rec)
            rec["eval_sample_position"] = i
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    tmp_path.replace(out_path)

    summary = {
        **config,
        **summarize(selected),
        "elapsed_s": round(time.time() - started, 3),
        "sample_index": str(out_path),
    }
    write_json(summary_path, summary)
    write_json(config_path, config)

    print(f"[build_eval_sample] wrote {out_path}")
    print(f"[build_eval_sample] selected_docs={len(selected)} mode={args.mode}")
    print(f"[build_eval_sample] long_tail_docs={summary['long_tail_docs']}")
    print(f"[build_eval_sample] elapsed_s={summary['elapsed_s']}")


if __name__ == "__main__":
    main()
