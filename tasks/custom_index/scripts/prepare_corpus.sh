#!/usr/bin/env bash
# Prepare per-shard ClimbMix corpus-jsonl files (one jsonl per parquet shard)
# using the official skill script. Resumable: existing non-empty outputs are
# skipped.
#
# This step is overlapped with encode in index_pipeline.sh — both run in
# parallel. Coordination happens via filesystem markers in OUT_DIR:
#
#   shard_NNNNN.jsonl.ready   touched after this shard's jsonl is final
#                             (encoder only picks up shards with this marker)
#   .prepare_done             touched at the very end on success
#                             (encoder drains then exits 0)
#   .prepare_fail             touched on any prepare error
#                             (encoder finishes its in-flight shard then exits 1)
#
# Atomicity per shard:
#   corpus.py -> ${out}.unsorted        (non-atomic write to staging name)
#   sort.py   -> ${out}                 (.tmp + rename inside the sort script)
#   rm        ${out}.unsorted
#   touch     ${out}.ready              (visible to encoder only now)
#
# Required env vars (no defaults — set by the caller, e.g. index_pipeline.sh):
#   NSHARDS  >0  -> use that many leading shards
#            <=0 -> use ALL shards available under data/climbmix-400b-shuffle/
#   OUT_DIR  output directory
#   SORT     none|desc|asc — post-sort each shard's jsonl by contents length
#            so the encoder gets length-bucketed batches and wastes less time
#            on padded short docs. Docids stay attached (they were assigned in
#            original parquet row order before this sort).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TASK_DIR="${REPO_ROOT}/tasks/custom_index"
SHARDS_DIR="${REPO_ROOT}/data/climbmix-400b-shuffle"
CORPUS_SCRIPT="${REPO_ROOT}/skills/trec-rag-climbmix-corpus-creation/scripts/create_climbmix_corpus.py"
SORT_SCRIPT="${TASK_DIR}/scripts/sort_corpus_by_length.py"

: "${NSHARDS:?NSHARDS must be set by the caller}"
: "${OUT_DIR:?OUT_DIR must be set by the caller}"
: "${SORT:?SORT must be set by the caller (none|desc|asc)}"
LOG_DIR="${TASK_DIR}/logs"
LOG_FILE="${LOG_DIR}/prepare.log"

mkdir -p "${OUT_DIR}" "${LOG_DIR}"

# Clear stale termination markers from any prior run before we start, then
# arm an ERR trap that signals encode.
rm -f "${OUT_DIR}/.prepare_done" "${OUT_DIR}/.prepare_fail"
trap 'rc=$?; echo "[$(date -Is)] prepare FAILED (rc=$rc) at line $LINENO" | tee -a "${LOG_FILE}" >&2; touch "${OUT_DIR}/.prepare_fail"; exit $rc' ERR

if (( NSHARDS > 0 )); then
  mapfile -t SHARDS < <(ls "${SHARDS_DIR}"/shard_*.parquet 2>/dev/null | sort | head -n "${NSHARDS}")
else
  mapfile -t SHARDS < <(ls "${SHARDS_DIR}"/shard_*.parquet 2>/dev/null | sort)
fi
if (( ${#SHARDS[@]} == 0 )); then
  echo "no parquet shards found under ${SHARDS_DIR}" | tee -a "${LOG_FILE}" >&2
  exit 1
fi

nshards_label="${NSHARDS}"
(( NSHARDS <= 0 )) && nshards_label="all(${#SHARDS[@]})"
echo "[$(date -Is)] prepare start — nshards=${nshards_label} out_dir=${OUT_DIR}" | tee -a "${LOG_FILE}"

for parquet in "${SHARDS[@]}"; do
  stem="$(basename "${parquet}" .parquet)"
  out="${OUT_DIR}/${stem}.jsonl"
  ready="${out}.ready"
  staging="${out}.unsorted"

  # Resumable skip: a *.ready marker means the final jsonl is on disk and
  # complete from a prior run.
  if [[ -f "${ready}" && -s "${out}" ]]; then
    echo "[$(date -Is)] skip ${stem} (ready, $(wc -l < "${out}") lines)" | tee -a "${LOG_FILE}"
    continue
  fi
  # Stale partial: jsonl exists but no .ready -> redo.
  rm -f "${out}" "${ready}" "${staging}"

  echo "[$(date -Is)] preparing ${stem} -> ${out}" | tee -a "${LOG_FILE}"
  uv run --project "${TASK_DIR}" python "${CORPUS_SCRIPT}" \
    "${parquet}" -o "${staging}" --format corpus-jsonl \
    2>&1 | tee -a "${LOG_FILE}"
  if [[ "${SORT}" != "none" ]]; then
    # sort_corpus_by_length.py writes ${out} atomically via .tmp + rename.
    uv run --project "${TASK_DIR}" python "${SORT_SCRIPT}" \
      "${staging}" -o "${out}" --order "${SORT}" \
      2>&1 | tee -a "${LOG_FILE}"
    rm -f "${staging}"
  else
    mv "${staging}" "${out}"
  fi
  # ${out} is now final on disk; mark ready *last* so the encoder won't pick
  # up a partial file in a race.
  touch "${ready}"
  echo "[$(date -Is)] done ${stem}: $(wc -l < "${out}") lines" | tee -a "${LOG_FILE}"
done

n_jsonl=$(ls "${OUT_DIR}"/*.jsonl 2>/dev/null | wc -l)
echo "[$(date -Is)] prepare done. ${n_jsonl} shard jsonl files in ${OUT_DIR}" | tee -a "${LOG_FILE}"

# Last write on the success path. Encoder polls for this and drains.
touch "${OUT_DIR}/.prepare_done"
