#!/usr/bin/env python3
"""Resolve every cited ClimbMix docid in the four-run comparison set to text.

Text comes from the **official** Pyserini REST doc endpoint for all four runs,
not from our own trajectories. That matters: our agents retrieve chunks
(``<docid>_pN``) while the baselines retrieve whole documents, so harvesting our
trajectory text would hand the judge a short focused chunk for us and a full
document for them — a systematic advantage that has nothing to do with answer
quality. One shared source keeps the judge's view identical across runs.

Fetches are cached to disk by docid, so re-running is free and the support and
UMBRELA stages share one corpus snapshot.

    PYTHONPATH=src uv run --group aus-agent python \
        tasks/task-comparison/scripts/resolve_test119_refs.py
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
sys.path.insert(0, str(ROOT / "src"))

EVAL_DIR = ROOT / "data/task-comparison/test119-eval"
CACHE_DIR = ROOT / "data/task-comparison/test119-eval/doc-cache"
DOC_URL = "http://api.castorini.uwaterloo.ca/v1/climbmix-400b/doc"
LABELS = ["ours-semantic", "ours-keyword", "base-agentic-bm25", "base-singlepass"]


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    import os
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class RateLimiter:
    """Global token bucket shared by every worker thread.

    Backoff alone was not enough: retries reconverge and the pool re-bursts, so
    the API kept returning 429 even at six workers. Pacing every request through
    one bucket bounds the *aggregate* rate regardless of worker count, which is
    the quantity the server actually limits.
    """

    def __init__(self, rate_per_second: float) -> None:
        self._interval = 1.0 / rate_per_second
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + self._interval
        if wait:
            time.sleep(wait)


def cache_path(docid: str) -> Path:
    """Shard the cache two levels deep — 6k+ files in one directory is slow."""
    return CACHE_DIR / docid[-2:] / f"{docid}.txt"


def extract_text(payload: dict) -> str:
    """Pull the document body out of the API's response.

    ``doc`` is a parsed JSON structure when the stored payload is JSON, and a
    bare string otherwise; both shapes occur in ClimbMix.
    """
    raw = payload.get("doc")
    if isinstance(raw, str):
        stripped = raw.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError:
                return raw
        else:
            return raw
    if isinstance(raw, dict):
        for key in ("contents", "content", "text", "body", "segment"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value
    for key in ("contents", "content", "text", "body", "segment"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise RuntimeError("no usable text field")


def fetch(docid: str, token: str, timeout: float, *,
          limiter: "RateLimiter | None" = None, attempts: int = 6) -> str:
    """One document, retrying 429/5xx with exponential backoff.

    The API rate-limits a back-to-back fetch pool (the pyserini-rest-api skill
    warns about exactly this: workloads that spend time *between* calls never
    see a 429, a tight fetch loop does). Honour ``Retry-After`` when the server
    sends one, otherwise back off geometrically with a per-docid jitter so the
    whole pool does not retry in lockstep.
    """
    url = f"{DOC_URL}/{urllib.parse.quote(docid, safe='')}"
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "trec-rag-reference-resolver/1.0"})
    for attempt in range(attempts):
        try:
            if limiter is not None:
                limiter.acquire()
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return extract_text(json.load(response))
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt == attempts - 1:
                raise
            after = exc.headers.get("Retry-After") if exc.headers else None
            delay = (float(after) if after and after.isdigit()
                     else 2.0 * (2 ** attempt))
            time.sleep(delay + (hash(docid) % 1000) / 1000.0)
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
            time.sleep(2.0 * (2 ** attempt))
    raise RuntimeError("unreachable")


def main() -> int:
    load_env()
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-dir", type=Path, default=EVAL_DIR)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--rate", type=float, default=6.0,
                        help="Aggregate requests per second across all workers.")
    args = parser.parse_args()

    token = os.environ.get("PYSERINI_API_TOKEN")
    if not token:
        print("PYSERINI_API_TOKEN is not set", file=sys.stderr)
        return 2

    runs = {label: [json.loads(line) for line in
                    (args.eval_dir / f"{label}.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()]
            for label in LABELS}
    wanted = sorted({docid for rows in runs.values() for row in rows
                     for docid in row["references"]})
    missing = [d for d in wanted if not cache_path(d).exists()]
    print(f"{len(wanted)} distinct cited docids; {len(missing)} not cached")

    failures: dict[str, str] = {}
    lock = threading.Lock()
    limiter = RateLimiter(args.rate)
    done = 0

    def work(docid: str) -> None:
        nonlocal done
        try:
            text = fetch(docid, token, args.timeout, limiter=limiter)
        except Exception as exc:  # noqa: BLE001 — record and keep going
            with lock:
                failures[docid] = f"{type(exc).__name__}: {exc}"
            return
        path = cache_path(docid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        with lock:
            done += 1
            if done % 250 == 0:
                print(f"  fetched {done}/{len(missing)}", flush=True)

    if missing:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(work, d) for d in missing]):
                future.result()
    print(f"fetched {done}, failed {len(failures)}")
    if failures:
        for docid, why in list(failures.items())[:10]:
            print(f"  FAIL {docid}: {why}")

    # RAGDoll's answers schema, one file per run.
    for label, rows in runs.items():
        out = args.eval_dir / f"{label}.resolved.jsonl"
        written = skipped = 0
        with out.open("w", encoding="utf-8") as stream:
            for row in rows:
                segments = {}
                for docid in row["references"]:
                    path = cache_path(docid)
                    if path.exists():
                        segments[docid] = path.read_text(encoding="utf-8")
                if len(segments) != len(row["references"]):
                    skipped += 1
                meta = row["metadata"]
                answer_text = " ".join(s["text"] for s in row["answer"])
                stream.write(json.dumps({
                    "run_id": label,
                    "qid": meta["narrative_id"],
                    "topic_id": meta["narrative_id"],
                    "query": meta["narrative"],
                    "topic": meta["narrative"],
                    "response_length": len(answer_text.split()),
                    "answer_text": answer_text,
                    "answer": row["answer"],
                    "references": row["references"],
                    "segments": segments,
                }, ensure_ascii=False) + "\n")
                written += 1
        note = f" ({skipped} rows have unresolved refs)" if skipped else ""
        print(f"wrote {written} rows -> {out}{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
