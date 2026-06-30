"""Ad-hoc search CLI: point at a built-index dir and run queries.

Usage:
  uv run --project tasks/search_serve python tasks/search_serve/scripts/cli.py \
    --index-dir data/built-indexes/climbmix-full \
    --query "transformers explained" \
    --k 5 --max-chars 200
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from encoder import EncoderConfig
from errors import EngineLoadError
from search_engine import SearchEngine


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Ad-hoc search against a built-index dir.")
    ap.add_argument("--index-dir", required=True, type=Path)
    ap.add_argument("--query", action="append", required=True,
                    help="repeat to issue multiple queries in one batch")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--device", default="auto",
                    help="encoder device: auto | cpu | cuda | cuda:N")
    ap.add_argument("--dtype", default="auto",
                    choices=["auto", "float32", "float16", "bfloat16"])
    ap.add_argument("--num-threads", type=int, default=4,
                    help="DiskANN search threads (one libaio context per thread)")
    ap.add_argument("--no-text", action="store_true",
                    help="don't fetch raw text via the docstore")
    ap.add_argument("--no-warmup", action="store_true")
    ap.add_argument("--no-server-info", action="store_true")
    ap.add_argument("--max-chars", type=int, default=200,
                    help="truncate printed text per hit for readability")
    return ap


def load_engine(args) -> SearchEngine:
    cfg = EncoderConfig(device=args.device, dtype=args.dtype)
    return SearchEngine.load(
        args.index_dir,
        encoder_config=cfg,
        diskann_search_threads=args.num_threads,
        warmup=not args.no_warmup,
        print_server_details=not args.no_server_info,
    )


def _truncate(s: str | None, n: int) -> str | None:
    if s is None or len(s) <= n:
        return s
    return s[:n] + "..."


def render_results(queries: list[str], batch, max_chars: int) -> list[dict]:
    out: list[dict] = []
    for q, hits in zip(queries, batch):
        out.append({
            "query": q,
            "hits": [
                {**h.to_dict(), "text": _truncate(h.text, max_chars)}
                for h in hits
            ],
        })
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        eng = load_engine(args)
    except EngineLoadError as e:
        print(f"\n[engine] FAILED to load index:\n  {e}\n", file=sys.stderr)
        return 3
    batch = eng.search_batch(args.query, k=args.k, with_text=not args.no_text)
    print(json.dumps(render_results(args.query, batch, args.max_chars),
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
