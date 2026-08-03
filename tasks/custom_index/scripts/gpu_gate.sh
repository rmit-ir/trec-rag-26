#!/usr/bin/env bash
# GPU gate: block until ALL GPUs are free (zero compute processes), with a
# debounce, then exit 0 so the caller (the agent, via background-task completion)
# launches the encode+index pipeline. Does NOT launch anything itself.
#
# Logic: poll every POLL seconds. When free, wait CONFIRM seconds and re-check;
# if still free -> exit 0 (gate OPEN). If busy again during the debounce -> reset
# to polling. A failed/again-busy nvidia-smi query counts as BUSY (fail safe: we
# never declare "free" on an unreadable GPU state).
#
# Env: POLL (default 600 = 10 min), CONFIRM (default 300 = 5 min), LOG.
set -uo pipefail
POLL="${POLL:-600}"
CONFIRM="${CONFIRM:-300}"
LOG="${LOG:-tasks/custom_index/logs/gpu_gate.log}"
mkdir -p "$(dirname "$LOG")"
log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

# Echoes the number of GPU compute processes, or -1 if nvidia-smi failed.
busy_count() {
  local out rc
  out="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null)"
  rc=$?
  if [ "$rc" -ne 0 ]; then echo -1; return; fi
  printf '%s\n' "$out" | grep -c .
}

log "gpu_gate start: poll=${POLL}s debounce=${CONFIRM}s (waiting for 0 compute apps on all GPUs)"
while true; do
  n="$(busy_count)"
  if [ "$n" != "0" ]; then
    log "GPU busy/unreadable (compute_apps=${n}); recheck in ${POLL}s"
    sleep "$POLL"
    continue
  fi
  log "GPU appears FREE; confirming after ${CONFIRM}s debounce"
  sleep "$CONFIRM"
  n2="$(busy_count)"
  if [ "$n2" != "0" ]; then
    log "GPU busy again during debounce (compute_apps=${n2}); resetting to polling"
    continue
  fi
  log "GPU CONFIRMED FREE for >=${CONFIRM}s — gate OPEN, exiting 0"
  exit 0
done
