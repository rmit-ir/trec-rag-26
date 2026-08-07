#!/usr/bin/env bash
# Run the verified aus_agent_v2 research-first control over all official test
# topics with independent topics in parallel. Reusing RUN_ID resumes strictly
# from artifacts whose trace.status is completed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

RUN_ID="${1:?usage: run_aus_agent_v2_control_parallel.sh <run-id>}"
TOPICS="${TOPICS:-data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv}"
BACKEND="${BACKEND:-openai}"
MODEL="${MODEL:-openai.gpt-5.6-sol}"
ENGINES="${ENGINES:-semantic,keyword}"
CONCURRENCY="${CONCURRENCY:-6}"
LOG="${LOG:-tasks/task-comparison/logs/${RUN_ID}.log}"

if [[ ! "$CONCURRENCY" =~ ^[1-9][0-9]*$ ]]; then
  echo "CONCURRENCY must be a positive integer" >&2
  exit 2
fi

mapfile -t TODO < <(
  PYTHONPATH=src uv run --group aus-agent-v2 python - "$TOPICS" "$RUN_ID" <<'PY'
import json
import sys
from pathlib import Path

topics_path, run_id = sys.argv[1:]
topics = [line.split("\t", 1)[0] for line in
          Path(topics_path).read_text(encoding="utf-8").splitlines()
          if line.strip()]
done = set()
for path in Path("data/outputs/aus_agent_v2").glob("*.output.json"):
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    if (obj.get("metadata", {}).get("run_id") == run_id
            and obj.get("trace", {}).get("status") == "completed"):
        done.add(str(obj["metadata"]["narrative_id"]))
print("\n".join(topic for topic in topics if topic not in done))
PY
)

TOTAL="$(awk 'NF {count += 1} END {print count + 0}' "$TOPICS")"
echo "run_id=$RUN_ID topics=$TOTAL todo=${#TODO[@]} concurrency=$CONCURRENCY"
echo "backend=$BACKEND model=$MODEL engines=$ENGINES"
if [[ "$TOTAL" -ne 119 ]]; then
  echo "refusing: official test run requires exactly 119 topics" >&2
  exit 2
fi
if [[ "${#TODO[@]}" -eq 0 ]]; then
  echo "all topics already completed: $RUN_ID"
  exit 0
fi

mkdir -p "$(dirname "$LOG")"
export TOPICS BACKEND MODEL ENGINES RUN_ID
printf '%s\0' "${TODO[@]}" | xargs -0 -P "$CONCURRENCY" -n 1 \
  bash -c '
    qid="$1"
    PYTHONPATH=src uv run --group aus-agent-v2 python \
      src/systems/aus_agent_v2/run.py \
      --qid "$qid" --topics "$TOPICS" \
      --backend "$BACKEND" --model "$MODEL" \
      --search-backends "$ENGINES" \
      --k 20 --context-token-budget 500000 \
      --safety-max-rounds 40 --max-committed-per-step 10 \
      --coverage-plan --coverage-scout --plan-critic-additions 8 \
      --no-compact-scout-plan --no-observable-scout \
      --no-plan-reconcile --no-coverage-verify \
      --no-audience-verify --no-finish-review --no-answer-blueprint \
      --no-coverage-contract --no-atomic-contract-plan \
      --no-dynamic-contract-rows --no-terminal-evidence-handoff \
      --no-semantic-closure-verify --prompt-variant default \
      --run-id "$RUN_ID" 2>&1 | sed "s/^/[$qid] /"
  ' _ 2>&1 | tee -a "$LOG"

PYTHONPATH=src uv run --group aus-agent-v2 python - "$TOPICS" "$RUN_ID" <<'PY'
import json
import sys
from pathlib import Path

topics_path, run_id = sys.argv[1:]
topics = [line.split("\t", 1)[0] for line in
          Path(topics_path).read_text(encoding="utf-8").splitlines()
          if line.strip()]
completed = []
for path in Path("data/outputs/aus_agent_v2").glob("*.output.json"):
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    if (obj.get("metadata", {}).get("run_id") == run_id
            and obj.get("trace", {}).get("status") == "completed"):
        completed.append(str(obj["metadata"]["narrative_id"]))
missing = [topic for topic in topics if topic not in set(completed)]
duplicates = sorted(topic for topic in set(completed)
                    if completed.count(topic) > 1)
if len(completed) != len(topics) or missing or duplicates:
    raise SystemExit(
        f"incomplete run: completed={len(completed)} "
        f"missing={missing} duplicates={duplicates}")
print(f"verified {len(completed)} completed topics for {run_id}")
PY
