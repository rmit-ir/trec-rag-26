#!/usr/bin/env bash
# Generate 4 single-engine aus_agent runs over the 30 research-rubrics DEV topics,
# one engine at a time (gentlest on the shared hosted backends + luna rate limit).
# --skip-existing makes the whole batch resumable: re-running only fills gaps.
#
# Run (as a tracked background task):
#   bash tasks/task-comparison/scripts/gen_per_engine_dev30.sh 2>&1 | tee /tmp/gen_dev30.log
#
# Output: data/outputs/aus_agent/<ts>.<qidslug>.{output,trajectory}.json  (run_id=dev-<tag>-30)
# Per-arm logs: data/task-comparison/gen-logs/dev-<tag>-30.log
set -uo pipefail
cd /scratch/fast/kun/projects/trec-rag-26

TOPICS=data/official/trec-rag-2026-data/trec-rag-2026/development-data/topics/research-rubrics-topics-dev.tsv
LOGDIR=data/task-comparison/gen-logs
mkdir -p "$LOGDIR"

# run-id tag -> --search-backends engine name
TAGS=(dense keyword ssr lucene)
declare -A ENG=( [dense]=semantic [keyword]=keyword [ssr]=ssr [lucene]=lucene_bool )

for tag in "${TAGS[@]}"; do
  eng="${ENG[$tag]}"
  echo "=== $(date -Is) START dev-${tag}-30 (engine=${eng}) ==="
  uv run --group aus-agent python src/systems/aus_agent/run.py --all \
    --topics "$TOPICS" \
    --backend openai --model gpt-5.6-luna \
    --search-backends "$eng" --run-id "dev-${tag}-30" --skip-existing \
    2>&1 | tee "$LOGDIR/dev-${tag}-30.log"
  echo "=== $(date -Is) DONE dev-${tag}-30 (exit ${PIPESTATUS[0]}) ==="
done
echo "=== $(date -Is) ALL ARMS COMPLETE ==="
