"""BM25 k1/b tuning harness for the chunked ClimbMix index.

The package is deliberately **stdlib-only at import time**. `pyserini` is
imported inside `searcher.ChunkSearcher._open()`, `boto3` inside
`judge.BedrockJudge._client()` and inside the `refresh-prices` subcommand body;
nothing else reaches for a third-party package. That is what lets
`tests/bm25_tune/` run in the repo-root test env — with no JVM, no AWS
credentials, and no new dependency group — and stay skip-free.

See `tasks/bm25_tune/PLAN.md` for the full design; `README.md` for operation.
"""

__all__ = ["config", "extract", "logging_setup", "prompts"]
