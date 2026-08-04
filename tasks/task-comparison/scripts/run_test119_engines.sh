#!/usr/bin/env bash
# Two single-engine aus_agent runs over ALL 119 TEST topics
# (trec_rag_2026_queries.tsv), semantic vs keyword, launched IN PARALLEL.
# Default prompt variant; k=20 and max-committed-per-step=20 (raised from the
# dev-30 defaults of 10/10 — the only intentional deviation).
# --skip-existing makes each arm resumable: re-running only fills gaps.
#
# Run (as a tracked background task):
#   bash tasks/task-comparison/scripts/run_test119_engines.sh 2>&1 | tee /tmp/test119.log
#
# Output: data/outputs/aus_agent/<ts>.<qidslug>.{output,trajectory}.json
#         run_id = test-semantic-119 | test-keyword-119
# Per-arm logs: tasks/task-comparison/logs/test-<engine>-119.log
set -uo pipefail
cd /scratch/fast/kun/projects/trec-rag-26

TOPICS=data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv
LOGDIR=tasks/task-comparison/logs
mkdir -p "$LOGDIR"

run_arm() {  # $1=engine  $2=run_id
  echo "=== $(date -Is) START $2 (engine=$1) ==="
  uv run --group aus-agent python src/systems/aus_agent/run.py --all \
    --topics "$TOPICS" \
    --backend openai --model gpt-5.6-luna \
    --search-backends "$1" \
    --prompt-variant default \
    --k 20 --max-committed-per-step 20 \
    --run-id "$2" --skip-existing \
    > "$LOGDIR/$2.log" 2>&1
  echo "=== $(date -Is) DONE $2 (exit $?) ==="
}

run_arm semantic test-semantic-119 &
PID_SEM=$!
run_arm keyword  test-keyword-119 &
PID_KW=$!

wait $PID_SEM; RC_SEM=$?
wait $PID_KW;  RC_KW=$?
echo "=== $(date -Is) BOTH ARMS COMPLETE (semantic=$RC_SEM keyword=$RC_KW) ==="
