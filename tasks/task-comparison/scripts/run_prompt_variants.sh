#!/usr/bin/env bash
# A/B the aus_agent system prompt across variants on a fixed topic set, holding
# model, engines, k, and commit cap constant. Host-agnostic (resolves the repo
# root from this file), unlike the older run_prompt_ab.sh which hardcodes the
# GPU box's /scratch path.
#
#   bash tasks/task-comparison/scripts/run_prompt_variants.sh \
#       default paired-lead done-condition evidence-dense 2>&1 | tee /tmp/promptab.log
#
# --skip-existing makes each arm resumable: a killed run resumes at the first
# topic that has no successful output for that run_id.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

TOPICS=${TOPICS:-data/task-comparison/topics10.tsv}
MODEL=${MODEL:-gpt-5.6-luna}
ENGINES=${ENGINES:-semantic,keyword}
K=${K:-20}
MAXCOMMIT=${MAXCOMMIT:-20}
TAG=${TAG:-promptab0805}
LOGDIR=tasks/task-comparison/logs; mkdir -p "$LOGDIR"

# BSD date (macOS) has no -I; GNU date does. Both understand +%FT%T%z.
stamp() { date +%FT%T%z; }

echo "topics=$TOPICS model=$MODEL engines=$ENGINES k=$K max-committed=$MAXCOMMIT"
for variant in "$@"; do
  run_id="$TAG-$variant"
  echo "=== $(date -Is) START $run_id ==="
  PYTHONPATH=src uv run --group aus-agent python src/systems/aus_agent/run.py \
    --all --topics "$TOPICS" --backend openai --model "$MODEL" \
    --search-backends "$ENGINES" --k "$K" --max-committed-per-step "$MAXCOMMIT" \
    --prompt-variant "$variant" --run-id "$run_id" --skip-existing \
    2>&1 | tee "$LOGDIR/$run_id.log"
  echo "=== $(date -Is) DONE $run_id (exit ${PIPESTATUS[0]}) ==="
done
echo "=== $(date -Is) ALL ARMS COMPLETE ==="
