#!/usr/bin/env bash
# Run one aus_agent arm over a topics file with N topics in flight at once.
#
# `run.py --all` walks topics sequentially. On the 30 research-rubric dev topics
# that is the whole wall clock: model turns average ~12s and nothing rate-limits,
# but each topic needs ~6.5 rounds, so a topic costs ~100s and an arm costs ~50
# minutes. Topics are completely independent — separate conversations, separate
# artifact files — so the only reason they were serial is that the runner loops.
#
# At CONCURRENCY=6 an arm drops to roughly 9 minutes, which is what makes a
# 24-hour optimization loop able to screen every single-factor patch and still
# have room for combination rounds. The binding constraint on the loop is agent
# generation time, not judging and not money.
#
# Already-completed topics are skipped by inspecting data/outputs directly, so a
# killed run resumes exactly like `--all --skip-existing` would.
#
#   bash tasks/task-comparison/scripts/run_topics_parallel.sh <variant> [run_id]
#
# Env: TOPICS, MODEL, ENGINES, K, MAXCOMMIT, CONCURRENCY, BACKEND.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

VARIANT="${1:?usage: run_topics_parallel.sh <variant> [run_id]}"
RUN_ID="${2:-rubric-dev30-$VARIANT}"
TOPICS="${TOPICS:-data/official/trec-rag-2026-data/trec-rag-2026/development-data/topics/research-rubrics-topics-dev.tsv}"
BACKEND="${BACKEND:-openai}"
MODEL="${MODEL:-}"
ENGINES="${ENGINES:-semantic,keyword}"
K="${K:-20}"
MAXCOMMIT="${MAXCOMMIT:-20}"
CONCURRENCY="${CONCURRENCY:-6}"
LOGDIR="tasks/task-comparison/logs"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/$RUN_ID.log"

# Which topics still need answering, decided from the artifacts rather than
# from this script's own bookkeeping — the artifacts are the only durable truth
# and they survive a kill.
mapfile -t TODO < <(
  PYTHONPATH=src uv run --group aus-agent python - "$TOPICS" "$RUN_ID" <<'PY'
import glob, json, sys
from pathlib import Path
topics_path, run_id = sys.argv[1], sys.argv[2]
want = [l.split("\t", 1)[0].strip()
        for l in Path(topics_path).read_text(encoding="utf-8").splitlines()
        if l.strip()]
done = set()
for path in glob.glob("data/outputs/aus_agent/*.output.json"):
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        continue
    meta = obj.get("metadata", {})
    # `obj["answer"]` is truthy for a FAILED run too -- the stub is a single
    # sentence reading "Run failed: ...". Resuming on that marks the topic done
    # and the arm silently ships 29 answers plus one error message. Only a
    # completed trace counts.
    if (meta.get("run_id") == run_id
            and (obj.get("trace") or {}).get("status") == "completed"):
        done.add(meta.get("narrative_id"))
print("\n".join(q for q in want if q not in done))
PY
)

TOTAL=$(grep -c . "$TOPICS")
echo "=== $(date -Is) $RUN_ID variant=$VARIANT ==="
echo "topics=$TOPICS  todo=${#TODO[@]}/$TOTAL  concurrency=$CONCURRENCY"
echo "backend=$BACKEND model=${MODEL:-<env default>} engines=$ENGINES k=$K max-committed=$MAXCOMMIT"
if [ "${#TODO[@]}" -eq 0 ]; then echo "nothing to do"; exit 0; fi

printf '%s\n' "${TODO[@]}" | xargs -P "$CONCURRENCY" -I{} sh -c '
  PYTHONPATH=src uv run --group aus-agent python src/systems/aus_agent/run.py \
    --qid "$1" --topics "'"$TOPICS"'" --backend "'"$BACKEND"'" \
    '"${MODEL:+--model $MODEL}"' \
    --search-backends "'"$ENGINES"'" --k '"$K"' \
    --max-committed-per-step '"$MAXCOMMIT"' \
    --prompt-variant "'"$VARIANT"'" --run-id "'"$RUN_ID"'" 2>&1 |
    sed "s/^/[$1] /"
' _ {} 2>&1 | tee -a "$LOG"

echo "=== $(date -Is) $RUN_ID DONE ==="
