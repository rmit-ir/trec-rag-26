#!/usr/bin/env python3
"""Download sampled Hugging Face dataset parquet shards with retry logging."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from huggingface_hub import hf_hub_download


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--status-jsonl", type=Path, required=True)
    ap.add_argument("--summary-json", type=Path, required=True)
    ap.add_argument("--repo-id", default="karpathy/climbmix-400b-shuffle")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--sleep-seconds", type=float, default=10.0)
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


def main() -> int:
    args = parse_args()
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.status_jsonl.parent.mkdir(parents=True, exist_ok=True)
    if args.status_jsonl.exists():
        args.status_jsonl.unlink()

    os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "0")

    rows = load_manifest(args.manifest)
    n_exists = n_downloaded = n_failed = 0
    started = time.time()
    print(f"[download] repo={args.repo_id} shards={len(rows)} raw_dir={args.raw_dir}", flush=True)

    for i, row in enumerate(rows, start=1):
        filename = row["filename"]
        repo_path = row.get("repo_path", filename)
        local_path = args.raw_dir / filename
        t0 = time.time()

        if local_path.exists() and local_path.stat().st_size > 0 and not args.force:
            n_exists += 1
            rec = {
                "filename": filename,
                "repo_path": repo_path,
                "status": "exists",
                "path": str(local_path),
                "bytes": local_path.stat().st_size,
                "elapsed_s": round(time.time() - t0, 3),
            }
            write_jsonl(args.status_jsonl, rec)
            print(f"[download] {i}/{len(rows)} exists {filename}", flush=True)
            continue

        ok = False
        last_error = ""
        for attempt in range(1, args.retries + 1):
            try:
                print(f"[download] {i}/{len(rows)} downloading {repo_path} attempt={attempt}", flush=True)
                path = hf_hub_download(
                    repo_id=args.repo_id,
                    filename=repo_path,
                    repo_type="dataset",
                    local_dir=str(args.raw_dir),
                    force_download=args.force,
                )
                got = Path(path)
                if got != local_path and got.exists():
                    # hf_hub_download may return an absolute path under local_dir.
                    local_path = got
                if local_path.exists() and local_path.stat().st_size > 0:
                    ok = True
                    break
                last_error = f"download returned but file is missing or empty: {local_path}"
            except Exception as e:  # noqa: BLE001
                last_error = repr(e)
                print(f"[download] warning {filename} attempt={attempt} error={last_error}", flush=True)
                if attempt < args.retries:
                    time.sleep(args.sleep_seconds * attempt)

        if ok:
            n_downloaded += 1
            rec = {
                "filename": filename,
                "repo_path": repo_path,
                "status": "downloaded",
                "path": str(local_path),
                "bytes": local_path.stat().st_size,
                "elapsed_s": round(time.time() - t0, 3),
            }
            print(f"[download] {i}/{len(rows)} done {filename} bytes={rec['bytes']}", flush=True)
        else:
            n_failed += 1
            rec = {
                "filename": filename,
                "repo_path": repo_path,
                "status": "failed",
                "path": str(local_path),
                "error": last_error,
                "elapsed_s": round(time.time() - t0, 3),
            }
            print(f"[download] {i}/{len(rows)} FAILED {filename}: {last_error}", flush=True)
        write_jsonl(args.status_jsonl, rec)

    available = n_exists + n_downloaded
    summary = {
        "repo_id": args.repo_id,
        "requested": len(rows),
        "exists": n_exists,
        "downloaded": n_downloaded,
        "failed": n_failed,
        "available": available,
        "elapsed_s": round(time.time() - started, 3),
        "status_jsonl": str(args.status_jsonl),
    }
    args.summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[download] summary: {json.dumps(summary, sort_keys=True)}", flush=True)

    if available == 0:
        raise SystemExit("no parquet shards are available after download step")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

