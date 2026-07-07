#!/usr/bin/env bash
# Unattended ClimbMix chunking comparison pipeline:
#   build eval sample -> compare chunkers -> render task-local report.

set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TASK_DIR="${REPO_ROOT}/tasks/chunking_profile"

CHUNK_PROFILE_RUN="${CHUNK_PROFILE_RUN:-smoke}"
SEED="${SEED:-20260703}"
PROFILE_RUN_ID="${PROFILE_RUN_ID:-onepct}"
PROFILE_ROOT="${PROFILE_ROOT:-${REPO_ROOT}/data/climbmix-profile-sample}"
CHUNK_ROOT="${CHUNK_ROOT:-${REPO_ROOT}/data/chunking-profile}"
RAW_DIR="${RAW_DIR:-${PROFILE_ROOT}/raw}"
PROFILE_MANIFEST="${PROFILE_MANIFEST:-${PROFILE_ROOT}/manifests/${PROFILE_RUN_ID}/sample_manifest.jsonl}"
PROFILE_STATS_DIR="${PROFILE_STATS_DIR:-${PROFILE_ROOT}/stats/${PROFILE_RUN_ID}}"
REPORTS_DIR="${REPORTS_DIR:-${TASK_DIR}/reports}"
FORCE="${FORCE:-0}"
EXAMPLE_DOCS_PER_STRATEGY="${EXAMPLE_DOCS_PER_STRATEGY:-8}"
EXAMPLE_CHARS="${EXAMPLE_CHARS:-1200}"
FORCE_LONGEST_DOCS="${FORCE_LONGEST_DOCS:-}"

case "${CHUNK_PROFILE_RUN}" in
  smoke)
    TARGET_DOCS="${TARGET_DOCS:-500}"
    ;;
  sample)
    TARGET_DOCS="${TARGET_DOCS:-5000}"
    ;;
  onepct)
    TARGET_DOCS="${TARGET_DOCS:-}"
    ;;
  *)
    echo "[run_chunking_profile] unknown CHUNK_PROFILE_RUN=${CHUNK_PROFILE_RUN}; expected smoke|sample|onepct" >&2
    exit 64
    ;;
esac

RUN_ID="${RUN_ID:-${CHUNK_PROFILE_RUN}-$(date -u +%Y%m%dT%H%M%SZ)}"
MANIFEST_DIR="${CHUNK_ROOT}/manifests/${RUN_ID}"
SAMPLE_DIR="${CHUNK_ROOT}/samples/${RUN_ID}"
STATS_DIR="${CHUNK_ROOT}/stats/${RUN_ID}"
EXAMPLES_DIR="${REPORTS_DIR}/examples/${RUN_ID}"
FIGURES_DIR="${REPORTS_DIR}/figures/${RUN_ID}"
LOG_DIR="${TASK_DIR}/logs"
LOG_FILE="${LOG_DIR}/${RUN_ID}.log"

mkdir -p "${MANIFEST_DIR}" "${SAMPLE_DIR}" "${STATS_DIR}" "${EXAMPLES_DIR}" "${FIGURES_DIR}" "${REPORTS_DIR}" "${LOG_DIR}"

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

force_args=()
if [[ "${FORCE}" == "1" ]]; then
  force_args+=(--force)
fi

target_args=()
if [[ -n "${TARGET_DOCS}" ]]; then
  target_args+=(--target-docs "${TARGET_DOCS}")
fi
if [[ -n "${FORCE_LONGEST_DOCS}" ]]; then
  target_args+=(--force-longest-docs "${FORCE_LONGEST_DOCS}")
fi

log "chunking profile start"
log "run_id=${RUN_ID} mode=${CHUNK_PROFILE_RUN} seed=${SEED}"
log "profile_manifest=${PROFILE_MANIFEST}"
log "profile_stats_dir=${PROFILE_STATS_DIR}"
log "raw_dir=${RAW_DIR}"
log "chunk_root=${CHUNK_ROOT}"
log "reports_dir=${REPORTS_DIR}"
log "log_file=${LOG_FILE}"

cat > "${MANIFEST_DIR}/run_config.json" <<EOF
{
  "run_id": "${RUN_ID}",
  "chunk_profile_run": "${CHUNK_PROFILE_RUN}",
  "seed": ${SEED},
  "target_docs": "${TARGET_DOCS}",
  "force_longest_docs": "${FORCE_LONGEST_DOCS}",
  "profile_run_id": "${PROFILE_RUN_ID}",
  "profile_manifest": "${PROFILE_MANIFEST}",
  "profile_stats_dir": "${PROFILE_STATS_DIR}",
  "raw_dir": "${RAW_DIR}",
  "chunk_root": "${CHUNK_ROOT}",
  "reports_dir": "${REPORTS_DIR}",
  "force": "${FORCE}",
  "example_docs_per_strategy": ${EXAMPLE_DOCS_PER_STRATEGY},
  "example_chars": ${EXAMPLE_CHARS},
  "started_at": "$(date -Is)"
}
EOF

log "step 0: uv sync task env"
uv sync --project "${TASK_DIR}"

log "step 1: build evaluation sample"
uv run --project "${TASK_DIR}" python "${TASK_DIR}/scripts/build_eval_sample.py" \
  --mode "${CHUNK_PROFILE_RUN}" \
  --run-id "${RUN_ID}" \
  --seed "${SEED}" \
  --profile-manifest "${PROFILE_MANIFEST}" \
  --profile-stats-dir "${PROFILE_STATS_DIR}" \
  --out-root "${CHUNK_ROOT}" \
  "${target_args[@]}" \
  "${force_args[@]}"

log "step 2: compare chunkers"
uv run --project "${TASK_DIR}" python "${TASK_DIR}/scripts/compare_chunkers.py" \
  --sample-index "${SAMPLE_DIR}/sample_index.jsonl" \
  --raw-dir "${RAW_DIR}" \
  --stats-dir "${STATS_DIR}" \
  --examples-dir "${EXAMPLES_DIR}" \
  --run-id "${RUN_ID}" \
  --seed "${SEED}" \
  --example-docs-per-strategy "${EXAMPLE_DOCS_PER_STRATEGY}" \
  --example-chars "${EXAMPLE_CHARS}" \
  "${force_args[@]}"

log "step 3: render report"
uv run --project "${TASK_DIR}" python "${TASK_DIR}/scripts/render_report.py" \
  --summary "${STATS_DIR}/chunking_summary.json" \
  --sample-summary "${SAMPLE_DIR}/sample_summary.json" \
  --reports-dir "${REPORTS_DIR}" \
  --run-id "${RUN_ID}" \
  --report-name chunking_comparison.md

cat > "${MANIFEST_DIR}/run_summary.json" <<EOF
{
  "run_id": "${RUN_ID}",
  "finished_at": "$(date -Is)",
  "log_file": "${LOG_FILE}",
  "sample_index": "${SAMPLE_DIR}/sample_index.jsonl",
  "stats": "${STATS_DIR}/chunking_summary.json",
  "report": "${REPORTS_DIR}/chunking_comparison.md",
  "teams_post": "${REPORTS_DIR}/teams_post.md",
  "figures": "${FIGURES_DIR}",
  "examples": "${EXAMPLES_DIR}"
}
EOF

log "done"
log "report: ${REPORTS_DIR}/chunking_comparison.md"
log "teams_post: ${REPORTS_DIR}/teams_post.md"
log "stats: ${STATS_DIR}/chunking_summary.json"
log "examples: ${EXAMPLES_DIR}"
