#!/usr/bin/env python3
"""ssr-search CLI — drive Cottontail SSR (the paper's stack) over a burrow.

Spawns its own ``ssr-server`` subprocess (via SsrEngine) against a burrow and
lets you run GCL Boolean queries, page through results, and fetch full docs.

Query language is **GCL** (Cottontail). Cheat-sheet for this corpus:

    apple                      one term
    "flu vaccine"              phrase (adjacent, in order; = (... flu vaccine))
    (^ influenza vaccine)      AND  — all must appear in the same doc body
    (+ flu influenza grippe)   OR   — any of these
    (^ "flu shot" (+ cdc who)) nest freely
    (>> A B)                   A that CONTAINS B
    (<< A B)                   A CONTAINED IN B
    (<< (^ a b) (# k))         a AND b within a k-token window (proximity)

SSR ranks by shortest matching substring (score = sum 1/(C+len), C=42), so
tight co-occurrences win — the truthful-zero property (an AND term that is
absent -> no hit) is the whole point vs. OR-BM25 drift.

Examples:
    python cli.py --burrow data/built-indexes/ssr-shard00000/json.burrow \\
        '(^ influenza vaccine)' -k 5
    python cli.py --burrow <burrow> --repl
    python cli.py --burrow <burrow> --doc shard_00000_0
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

from ssr_engine import (DEFAULT_CONTAINER, DEFAULT_CONTENT, DEFAULT_DOCNO,
                        DEFAULT_SERVER_BIN, SsrEngine)


def _print_hit(h, width: int, full_snippet: bool) -> None:
    snip = h.snippet if full_snippet else " ".join(h.snippet.split())[:width]
    print(f"[{h.rank:>3}] {h.docno}")
    print(textwrap.indent(textwrap.fill(snip, width=width) if not full_snippet
                          else snip, "      "))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Cottontail SSR search CLI")
    ap.add_argument("query", nargs="*", help="GCL query (omit for --repl)")
    ap.add_argument("--burrow", required=True, action="append",
                    help="burrow dir (repeat for multiple collections)")
    ap.add_argument("-k", type=int, default=10)
    ap.add_argument("--container", default=DEFAULT_CONTAINER)
    ap.add_argument("--content", default=DEFAULT_CONTENT)
    ap.add_argument("--docno", default=DEFAULT_DOCNO)
    ap.add_argument("--fields", default=None,
                    help="comma-separated field GCL for --doc full text")
    ap.add_argument("--server-bin", default=str(DEFAULT_SERVER_BIN))
    ap.add_argument("--width", type=int, default=200)
    ap.add_argument("--full-snippet", action="store_true")
    ap.add_argument("--repl", action="store_true")
    ap.add_argument("--doc", default=None, help="fetch full document by docno")
    args = ap.parse_args(argv)

    engine = SsrEngine(
        burrows=[str(Path(b).resolve()) for b in args.burrow],
        container=args.container, content=args.content, docno=args.docno,
        fields=args.fields, server_bin=Path(args.server_bin))
    try:
        engine.start()
    except Exception as e:  # noqa: BLE001
        print(f"cli: failed to start ssr-server: {e}", file=sys.stderr)
        return 1
    print(f"cli: ssr-server on port {engine.port}", file=sys.stderr)

    try:
        if args.doc is not None:
            print(engine.document(args.doc))
            return 0
        if args.repl or not args.query:
            return _repl(engine, args)
        hits = engine.search(" ".join(args.query), k=args.k)
        if not hits:
            print("(no hits)")
        for h in hits:
            _print_hit(h, args.width, args.full_snippet)
        return 0
    finally:
        engine.close()


def _repl(engine: SsrEngine, args) -> int:
    print("GCL REPL. Enter a query; '@doc <docno>' full text; Ctrl-D to quit.",
          file=sys.stderr)
    while True:
        try:
            line = input(">> ").strip()
        except EOFError:
            print(); break
        if not line:
            continue
        try:
            if line.startswith("@doc "):
                print(engine.document(line[5:].strip()))
                continue
            hits = engine.search(line, k=args.k)
            if not hits:
                print("(no hits)")
            for h in hits:
                _print_hit(h, args.width, args.full_snippet)
        except Exception as e:  # noqa: BLE001
            print(f"cli: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
