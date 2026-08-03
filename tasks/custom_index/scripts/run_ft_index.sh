#!/usr/bin/env bash
# Full fine-tune re-encode + DiskANN index build, reusing the EXISTING token
# store (embed text unchanged -> tokens valid; verified cosine 1.0). Runs on all
# visible GPUs. Default model is the fine-tune (encode_pretokenized default).
#
# Phase 0 is a single-shard GPU pre-flight: if that shard's vectors aren't 256-d
# with the expected count, ABORT before spending the full multi-GPU-day encode
# (honours "test one shard before the full run", autonomously).
#
# Status marker: $INDEX/.pipeline_status = RUNNING | DONE | FAIL.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
TASK="tasks/custom_index"
TOKENS="$TASK/work/climbmix-chunked/tokens"
ENC="$TASK/work/climbmix-chunked/encoded-ft"
INDEX="data/built-indexes/climbmix-chunked-ft"
LOG="$TASK/logs/run_ft_index.log"
mkdir -p "$(dirname "$LOG")" "$ENC" "$INDEX"
log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }
fail() { log "FATAL: $*"; echo FAIL > "$INDEX/.pipeline_status"; exit 1; }

echo RUNNING > "$INDEX/.pipeline_status"
log "=== fine-tune re-encode + index start ==="
nvidia-smi --query-gpu=index,name,memory.used --format=csv,noheader 2>&1 | tee -a "$LOG"

EXPECT_SHARD0=141807   # shard_00000 chunk count (known)

# --- Phase 0: single-shard GPU pre-flight (shard_00000, GPU 0) --------------
log "Phase 0: single-shard GPU pre-flight (shard_00000)"
CUDA_VISIBLE_DEVICES=0 uv run --project "$TASK" python \
  "$TASK/scripts/encode_pretokenized.py" --worker-rank 0 \
  --tokens-dir "$TOKENS" --out-dir "$ENC" \
  --batch-size 256 --device cuda --dtype auto --max-seq-len 1024 \
  --total-shards 1 --step-start-epoch 0 --stems shard_00000 \
  2>&1 | tee -a "$LOG" || fail "pre-flight encode errored"
read -r n d < <(python3 -c "import struct;f=open('$ENC/shard_00000.fbin','rb');n,dd=struct.unpack('<II',f.read(8));print(n,dd)") || fail "cannot read pre-flight fbin"
log "pre-flight fbin: n=$n dim=$d (expect n=$EXPECT_SHARD0 dim=256)"
[ "$d" = "256" ] || fail "pre-flight dim $d != 256"
[ "$n" = "$EXPECT_SHARD0" ] || fail "pre-flight count $n != $EXPECT_SHARD0"
log "Phase 0 OK"

# --- Phase 1: full encode on all GPUs (skip-existing resumes shard_00000) ----
log "Phase 1: full encode on ALL GPUs (parent auto-detects, one worker/GPU)"
uv run --project "$TASK" python "$TASK/scripts/encode_pretokenized.py" \
  --tokens-dir "$TOKENS" --out-dir "$ENC" \
  --batch-size 256 --device cuda --dtype auto --max-seq-len 1024 \
  2>&1 | tee -a "$LOG" || fail "full encode errored"
nfb=$(ls "$ENC"/*.fbin 2>/dev/null | wc -l)
log "Phase 1 done: $nfb shard fbins encoded"

# --- Phase 2: build DiskANN disk index --------------------------------------
# NB: diskannpy's C++ objects can crash during Python interpreter *teardown*
# AFTER build_diskann_index.py's main() has already returned 0 and written every
# artifact (seen 2026-08-03: ~25 h build, all files complete, non-zero exit with
# no traceback). So do NOT trust the exit code alone — verify the artifacts and
# only fail if one is missing/empty. That is the real success signal.
log "Phase 2: build DiskANN disk index -> $INDEX"
uv run --project "$TASK" python "$TASK/scripts/build_diskann_index.py" \
  --encoded-dir "$ENC" --out-dir "$INDEX" \
  --kind disk --metric mips --graph-degree 64 --complexity 100 \
  --build-mem-gb 500 --search-mem-gb 64 --pq-disk-bytes 32 --threads 128 \
  2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
for f in ann_disk.index index_meta.json encoding_meta.json docids.txt; do
  [ -s "$INDEX/$f" ] || fail "index build: missing/empty $f (builder rc=$rc)"
done
if [ "$rc" -ne 0 ]; then
  log "WARN: builder exited rc=$rc but all artifacts present — treating as a "\
"native teardown crash, not a build failure."
fi

echo DONE > "$INDEX/.pipeline_status"
log "=== DONE: fine-tune index built at $INDEX (docstore: restore from backup) ==="
