#!/usr/bin/env python3
"""Query a remote search-serve (POST /search/batch) over the RAG25 dev topics and
write a TREC run file. Used to pull baseline runs (BM25 / old dense) for an
apples-to-apples comparison against the local climbmix-chunked index.

Chunk ids (``shard_NNNNN_docrow_pN``) are collapsed to their parent doc id
(``shard_NNNNN_docrow``) with max-pool over pages, matching the qrels keys.
For an unchunked index (docids already parent-level) the collapse is a no-op.

Credentials come from env RMIT_USER / RMIT_PASS (basic auth) so they never land
in a tracked file. Uses only the stdlib (urllib) — no extra deps.

Run:
  RMIT_USER=... RMIT_PASS=... uv run --project tasks/custom_index python \
    tasks/custom_index/scripts/fetch_remote_run.py \
    --url https://index-climbmix-jina-v5-nano.dsync.net \
    --topics .../rag25-topics-dev.tsv \
    --k 1000 --complexity 2000 --beam-width 4 \
    --tag old-dense-768 --out /tmp/old-dense.rag25dev.run
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path


def load_topics(path: Path) -> list[tuple[str, str]]:
    out = []
    for line in open(path, "rt", encoding="utf-8"):
        line = line.rstrip("\n")
        if not line:
            continue
        qid, _, query = line.partition("\t")
        out.append((qid.strip(), query.strip()))
    return out


def parent_of(docid: str) -> str:
    return docid.rsplit("_p", 1)[0]


def _open(req: urllib.request.Request, timeout: float):
    req.add_header("user-agent", "curl/8.4.0")  # proxy 403s the stock urllib UA
    return urllib.request.urlopen(req, timeout=timeout)


def post_sparse(url: str, auth: str, query: str, k: int, timeout: float) -> list[dict]:
    """Anserini index-server: POST /api/search {query, hits} -> ES-style hits."""
    body = json.dumps({"query": query, "hits": k}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/api/search", data=body, method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("authorization", "Basic " + auth)
    with _open(req, timeout) as r:
        data = json.loads(r.read())
    out = []
    for h in data.get("hits", {}).get("hits", []):
        out.append({"docid": h["_id"], "score": float(h["_score"])})
    return out


def post_batch(url: str, auth: str, queries: list[str], k: int,
               complexity: int, beam_width: int, timeout: float) -> list[list[dict]]:
    body = json.dumps({
        "queries": queries, "k": k, "complexity": complexity,
        "beam_width": beam_width, "with_text": False,
    }).encode()
    req = urllib.request.Request(url.rstrip("/") + "/search/batch", data=body,
                                 method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("authorization", "Basic " + auth)
    # Cloudflare in front of the service 403s the default python-urllib UA.
    req.add_header("user-agent", "curl/8.4.0")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.loads(r.read())
    return payload["results"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--engine", choices=["dense", "sparse"], default="dense",
                    help="dense=POST /search/batch; sparse=POST /api/search per query")
    ap.add_argument("--topics", required=True, type=Path)
    ap.add_argument("--k", type=int, default=1000)
    ap.add_argument("--complexity", type=int, default=2000)
    ap.add_argument("--beam-width", type=int, default=4)
    ap.add_argument("--depth", type=int, default=1000, help="docs kept per topic after collapse")
    ap.add_argument("--batch", type=int, default=64, help="queries per /search/batch call")
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    user, pw = os.environ.get("RMIT_USER"), os.environ.get("RMIT_PASS")
    if not user or not pw:
        print("[fetch] set RMIT_USER and RMIT_PASS in the environment", file=sys.stderr)
        return 2
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()

    topics = load_topics(args.topics)
    print(f"[fetch] {args.url}  {len(topics)} topics  k={args.k} L={args.complexity}",
          flush=True)

    def collapse(hits: list[dict]) -> dict[str, float]:
        best: dict[str, float] = {}
        for h in hits:
            d = parent_of(h["docid"])
            s = float(h["score"])
            if d not in best or s > best[d]:
                best[d] = s
        return dict(sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:args.depth])

    run: dict[str, dict[str, float]] = {}
    t0 = time.perf_counter()
    if args.engine == "sparse":
        for j, (qid, q) in enumerate(topics, start=1):
            run[qid] = collapse(post_sparse(args.url, auth, q, args.k, args.timeout))
            if j % 5 == 0 or j == len(topics):
                print(f"[fetch]  {j}/{len(topics)} topics", flush=True)
    else:
        for i in range(0, len(topics), args.batch):
            chunk = topics[i:i + args.batch]
            results = post_batch(args.url, auth, [q for _, q in chunk],
                                 args.k, args.complexity, args.beam_width, args.timeout)
            for (qid, _q), hits in zip(chunk, results):
                run[qid] = collapse(hits)
            print(f"[fetch]  {min(i+args.batch,len(topics))}/{len(topics)} topics", flush=True)

    with open(args.out, "wt", encoding="utf-8") as f:
        for qid, docs in run.items():
            for rank, (docid, score) in enumerate(
                sorted(docs.items(), key=lambda kv: kv[1], reverse=True), start=1
            ):
                f.write(f"{qid} Q0 {docid} {rank} {score:.6f} {args.tag}\n")
    avg = sum(len(v) for v in run.values()) / len(run)
    print(f"[fetch] wrote {args.out}  mean {avg:.0f} docs/topic  "
          f"({time.perf_counter()-t0:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
