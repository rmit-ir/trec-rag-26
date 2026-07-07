#!/usr/bin/env bash
# Unattended ClimbMix corpus profiling pipeline:
#   sample shard ids -> download selected parquet -> stream profile -> render report.
#
# Intended tmux usage:
#   PROFILE_RUN=pilot ./tasks/corpus_profile/scripts/run_profile.sh 2>&1 | tee /tmp/climbmix-profile-pilot.log

set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TASK_DIR="${REPO_ROOT}/tasks/corpus_profile"

PROFILE_RUN="${PROFILE_RUN:-smoke}"
SEED="${SEED:-20260703}"
TOTAL_SHARDS="${TOTAL_SHARDS:-6543}"
REPO_ID="${REPO_ID:-karpathy/climbmix-400b-shuffle}"
SAMPLE_ROOT="${SAMPLE_ROOT:-${REPO_ROOT}/data/climbmix-profile-sample}"
RAW_DIR="${RAW_DIR:-${SAMPLE_ROOT}/raw}"
REPORTS_DIR="${REPORTS_DIR:-${TASK_DIR}/reports}"
SKIP_DOWNLOAD="${SKIP_DOWNLOAD:-0}"
FORCE_DOWNLOAD="${FORCE_DOWNLOAD:-0}"
FORCE_PROFILE="${FORCE_PROFILE:-0}"
EXAMPLES_PER_CATEGORY="${EXAMPLES_PER_CATEGORY:-20}"
EXAMPLE_CHARS="${EXAMPLE_CHARS:-6000}"
EXAMPLE_SEED="${EXAMPLE_SEED:-${SEED}}"

case "${PROFILE_RUN}" in
  smoke)
    SAMPLE_SHARDS="${SAMPLE_SHARDS:-1}"
    MAX_DOCS_PER_SHARD="${MAX_DOCS_PER_SHARD:-1000}"
    ;;
  pilot)
    SAMPLE_SHARDS="${SAMPLE_SHARDS:-10}"
    MAX_DOCS_PER_SHARD="${MAX_DOCS_PER_SHARD:-10000}"
    ;;
  onepct)
    # 66 / 6543 shards is 1.01% by shard count. With the current 10k-row
    # ClimbMix shard layout this profiles approximately 1% of documents.
    SAMPLE_SHARDS="${SAMPLE_SHARDS:-66}"
    MAX_DOCS_PER_SHARD="${MAX_DOCS_PER_SHARD:-10000}"
    ;;
  report)
    SAMPLE_SHARDS="${SAMPLE_SHARDS:-40}"
    MAX_DOCS_PER_SHARD="${MAX_DOCS_PER_SHARD:-25000}"
    ;;
  *)
    echo "[run_profile] unknown PROFILE_RUN=${PROFILE_RUN}; expected smoke|pilot|onepct|report" >&2
    exit 64
    ;;
esac

RUN_ID="${RUN_ID:-${PROFILE_RUN}-$(date -u +%Y%m%dT%H%M%SZ)}"
MANIFEST_DIR="${SAMPLE_ROOT}/manifests/${RUN_ID}"
STATS_DIR="${SAMPLE_ROOT}/stats/${RUN_ID}"
EXAMPLES_DIR="${SAMPLE_ROOT}/examples/${RUN_ID}"
LOG_DIR="${TASK_DIR}/logs"
LOG_FILE="${LOG_DIR}/${RUN_ID}.log"

mkdir -p "${MANIFEST_DIR}" "${STATS_DIR}" "${EXAMPLES_DIR}" "${REPORTS_DIR}" "${LOG_DIR}"

# Mirror all wrapper output into the task-local log, even if the caller also
# tees to /tmp. This makes tmux detach/reconnect debugging reliable.
exec > >(tee -a "${LOG_FILE}") 2>&1

log() {
  echo "[$(date -Is)] $*"
}

on_error() {
  local rc=$?
  log "FATAL: run failed at line ${BASH_LINENO[0]} with exit ${rc}"
  log "See log: ${LOG_FILE}"
  exit "${rc}"
}
trap on_error ERR

log "corpus profiling start"
log "run_id=${RUN_ID} mode=${PROFILE_RUN} seed=${SEED}"
log "sample_shards=${SAMPLE_SHARDS} total_shards=${TOTAL_SHARDS} max_docs_per_shard=${MAX_DOCS_PER_SHARD}"
log "repo_id=${REPO_ID}"
log "sample_root=${SAMPLE_ROOT}"
log "log_file=${LOG_FILE}"

