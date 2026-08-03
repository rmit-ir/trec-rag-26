#!/usr/bin/env bash
# Compare the fine-tuned full index vs the base-model full index on the RAG25
# dev topics, against the ClimbMix UMBRELA qrels. Answers: "does general (non-
# agent) retrieval quality drop with the fine-tune, and by how much?"
#
#   - FT run  : local DiskANN disk index data/built-indexes/climbmix-chunked-ft
#               (query-encoded with the fine-tune, index-driven).
#   - BASE run: the OLD base-model full dense index, still served at
#               index-climbmix-jina-v5-nano.dsync.net. Same chunks/corpus, only
#               the embedding model differs -> clean apples-to-apples.
#
# Both retrieve with identical params, collapse chunk->parent doc (max-pool over
# pages) to match the doc-level qrels, then score_run.py reports RAW + CONDENSED
# (pool-bias-corrected) metrics + judged-coverage against every qrels variant.
#
# Base fetch needs basic-auth creds in env (NEVER hardcode/commit):
#   RMIT_USER=... RMIT_PASS=... bash tasks/custom_index/scripts/eval_ft_vs_base.sh
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
TASK="tasks/custom_index"

FT_INDEX="data/built-indexes/climbmix-chunked-ft"
BASE_URL="${BASE_URL:-https://index-climbmix-jina-v5-nano.dsync.net}"
DEV="data/official/trec-rag-2026-data/trec-rag-2026/development-data"
TOPICS="$DEV/topics/rag25-topics-dev.tsv"
QRELS_DIR="$DEV/rag25-dev-umbrela-qrels"
OUT="$TASK/work/eval-ft-vs-base"
mkdir -p "$OUT"

# Identical retrieval params on both sides.
K=2000; COMPLEXITY=2000; BEAM=4; DEPTH=1000

FT_RUN="$OUT/ft.rag25dev.run"
BASE_RUN="$OUT/base.rag25dev.run"

echo "=== [1/3] FT run: local index $FT_INDEX ==="
uv run --project "$TASK" python "$TASK/scripts/eval_umbrela.py" \
  --index-dir "$FT_INDEX" --topics "$TOPICS" --qrels-dir "$QRELS_DIR" \
  --k "$K" --complexity "$COMPLEXITY" --beam-width "$BEAM" \
  --num-threads 8 --depth "$DEPTH" \
  --run-out "$FT_RUN" --json-out "$OUT/ft.metrics.json" || exit 1

echo
echo "=== [2/3] BASE run: remote $BASE_URL ==="
if [ -z "${RMIT_USER:-}" ] || [ -z "${RMIT_PASS:-}" ]; then
  echo "SKIP base fetch: set RMIT_USER / RMIT_PASS in env for the baseline." >&2
else
  uv run --project "$TASK" python "$TASK/scripts/fetch_remote_run.py" \
    --url "$BASE_URL" --engine dense --topics "$TOPICS" \
    --k "$K" --complexity "$COMPLEXITY" --beam-width "$BEAM" --depth "$DEPTH" \
    --tag base-jina-v5-nano --out "$BASE_RUN" || exit 1
fi

echo
echo "=== [3/3] Scored comparison (raw + condensed + jcov) ==="
RUN_ARGS=(--run "fine-tuned=$FT_RUN")
[ -f "$BASE_RUN" ] && RUN_ARGS+=(--run "base=$BASE_RUN")
uv run --project "$TASK" python "$TASK/scripts/score_run.py" \
  --qrels-dir "$QRELS_DIR" "${RUN_ARGS[@]}" | tee "$OUT/comparison.txt"

echo
echo "Runs + metrics under $OUT/"
