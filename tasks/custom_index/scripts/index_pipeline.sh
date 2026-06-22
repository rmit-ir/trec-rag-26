#!/usr/bin/env bash
# End-to-end custom-index pipeline:
#   prepare -> encode (multi-GPU) -> build DiskANN -> sample search.
# Resumable at every step (existing per-shard outputs are skipped).
#
# No defaults anywhere for the pipeline knobs below. Set them as env vars on
# the command line, or run interactively and the script will prompt. If a
# required value is missing and stdin is not a TTY, the script aborts with
# the verbatim command line you need to re-launch.
#
# Required env vars:
#   RUN_NAME, NSHARDS, MODEL, BATCH, NUM_WORKERS, DEVICE, INDEX_KIND, METRIC, SORT,
#   GRAPH_DEGREE, COMPLEXITY, BUILD_MEM_GB, SEARCH_MEM_GB, PQ_DISK_BYTES, INDEX_THREADS
#
# NSHARDS semantics:
#   >0  -> use that many leading parquet shards (e.g. 16 for a smoke run)
#   <=0 -> use ALL shards available under data/climbmix-400b-shuffle/
#
# DiskANN knob notes (only relevant when INDEX_KIND=disk):
#   GRAPH_DEGREE   Vamana out-degree R. 64-128 typical; higher = better recall, larger index, slower build.
#   COMPLEXITY     build search list L. 100-200 typical; higher = better graph, slower build.
#   BUILD_MEM_GB   RAM cap during build. The box is SHARED — keep this conservative so that even if
#                  a build step internally doubles the cap (scratch, merge passes), peak stays under
#                  ~1 TB and leaves >=1 TB free for other users. 500 = ~5-6 partitions, slower but safe.
#   SEARCH_MEM_GB  cache budget the serve uses. The Rust serve task is sized for 64 GB.
#   PQ_DISK_BYTES  PQ bytes/vector for the in-RAM nav table. 32 -> ~18 GB resident for 563M x 256d vectors.
#                  0 = uncompressed (huge); only sane for tiny smokes.
#   INDEX_THREADS  Build parallelism. 128 = physical cores on this box (2x Xeon 8592+, 64 cores/socket).
#                  SMT (256 logical) rarely helps DiskANN — the build is memory-bandwidth bound.

set -euo pipefail
set -o errtrace
trap 'echo "[index_pipeline] FAILED at line $LINENO with exit $?" >&2' ERR

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TASK_DIR="${REPO_ROOT}/tasks/custom_index"

# ---- Required-knob handling -----------------------------------------------
declare -a MISSING=()

# (name, suggested-value-for-error-message). The suggestion is *only* used to
# build a copy-pasteable error/help message. It is never silently applied.
PARAMS=(
  "RUN_NAME=climbmix-smoke"
  "NSHARDS=16"
  "MODEL=jinaai/jina-embeddings-v5-text-nano"
  "BATCH=10"
  "NUM_WORKERS=0"
  "DEVICE=auto"
  "INDEX_KIND=memory"
  "METRIC=mips"
  "SORT=desc"
  "GRAPH_DEGREE=64"
  "COMPLEXITY=100"
  "BUILD_MEM_GB=500"
  "SEARCH_MEM_GB=64"
  "PQ_DISK_BYTES=32"
  "INDEX_THREADS=128"
)

ask_or_collect() {
  local name="$1" suggestion="$2" v="${!1:-}"
  if [[ -n "$v" ]]; then return; fi
  if [[ -t 0 ]]; then
    printf '  %s [%s]: ' "$name" "$suggestion" >&2
    local ans=""; read -r ans
    if [[ -z "$ans" ]]; then ans="$suggestion"; fi
    eval "export $name=\$ans"
  else
    MISSING+=("$name=$suggestion")
  fi
}

if [[ -t 0 ]]; then
  echo "[index_pipeline] enter values (press enter to accept the [suggested] value):" >&2
fi
for pair in "${PARAMS[@]}"; do
  ask_or_collect "${pair%%=*}" "${pair#*=}"
done

