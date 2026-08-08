#!/usr/bin/env bash
# Generic official-119-test-topic parallel runner, for any system whose
# run.py accepts --qid/--topics/--run-id and writes
# data/outputs/<system>/*.output.json with top-level metadata.run_id and
# trace.status. Generalizes run_aus_agent_v2_control_parallel.sh (same
# resume/verify semantics) instead of forking a fourth near-identical copy
# for brief_revise_agent/facets_agent/facet_rag.
#
# Reusing RUN_ID resumes strictly from artifacts whose trace.status is
# completed -- a killed run is safe to just re-launch.
#
#   SYSTEM=<dir under data/outputs/> RUN_PY=<path> UV_GROUP=<group> \
#   EXTRA_ARGS="--backend openai --model gpt-5.6-sol ..." \
#   bash run_test119_generic_parallel.sh <run-id>
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

RUN_ID="${1:?usage: run_test119_generic_parallel.sh <run-id>}"
SYSTEM="${SYSTEM:?SYSTEM env var required (data/outputs/<SYSTEM> dir name)}"
RUN_PY="${RUN_PY:?RUN_PY env var required (path to the systems run.py)}"
UV_GROUP="${UV_GROUP:?UV_GROUP env var required}"
EXTRA_ARGS="${EXTRA_ARGS:-}"
TOPICS="${TOPICS:-data/official/trec-rag-2026-data/trec-rag-2026/test-data/trec_rag_2026_queries.tsv}"
CONCURRENCY="${CONCURRENCY:-6}"
LOG="${LOG:-tasks/task-comparison/logs/${RUN_ID}.log}"

if [[ ! "$CONCURRENCY" =~ ^[1-9][0-9]*$ ]]; then
  echo "CONCURRENCY must be a positive integer" >&2
  exit 2
fi

todo_script() {
  PYTHONPATH=src uv run --group "$UV_GROUP" python - "$TOPICS" "$RUN_ID" "$SYSTEM" <<'PY'
import json
import sys
from pathlib import Path

topics_path, run_id, system = sys.argv[1:]
topics = [line.split("\t", 1)[0] for line in
          Path(topics_path).read_text(encoding="utf-8").splitlines()
          if line.strip()]
done = set()
for path in Path(f"data/outputs/{system}").glob("*.output.json"):
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    if (obj.get("metadata", {}).get("run_id") == run_id
            and obj.get("trace", {}).get("status") == "completed"):
        done.add(str(obj["metadata"]["narrative_id"]))
print("\n".join(topic for topic in topics if topic not in done))
PY
}

mapfile -t TODO < <(todo_script)

TOTAL="$(awk 'NF {count += 1} END {print count + 0}' "$TOPICS")"
echo "run_id=$RUN_ID system=$SYSTEM topics=$TOTAL todo=${#TODO[@]} concurrency=$CONCURRENCY"
echo "run_py=$RUN_PY extra_args=$EXTRA_ARGS"
if [[ "$TOTAL" -ne 119 ]]; then
  echo "refusing: official test run requires exactly 119 topics" >&2
  exit 2
fi
if [[ "${#TODO[@]}" -eq 0 ]]; then
  echo "all topics already completed: $RUN_ID"
  exit 0
fi

mkdir -p "$(dirname "$LOG")"
export TOPICS RUN_ID RUN_PY UV_GROUP EXTRA_ARGS
printf '%s\0' "${TODO[@]}" | xargs -0 -P "$CONCURRENCY" -n 1 \
  bash -c '
    qid="$1"
    PYTHONPATH=src uv run --group "$UV_GROUP" python "$RUN_PY" \
      --qid "$qid" --topics "$TOPICS" --run-id "$RUN_ID" $EXTRA_ARGS \
      2>&1 | sed "s/^/[$qid] /"
  ' _ 2>&1 | tee -a "$LOG"

PYTHONPATH=src uv run --group "$UV_GROUP" python - "$TOPICS" "$RUN_ID" "$SYSTEM" <<'PY'
import json
import sys
from pathlib import Path

topics_path, run_id, system = sys.argv[1:]
topics = [line.split("\t", 1)[0] for line in
          Path(topics_path).read_text(encoding="utf-8").splitlines()
          if line.strip()]
completed = []
for path in Path(f"data/outputs/{system}").glob("*.output.json"):
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
