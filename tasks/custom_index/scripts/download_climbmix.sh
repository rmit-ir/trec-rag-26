#!/usr/bin/env bash
# Download karpathy/climbmix-400b-shuffle into data/climbmix-400b-shuffle/.
# Resumable; safe to re-run. Uses uvx so no system pollution.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DEST="${REPO_ROOT}/data/climbmix-400b-shuffle"
LOG_DIR="${REPO_ROOT}/tasks/custom_index/logs"
LOG_FILE="${LOG_DIR}/download.log"

mkdir -p "${DEST}" "${LOG_DIR}"

echo "[$(date -Is)] starting download of karpathy/climbmix-400b-shuffle -> ${DEST}" | tee -a "${LOG_FILE}"

# Enable Xet high-perf transfer (huggingface_hub >=1.0 replacement for hf_transfer).
export HF_XET_HIGH_PERFORMANCE="${HF_XET_HIGH_PERFORMANCE:-1}"
# Force progress bars to render even when stdout is not a TTY.
export HF_HUB_DISABLE_PROGRESS_BARS=0
export FORCE_COLOR=1

# `script` allocates a PTY so tqdm progress bars render into the log; -f flushes
# on every write so `tail -f` shows live progress.
script -qfc "uvx --from huggingface_hub hf download \
  karpathy/climbmix-400b-shuffle \
  --repo-type dataset \
  --local-dir '${DEST}'" /dev/null \
  2>&1 | tee -a "${LOG_FILE}"

echo "[$(date -Is)] download finished" | tee -a "${LOG_FILE}"
