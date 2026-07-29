#!/usr/bin/env bash
# A/B the aus_agent system prompt on the FIRST 10 dev topics: baseline (default)
# vs the first-hand/original-content variant (firsthand). Everything else held
# constant (same 10 topics, backends, model). --skip-existing => resumable.
#
# Run (tracked background task):
#   bash tasks/task-comparison/scripts/run_prompt_ab.sh 2>&1 | tee /tmp/promptab.log
#
# Outputs: data/outputs/aus_agent/*.output.json with run_id promptab-<variant>
# (metadata.prompt_variant + run_desc record which prompt was used).
set -uo pipefail
cd /scratch/fast/kun/projects/trec-rag-26

DEV=data/official/trec-rag-2026-data/trec-rag-2026/development-data/topics/research-rubrics-topics-dev.tsv
TOPICS=$(mktemp /tmp/promptab-topics10.XXXXXX.tsv)
head -10 "$DEV" > "$TOPICS"
LOGDIR=tasks/task-comparison/logs; mkdir -p "$LOGDIR"

run_arm() {  # $1=prompt_variant  $2=run_id
  echo "=== $(date -Is) START $2 (prompt=$1) ==="
  uv run --group aus-agent python src/systems/aus_agent/run.py --all \
    --topics "$TOPICS" --backend openai --model gpt-5.6-luna \
    --search-backends semantic,keyword \
    --prompt-variant "$1" --run-id "$2" --skip-existing \
    2>&1 | tee "$LOGDIR/$2.log"
  echo "=== $(date -Is) DONE $2 (exit ${PIPESTATUS[0]}) ==="
}

run_arm default   promptab-default
run_arm firsthand promptab-firsthand
echo "=== $(date -Is) A/B COMPLETE ==="
rm -f "$TOPICS"
