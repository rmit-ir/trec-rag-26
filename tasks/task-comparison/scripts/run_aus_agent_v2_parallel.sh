#!/usr/bin/env bash
# Run the executable-contract v2 candidate over the full dev30 in parallel.
#
# Paid execution is fail-closed. The operator must explicitly provide all three:
#
#   RUN_PAID_EXPERIMENT=YES
#   AUTHORIZED_TOTAL_BUDGET_USD=<absolute historical-spend ceiling>
#   IN_FLIGHT_RESERVE_USD=<headroom reserved for already-running calls>
#
# The reserve has no default because choosing it is a paid-risk decision. The
# monitor stops launching work when total spend reaches cap minus reserve and
# terminates every exact worker process group. With the standing $300 total cap,
# the historical-spend preflight exits before any provider or search client runs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

TOPICS="${TOPICS:-data/official/trec-rag-2026-data/trec-rag-2026/development-data/topics/research-rubrics-topics-dev.tsv}"
RUN_ID="${RUN_ID:-sol-aus-v2-lean-contract-dev30}"
BACKEND="${BACKEND:-openai}"
MODEL="${MODEL:-openai.gpt-5.6-sol}"
ENGINES="${ENGINES:-semantic,keyword}"
PROMPT_VARIANT="${PROMPT_VARIANT:-contract-lean}"
CONCURRENCY="${CONCURRENCY:-6}"
MONITOR_INTERVAL_S="${MONITOR_INTERVAL_S:-5}"
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

topics_path, run_id = sys.argv[1], sys.argv[2]
topics = [
    line.split("\t", 1)[0].strip()
    for line in Path(topics_path).read_text(encoding="utf-8").splitlines()
    if line.strip()
]
done = set()
for path in Path("data/outputs/aus_agent_v2").glob("*.output.json"):
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    if (obj.get("metadata", {}).get("run_id") == run_id
            and (obj.get("trace") or {}).get("status") == "completed"):
        done.add(str(obj["metadata"]["narrative_id"]))
print("\n".join(qid for qid in topics if qid not in done))
PY
)

TOTAL="$(awk 'NF {count += 1} END {print count + 0}' "$TOPICS")"
echo "run_id=$RUN_ID topics=$TOTAL todo=${#TODO[@]} concurrency=$CONCURRENCY"
echo "backend=$BACKEND model=$MODEL engines=$ENGINES prompt=$PROMPT_VARIANT"
if [[ "$TOTAL" -ne 30 ]]; then
  echo "refusing: comparable dev evaluation requires exactly 30 topics" >&2
  exit 2
fi
if [[ "${#TODO[@]}" -eq 0 ]]; then
  echo "nothing to do"
  exit 0
fi

if [[ "${RUN_PAID_EXPERIMENT:-NO}" != "YES" ]]; then
  echo "refusing paid execution: set RUN_PAID_EXPERIMENT=YES explicitly" >&2
  exit 3
fi
if [[ -z "${AUTHORIZED_TOTAL_BUDGET_USD:-}" ]]; then
  echo "refusing paid execution: AUTHORIZED_TOTAL_BUDGET_USD is required" >&2
  exit 3
fi
if [[ -z "${IN_FLIGHT_RESERVE_USD:-}" ]]; then
  echo "refusing paid execution: IN_FLIGHT_RESERVE_USD is required" >&2
  exit 3
fi

STOP_BUDGET_USD="$({
  uv run --no-project python - \
    "$AUTHORIZED_TOTAL_BUDGET_USD" "$IN_FLIGHT_RESERVE_USD" <<'PY'
import sys

cap, reserve = map(float, sys.argv[1:])
if cap <= 0 or reserve <= 0 or reserve >= cap:
    raise SystemExit("budget and reserve must satisfy 0 < reserve < cap")
print(f"{cap - reserve:.6f}")
PY
} 2>&1)" || {
  echo "$STOP_BUDGET_USD" >&2
  exit 3
}

budget_status() {
  uv run --no-project python \
    tasks/task-comparison/scripts/goal_status.py \
    --budget "$1" 2>&1 || true
}

PREFLIGHT="$(budget_status "$AUTHORIZED_TOTAL_BUDGET_USD")"
printf '%s\n' "$PREFLIGHT"
if grep -q '^BUDGET EXCEEDED$' <<<"$PREFLIGHT"; then
  echo "refusing: historical spend already reaches the authorized cap" >&2
  exit 4
fi
if grep -q '^GOAL MET$' <<<"$PREFLIGHT"; then
  echo "refusing: the verified goal is already met" >&2
  exit 0
fi
RESERVE_PREFLIGHT="$(budget_status "$STOP_BUDGET_USD")"
if grep -q '^BUDGET EXCEEDED$' <<<"$RESERVE_PREFLIGHT"; then
  echo "refusing: spend has entered the in-flight reserve" >&2
  exit 4
fi

mkdir -p "$(dirname "$LOG")"
declare -A WORKERS=()
next_index=0
failed=0
stopped_for_budget=0

stop_workers() {
  local pid
  for pid in "${!WORKERS[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  for pid in "${!WORKERS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
  WORKERS=()
}
abort_workers() {
  stop_workers
  exit 130
}
trap stop_workers EXIT
trap abort_workers INT TERM

launch_one() {
  local qid="$1"
  echo "[$(date -Is)] launch $qid" | tee -a "$LOG"
  setsid env PYTHONPATH=src uv run --group aus-agent-v2 python \
    src/systems/aus_agent_v2/run.py \
    --qid "$qid" --topics "$TOPICS" \
    --backend "$BACKEND" --model "$MODEL" \
    --search-backends "$ENGINES" \
    --coverage-contract --observable-scout \
    --atomic-contract-plan --dynamic-contract-rows \
    --terminal-evidence-handoff \
    --prompt-variant "$PROMPT_VARIANT" \
    --run-id "$RUN_ID" >>"$LOG" 2>&1 &
  WORKERS["$!"]="$qid"
}

while [[ "$next_index" -lt "${#TODO[@]}" || "${#WORKERS[@]}" -gt 0 ]]; do
  while [[ "$next_index" -lt "${#TODO[@]}" \
           && "${#WORKERS[@]}" -lt "$CONCURRENCY" ]]; do
    launch_one "${TODO[$next_index]}"
    next_index=$((next_index + 1))
  done

  sleep "$MONITOR_INTERVAL_S"
  STATUS="$(budget_status "$STOP_BUDGET_USD")"
  if grep -q '^BUDGET EXCEEDED$' <<<"$STATUS"; then
    echo "budget stop: total spend reached cap minus in-flight reserve" \
      | tee -a "$LOG" >&2
    stopped_for_budget=1
    stop_workers
    break
  fi

  for pid in "${!WORKERS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      if ! wait "$pid"; then
        failed=$((failed + 1))
      fi
      echo "[$(date -Is)] finished ${WORKERS[$pid]}" | tee -a "$LOG"
      unset 'WORKERS[$pid]'
    fi
  done
done

trap - EXIT INT TERM
if [[ "$stopped_for_budget" -eq 1 ]]; then
  exit 4
fi
if [[ "$failed" -ne 0 ]]; then
  echo "$failed topic worker(s) failed; rerun with the same RUN_ID to resume" >&2
  exit 1
fi
echo "full dev30 generation completed: $RUN_ID"
