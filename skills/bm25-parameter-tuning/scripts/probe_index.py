#!/usr/bin/env python
"""Probe any Anserini/Lucene index and print the env exports to tune it.

The first step on a new index is the one that goes wrong, and it goes wrong
*silently*. Two facts have to be established before spending anything:

1. **`num_docs`** — the value `BM25_TUNE_EXPECTED_NUM_DOCS` must be pinned to.
   That guard is what makes a cached judgment safe to reuse: the cache key is
   `prompt::topic_id::chunk_id` with no corpus component, so an index rebuilt or
   re-chunked under the same path would have new passages scored against grades
   given to old ones. Running with the guard off is correct exactly once — now.
2. **Whether document text is retrievable at all.** `judge-pool` sends the
   *passage*, not the docid, so an index built without stored text yields empty
   passages that every judge grades 0 uniformly — producing a complete-looking
   score matrix in which no config can beat any other. Which accessor works is
   build-dependent and the two common cases are opposites (`contents()` on
   ClimbMix's custom generator, `raw()` on a stock `--storeRaw` index), so this
   probe checks both the way the harness does.

It also runs one real query per `--query` so the ranking is seen to be non-empty
before a grid of them is launched.

Usage (needs the task env and JDK 21, same as the harness itself):

    export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"
    uv run --project tasks/bm25_tune python \\
        skills/bm25-parameter-tuning/scripts/probe_index.py /path/to/index \\
        --query "soil moisture irrigation"

Exit codes: 0 = usable, 1 = unopenable, 2 = opened but stores no document text
(the silent-failure case, called out as its own code so a wrapper can branch),
3 = no query matched anything, so nothing was proven either way.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The harness' own `_document_text` is reused rather than reimplemented: a probe
# that answers "is text retrievable" with different logic than the code that
# fetches it can pass while the real run gets nothing.
TASK_ROOT = Path(__file__).resolve().parents[3] / "tasks" / "bm25_tune"

EXIT_OK = 0
EXIT_UNOPENABLE = 1
EXIT_NO_TEXT = 2
EXIT_NO_HITS = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("index_dir", type=Path,
                        help="the Anserini/Lucene index directory to probe")
    parser.add_argument("--query", action="append", default=None, metavar="TEXT",
                        help="issue this query (repeatable) and show the top "
                             "hits with their text; default: one generic query")
    parser.add_argument("--depth", type=int, default=3,
                        help="hits to show per query (default: 3)")
    parser.add_argument("--chars", type=int, default=200,
                        help="passage characters to print per hit "
                             "(default: 200)")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(TASK_ROOT))
    try:
        from bm25tune.searcher import _document_text
    except ImportError as exc:
        print(f"cannot import the bm25tune harness from {TASK_ROOT}: {exc}",
              file=sys.stderr)
        return EXIT_UNOPENABLE

    if not args.index_dir.is_dir():
        print(f"not a directory: {args.index_dir}", file=sys.stderr)
        return EXIT_UNOPENABLE

    try:
        from pyserini.search.lucene import LuceneSearcher
    except Exception as exc:
        print("could not import pyserini.search.lucene — run this under the "
              "task env with JDK 21 on JAVA_HOME:\n"
              '  export JAVA_HOME="$PWD/tasks/bm25_tune/env/lib/jvm"\n'
              "  uv run --project tasks/bm25_tune python "
              f"{Path(__file__).name} ...\n({type(exc).__name__}: {exc})",
              file=sys.stderr)
        return EXIT_UNOPENABLE

    try:
        searcher = LuceneSearcher(str(args.index_dir))
    except Exception as exc:
        print(f"failed to open {args.index_dir}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return EXIT_UNOPENABLE

    num_docs = int(getattr(searcher, "num_docs", -1))
    print(f"index      : {args.index_dir}")
    print(f"num_docs   : {num_docs}")

    queries = args.query or ["information"]
    any_text = False
    any_hits = False
    for query in queries:
        hits = searcher.search(query, k=args.depth)
        print(f"\nquery      : {query!r} -> {len(hits)} hits")
        if hits:
            any_hits = True
        else:
            # Not fatal: a probe query may simply have no match. It IS a reason
            # to try another before trusting the index, which is why the query
            # text is echoed rather than just the count.
            print("             (no hits — try a term you know is in the "
                  "corpus before concluding anything)")
            continue
        for hit in hits:
            docid = getattr(hit, "docid", "?")
            text = _document_text(searcher.doc(docid))
            if text:
                any_text = True
                snippet = " ".join(text.split())[:args.chars]
                print(f"  {docid}  score={hit.score:.4f}\n      {snippet}")
            else:
                print(f"  {docid}  score={hit.score:.4f}\n      "
                      "*** NO STORED TEXT ***")

    print()
    # "No hits" and "hits but no text" are different findings and only the second
    # is a verdict on the index. Conflating them would report a healthy index as
    # broken whenever the default probe term happens to be absent — which is the
    # normal case on a small or domain-specific corpus.
    if not any_hits:
        print("INCONCLUSIVE: no query matched, so neither the text accessors nor "
              "the ranking was exercised.\n"
              "  Re-run with `--query` terms you know appear in this corpus.",
              file=sys.stderr)
        return EXIT_NO_HITS
    if not any_text:
        print("FAIL: this index returns no document text.\n"
              "  `judge-pool` sends the passage, not the docid, so every "
              "judgment would be made on an empty string — grading 0 uniformly "
              "and producing a score matrix in which no config beats any "
              "other.\n"
              "  Rebuild the index with stored text (`pyserini.index.lucene "
              "--storeRaw`, or a generator that populates `contents`) before "
              "spending anything on judging.", file=sys.stderr)
        return EXIT_NO_TEXT

    print("Usable. Pin the identity guard to what this index actually holds:\n")
    print(f'  export BM25_TUNE_INDEX_DIR="{args.index_dir}"')
    print(f"  export BM25_TUNE_EXPECTED_NUM_DOCS={num_docs}")
    print("\n(`=none` disables the guard — correct only for this first probe. "
          "Leaving it off means a rebuilt index silently reuses judgments made "
          "against the old one.)")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