cat > "${MANIFEST_DIR}/run_config.json" <<EOF
{
  "run_id": "${RUN_ID}",
  "profile_run": "${PROFILE_RUN}",
  "seed": ${SEED},
  "total_shards": ${TOTAL_SHARDS},
  "sample_shards": ${SAMPLE_SHARDS},
  "max_docs_per_shard": ${MAX_DOCS_PER_SHARD},
  "repo_id": "${REPO_ID}",
  "sample_root": "${SAMPLE_ROOT}",
  "raw_dir": "${RAW_DIR}",
  "reports_dir": "${REPORTS_DIR}",
  "skip_download": "${SKIP_DOWNLOAD}",
  "force_download": "${FORCE_DOWNLOAD}",
  "force_profile": "${FORCE_PROFILE}",
  "examples_per_category": ${EXAMPLES_PER_CATEGORY},
  "example_chars": ${EXAMPLE_CHARS},
  "example_seed": ${EXAMPLE_SEED},
  "started_at": "$(date -Is)"
}
EOF

log "step 0: uv sync task env"
uv sync --project "${TASK_DIR}"

log "step 1: sample shards"
uv run --project "${TASK_DIR}" python "${TASK_DIR}/scripts/sample_shards.py" \
  --total-shards "${TOTAL_SHARDS}" \
  --sample-shards "${SAMPLE_SHARDS}" \
  --seed "${SEED}" \
  --out-dir "${MANIFEST_DIR}"

if [[ "${SKIP_DOWNLOAD}" == "1" ]]; then
  log "step 2: download skipped by SKIP_DOWNLOAD=1"
else
  log "step 2: download sampled shards"
  download_args=(
    --manifest "${MANIFEST_DIR}/sample_manifest.jsonl"
    --raw-dir "${RAW_DIR}"
    --status-jsonl "${MANIFEST_DIR}/download_status.jsonl"
    --summary-json "${MANIFEST_DIR}/download_summary.json"
    --repo-id "${REPO_ID}"
  )
  if [[ "${FORCE_DOWNLOAD}" == "1" ]]; then
    download_args+=(--force)
  fi
  uv run --project "${TASK_DIR}" python "${TASK_DIR}/scripts/download_shards.py" "${download_args[@]}"
fi

log "step 3: profile parquet shards"
profile_args=(
  --manifest "${MANIFEST_DIR}/sample_manifest.jsonl"
  --raw-dir "${RAW_DIR}"
  --stats-dir "${STATS_DIR}"
  --examples-dir "${EXAMPLES_DIR}"
  --errors-jsonl "${MANIFEST_DIR}/profile_errors.jsonl"
  --max-docs-per-shard "${MAX_DOCS_PER_SHARD}"
  --examples-per-category "${EXAMPLES_PER_CATEGORY}"
  --example-chars "${EXAMPLE_CHARS}"
  --example-seed "${EXAMPLE_SEED}"
)
if [[ "${FORCE_PROFILE}" == "1" ]]; then
  profile_args+=(--force)
fi
uv run --project "${TASK_DIR}" python "${TASK_DIR}/scripts/profile_parquet.py" "${profile_args[@]}"

log "step 4: render report"
uv run --project "${TASK_DIR}" python "${TASK_DIR}/scripts/render_report.py" \
  --stats "${STATS_DIR}/corpus_stats.json" \
  --run-config "${MANIFEST_DIR}/run_config.json" \
  --download-summary "${MANIFEST_DIR}/download_summary.json" \
  --examples-dir "${EXAMPLES_DIR}" \
  --reports-dir "${REPORTS_DIR}" \
  --run-id "${RUN_ID}" \
  --report-name corpus_profile.md

cat > "${MANIFEST_DIR}/run_summary.json" <<EOF
{
  "run_id": "${RUN_ID}",
  "finished_at": "$(date -Is)",
  "log_file": "${LOG_FILE}",
  "report": "${REPORTS_DIR}/corpus_profile.md",
  "stats": "${STATS_DIR}/corpus_stats.json"
}
EOF

log "done"
log "report: ${REPORTS_DIR}/corpus_profile.md"
log "stats: ${STATS_DIR}/corpus_stats.json"
log "examples: ${EXAMPLES_DIR}"
