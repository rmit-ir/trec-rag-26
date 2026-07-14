#!/usr/bin/env python3
"""Dataset browser + chunking playground.

Point it at ONE parquet shard (schema: a `text` column); it loads the shard
into memory and serves a UI to browse documents, chunk them with any strategy
in chunkers.STRATEGIES, tweak the dials live, and see per-chunk token
estimates (words * tokens-per-word) plus corpus-sample statistics.

    uv run --project tasks/chunking-strategy python \
      tasks/chunking-strategy/scripts/app.py \
      --parquet data/climbmix-400b-shuffle/shard_00000.parquet \
      --port 8377

Docids mirror production (`shard_<NNNNN>_<row>` from prepare_corpus), chunk
ids mirror the production scheme `<docid>#c<k>`.
"""
from __future__ import annotations

import argparse
import re
import statistics
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

import chunkers

HERE = Path(__file__).resolve().parent
DEFAULT_TOKENS_PER_WORD = 1.3

app = FastAPI(title="chunking-strategy browser")
STATE: dict = {}  # parquet, texts, docid_prefix


def _docid(row: int) -> str:
    return f"{STATE['docid_prefix']}_{row}"


def _doc(i: int) -> str:
    texts = STATE["texts"]
    if not 0 <= i < len(texts):
        raise HTTPException(status_code=404, detail=f"doc index {i} out of range 0..{len(texts) - 1}")
    return texts[i]


def _chunk_params(request: Request) -> tuple[str, float, dict]:
    q = dict(request.query_params)
    strategy = q.pop("strategy", "band")
    if strategy not in chunkers.STRATEGIES:
        raise HTTPException(status_code=400, detail=f"unknown strategy {strategy!r}")
    try:
        tpw = float(q.pop("tokens_per_word", DEFAULT_TOKENS_PER_WORD))
    except ValueError:
        raise HTTPException(status_code=400, detail="tokens_per_word must be a number")
    if not 0.1 <= tpw <= 10:
        raise HTTPException(status_code=400, detail="tokens_per_word out of range")
    params = {}
    for k, v in q.items():
        try:
            params[k] = int(v)
        except ValueError:
            pass
    return strategy, tpw, params


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (HERE / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/info")
def info() -> dict:
    return {
        "parquet": str(STATE["parquet"]),
        "n_docs": len(STATE["texts"]),
        "docid_prefix": STATE["docid_prefix"],
        "tokens_per_word": DEFAULT_TOKENS_PER_WORD,
        "strategies": {
            name: {"label": spec["label"], "params": spec["params"]}
            for name, spec in chunkers.STRATEGIES.items()
        },
    }


@app.get("/api/docs")
def list_docs(offset: int = 0, limit: int = 50,
              tokens_per_word: float = DEFAULT_TOKENS_PER_WORD) -> dict:
    texts = STATE["texts"]
    offset = max(0, offset)
    limit = max(1, min(limit, 500))
    page = []
    for i in range(offset, min(offset + limit, len(texts))):
        t = texts[i]
        w = chunkers.n_words(t)
        page.append({
            "i": i,
            "docid": _docid(i),
            "words": w,
            "est_tokens": round(w * tokens_per_word),
            "preview": re.sub(r"\s+", " ", t[:160]).strip(),
        })
    return {"offset": offset, "limit": limit, "total": len(texts), "docs": page}


@app.get("/api/doc/{i}")
def get_doc(i: int, tokens_per_word: float = DEFAULT_TOKENS_PER_WORD) -> dict:
    t = _doc(i)
    w = chunkers.n_words(t)
    return {"i": i, "docid": _docid(i), "text": t,
            "words": w, "est_tokens": round(w * tokens_per_word)}


@app.get("/api/chunks/{i}")
def get_chunks(i: int, request: Request) -> dict:
    t = _doc(i)
    strategy, tpw, params = _chunk_params(request)
    parts = chunkers.run_strategy(strategy, t, tpw, params)
    docid = _docid(i)
    chunks = []
    for k, c in enumerate(parts):
        w = chunkers.n_words(c)
        chunks.append({"id": f"{docid}#c{k}", "k": k, "text": c,
                       "words": w, "est_tokens": round(w * tpw)})
    return {"i": i, "docid": docid, "strategy": strategy,
            "tokens_per_word": tpw, "params": params,
            "doc_words": chunkers.n_words(t), "n_chunks": len(chunks),
            "chunks": chunks}


@app.get("/api/stats")
def stats(request: Request) -> dict:
    """Chunk the first `sample` docs with the given strategy/params and
    return the chunk-size distribution."""
    q = dict(request.query_params)
    sample = min(int(q.pop("sample", 200)), len(STATE["texts"]))
    strategy, tpw, params = _chunk_params(request)
    sizes: list[int] = []
    n_docs = 0
    for i in range(sample):
        parts = chunkers.run_strategy(strategy, STATE["texts"][i], tpw, params)
        sizes.extend(round(chunkers.n_words(c) * tpw) for c in parts)
        n_docs += 1
    if not sizes:
        return {"sample_docs": n_docs, "n_chunks": 0}
    sizes.sort()
    qtile = lambda p: sizes[min(len(sizes) - 1, int(p * len(sizes)))]
    # fixed-width histogram buckets of 100 tokens
    hist: dict[str, int] = {}
    for s in sizes:
        b = (s // 100) * 100
        hist[f"{b}"] = hist.get(f"{b}", 0) + 1
    return {
        "sample_docs": n_docs,
        "n_chunks": len(sizes),
        "chunks_per_doc": round(len(sizes) / n_docs, 3),
        "tokens": {
            "mean": round(statistics.fmean(sizes), 1),
            "p10": qtile(0.10), "p50": qtile(0.50),
            "p90": qtile(0.90), "max": sizes[-1],
        },
        "histogram_bucket_tokens": 100,
        "histogram": hist,
        "strategy": strategy, "params": params, "tokens_per_word": tpw,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet", required=True, type=Path,
                    help="one parquet shard with a `text` column")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8377)
    args = ap.parse_args()

    import pyarrow.parquet as pq
    if not args.parquet.exists():
        raise SystemExit(f"parquet not found: {args.parquet}")
    print(f"[app] loading {args.parquet} ...", flush=True)
    table = pq.read_table(args.parquet, columns=["text"])
    STATE["texts"] = table.column("text").to_pylist()
    STATE["parquet"] = args.parquet
    m = re.search(r"(\d+)", args.parquet.stem)
    STATE["docid_prefix"] = f"shard_{int(m.group(1)):05d}" if m else args.parquet.stem
    print(f"[app] {len(STATE['texts'])} docs, docid prefix {STATE['docid_prefix']}",
          flush=True)

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
