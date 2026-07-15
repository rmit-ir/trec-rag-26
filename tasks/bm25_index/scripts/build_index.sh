#!/bin/bash
# Build the full ClimbMix BM25 Lucene index with Anserini.
#
# Prereqs:
#   - JDK on PATH (JAVA_HOME set) — Anserini 2.2.0 needs Java 21+, uses Lucene 10.4.0
#   - collection/ already populated by parquet_to_jsonl.py (one .jsonl per shard,
#     docs {"id":"shard_NNNNN_<row>","contents":"..."})
#
# Storage flags:
#   -storePositions  -> phrase/proximity queries
#   -storeContents   -> document text retrievable via index-server /doc + _source
#   (no -storeDocvectors: PRF/RM3 not used; no -storeRaw: contents already stored)
set -euo pipefail

TASK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$TASK_DIR/../.." && pwd)"
ANSERINI_JAR="${ANSERINI_JAR:-$TASK_DIR/jars/anserini-2.2.0-fatjar.jar}"
# Data artifacts live under data/, not tasks/ (parallels data/built-indexes/climbmix-full)
INPUT="${INPUT:-$REPO_ROOT/data/climbmix-bm25-collection}"
INDEX="${INDEX:-$REPO_ROOT/data/built-indexes/climbmix-bm25}"
# Default to physical core count (NOT vcores/hyperthreads) — indexing is CPU-bound
# on dense GEMM-free tokenization + postings, and SMT oversubscription hurts here.
# This box: 2 sockets x 28 cores = 56 physical. Override with THREADS=.
THREADS="${THREADS:-56}"
# -optimize force-merges to ONE segment (best search latency) but on 553M docs it
# adds many hours + needs ~2x transient disk. Off by default; multi-segment is fine
# (index-server's IndexSearcher reads all segments). Set OPTIMIZE=1 to enable.
OPTIMIZE_FLAG=""
[ "${OPTIMIZE:-0}" = "1" ] && OPTIMIZE_FLAG="-optimize"

echo "[build_index] jar      = $ANSERINI_JAR"
echo "[build_index] input    = $INPUT"
echo "[build_index] index    = $INDEX"
echo "[build_index] threads  = $THREADS"
echo "[build_index] optimize = ${OPTIMIZE:-0}"
java -version

mkdir -p "$(dirname "$INDEX")"

exec java -Xmx64g -cp "$ANSERINI_JAR" io.anserini.index.IndexCollection \
  -collection JsonCollection \
  -input "$INPUT" \
  -index "$INDEX" \
  -generator DefaultLuceneDocumentGenerator \
  -threads "$THREADS" \
  -storePositions -storeContents \
  $OPTIMIZE_FLAG