if (( ${#MISSING[@]} > 0 )); then
  cat >&2 <<EOF
[index_pipeline] missing required env var(s) (no TTY to prompt):
  ${MISSING[*]}

Re-launch with every required var set, e.g.:

  ${MISSING[*]} \\
    ./tasks/custom_index/scripts/index_pipeline.sh

(Or set just the few you want to change and rely on the ones already exported.)
EOF
  exit 64
fi

# ---- Derived paths --------------------------------------------------------
WORK_DIR="${WORK_DIR:-${TASK_DIR}/work/${RUN_NAME}}"
CORPUS_DIR="${WORK_DIR}/corpus"
ENCODED_DIR="${WORK_DIR}/encoded"
INDEX_DIR="${REPO_ROOT}/data/built-indexes/${RUN_NAME}"
LOG_DIR="${TASK_DIR}/logs"
LOG_FILE="${LOG_DIR}/index_pipeline.${RUN_NAME}.log"

mkdir -p "${WORK_DIR}" "${CORPUS_DIR}" "${ENCODED_DIR}" "${INDEX_DIR}" "${LOG_DIR}"

log() { echo "[$(date -Is)] $*" | tee -a "${LOG_FILE}"; }

log "index pipeline start  run_name=${RUN_NAME}"
log "nshards=${NSHARDS} model=${MODEL} batch=${BATCH} num_workers=${NUM_WORKERS} device=${DEVICE} kind=${INDEX_KIND} metric=${METRIC} sort=${SORT}"
log "diskann: R=${GRAPH_DEGREE} L=${COMPLEXITY} build_mem_gb=${BUILD_MEM_GB} search_mem_gb=${SEARCH_MEM_GB} pq_disk_bytes=${PQ_DISK_BYTES} threads=${INDEX_THREADS}"

# ---- 0. resolve / install task env deps (fail fast on dep issues) --------
log "step 0: uv sync task env"
uv sync --project "${TASK_DIR}" 2>&1 | tee -a "${LOG_FILE}"

# ---- 1+2. prepare ↔ encode (overlapped) ---------------------------------
# Prepare writes corpus jsonls + per-shard .ready markers + a final
# .prepare_done (or .prepare_fail on error). Encoder runs in --watch mode,
# polling the corpus dir for ready shards and exiting when the queue is
# drained AND prepare signals done. Both processes run concurrently so the
# GPUs stop sitting idle for the ~7 hours of sequential parquet -> jsonl.
log "step 1+2: prepare ↔ encode (overlapped, watch-mode)"

PREPARE_OUT="${LOG_DIR}/prepare.${RUN_NAME}.out.log"
ENCODE_OUT="${LOG_DIR}/encode.${RUN_NAME}.out.log"

# Prepare bg.
NSHARDS="${NSHARDS}" OUT_DIR="${CORPUS_DIR}" SORT="${SORT}" \
  "${TASK_DIR}/scripts/prepare_corpus.sh" \
  > >(tee -a "${LOG_FILE}" "${PREPARE_OUT}") 2>&1 &
PREPARE_PID=$!
log "prepare started pid=${PREPARE_PID} (stdout/err -> ${PREPARE_OUT})"

# Encode bg (watch mode).
uv run --project "${TASK_DIR}" python \
  "${TASK_DIR}/scripts/encode_documents.py" \
  --watch \
  --corpus-dir "${CORPUS_DIR}" \
  --out-dir "${ENCODED_DIR}" \
  --model "${MODEL}" \
  --batch-size "${BATCH}" \
  --num-workers "${NUM_WORKERS}" \
  --device "${DEVICE}" \
  > >(tee -a "${LOG_FILE}" "${ENCODE_OUT}") 2>&1 &
ENCODE_PID=$!
log "encode started pid=${ENCODE_PID} (stdout/err -> ${ENCODE_OUT})"

# Disable the orchestrator's ERR trap while we wait — `wait` returning the
# child's non-zero rc would fire the trap before we can do controlled cleanup.
trap - ERR
set +e
wait "${PREPARE_PID}"; PREPARE_RC=$?
wait "${ENCODE_PID}";  ENCODE_RC=$?
set -e

log "prepare exit=${PREPARE_RC}  encode exit=${ENCODE_RC}"
if (( PREPARE_RC != 0 || ENCODE_RC != 0 )); then
  log "prepare/encode failed — aborting pipeline"
  exit 1
fi

n_fbin=$(ls "${ENCODED_DIR}"/*.fbin 2>/dev/null | wc -l)
log "encoded ${n_fbin} shard fbin files"
[[ "${n_fbin}" -gt 0 ]] || { log "no fbin produced — aborting"; exit 1; }

# ---- 3. concat + build DiskANN index -------------------------------------
log "step 3: build DiskANN index (${INDEX_KIND})"
uv run --project "${TASK_DIR}" python \
  "${TASK_DIR}/scripts/build_diskann_index.py" \
  --encoded-dir "${ENCODED_DIR}" \
  --out-dir "${INDEX_DIR}" \
  --kind "${INDEX_KIND}" \
  --metric "${METRIC}" \
  --graph-degree "${GRAPH_DEGREE}" \
  --complexity "${COMPLEXITY}" \
  --build-mem-gb "${BUILD_MEM_GB}" \
  --search-mem-gb "${SEARCH_MEM_GB}" \
  --pq-disk-bytes "${PQ_DISK_BYTES}" \
  --threads "${INDEX_THREADS}" \
  2>&1 | tee -a "${LOG_FILE}"

# ---- 4. sample search ----------------------------------------------------
log "step 4: sample search"
uv run --project "${TASK_DIR}" python \
  "${TASK_DIR}/scripts/search.py" \
  --index-dir "${INDEX_DIR}" \
  --query "What is photosynthesis?" \
  --query "How does a transformer neural network work?" \
  --k 5 \
  2>&1 | tee -a "${LOG_FILE}"

log "index pipeline done. index at ${INDEX_DIR}"
