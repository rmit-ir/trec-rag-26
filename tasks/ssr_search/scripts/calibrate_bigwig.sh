#!/usr/bin/env bash
# Timed, RAM-tracked end-to-end calibration of the --bigwig -> Hazel path, so we
# can multiply a measured per-shard rate by 6,543 instead of extrapolating from
# a single --simple build.
#
#   calibrate_bigwig.sh <run-name> <N-shards>
#
# Stages (each timed; peak RSS sampled via a /proc poller):
#   1. jsonl --bigwig <shards...>   -> Bigwig burrow; background workers already
#                                      consolidate fivers -> hazels during ingest
#   2. finish-merging <burrow>      -> reopen the Bigwig warren so its background
#                                      workers finish consolidation and DELETE
#                                      superseded shards, converging to ONE mmap'd
#                                      hazel.<0>.<N> (the paper's single-string
#                                      model). NB: fiver2hazel --merge alone does
#                                      NOT prune source shards (each needs >=2
#                                      covering pieces), so it loops; finish-merging
#                                      is the correct convergence tool.
# Prints a summary table + writes it to the burrow dir as calibrate.txt.
set -euo pipefail

ROOT=/scratch/fast/kun/projects/trec-rag-26
ENV=$ROOT/tasks/ssr_search/env
BIN=$ROOT/tmp/Cottontail-claclark/bazel-bin/apps
COLL=$ROOT/data/climbmix-bm25-collection
export LD_LIBRARY_PATH="$ENV/lib:${LD_LIBRARY_PATH:-}"

RUN=${1:?usage: calibrate_bigwig.sh <run-name> <N-shards>}
N=${2:?usage: calibrate_bigwig.sh <run-name> <N-shards>}
OUT=$ROOT/data/built-indexes/ssr-$RUN
BURROW=$OUT/json.burrow
SUMMARY=$OUT/calibrate.txt

mkdir -p "$OUT"
rm -rf "$BURROW"

# Pick the first N shards, absolutize.
mapfile -t SHARDS < <(ls "$COLL"/shard_*.jsonl | head -n "$N")
[ "${#SHARDS[@]}" -eq "$N" ] || { echo "only found ${#SHARDS[@]} shards"; exit 1; }
IN_BYTES=$(du -cb "${SHARDS[@]}" | tail -1 | cut -f1)

# Run a command, sampling the whole process-tree's RSS every 0.5s; echo
# "<elapsed_s> <peak_rss_kb>". Uses pgrep on the child pid's process group.
run_timed() {
  local label=$1; shift
  echo ">>> [$label] $*" >&2
  local t0=$SECONDS
  "$@" &
  local pid=$!
  local peak=0
  while kill -0 "$pid" 2>/dev/null; do
    # sum RSS (kB) of the pid and all its descendants
    local rss
    rss=$(ps -o rss= --ppid "$pid" -p "$pid" 2>/dev/null | awk '{s+=$1} END{print s+0}')
    [ "$rss" -gt "$peak" ] && peak=$rss
    sleep 0.5
  done
  wait "$pid"
  local rc=$?
  local dt=$((SECONDS - t0))
  echo "$dt $peak $rc"
}

cd "$OUT"
echo "=== calibrate --bigwig->hazel: $N shards, $((IN_BYTES/1024/1024)) MB in ==="

# --- Stage 1: jsonl --bigwig -----------------------------------------------
read -r BUILD_S BUILD_RSS BUILD_RC < <(run_timed "jsonl --bigwig" \
  "$BIN/jsonl" --bigwig "${SHARDS[@]}")
[ "$BUILD_RC" -eq 0 ] || { echo "jsonl --bigwig FAILED rc=$BUILD_RC"; exit 1; }
SHARDS_AFTER_BUILD=$(ls "$BURROW" | grep -cE '^(fiver|hazel)\.' || true)
SIZE_AFTER_BUILD=$(du -sb "$BURROW" | cut -f1)

# --- Stage 2: finish-merging (converge to a single mmap'd Hazel) -------------
read -r MERGE_S MERGE_RSS MERGE_RC < <(run_timed "finish-merging" \
  "$BIN/finish-merging" "$BURROW")
[ "$MERGE_RC" -eq 0 ] || { echo "finish-merging FAILED rc=$MERGE_RC"; exit 1; }
SHARDS_AFTER_MERGE=$(ls "$BURROW" | grep -cE '^(fiver|hazel)\.' || true)
HAZELS=$(ls "$BURROW" | grep -E '^hazel\.' || true)
SIZE_AFTER_MERGE=$(du -sb "$BURROW" | cut -f1)

fmt_mb() { echo "$(( $1 / 1024 / 1024 )) MB"; }
{
  echo "===== --bigwig -> Hazel calibration ($RUN) ====="
  echo "shards:            $N"
  echo "input text:        $(fmt_mb "$IN_BYTES")"
  echo
  echo "stage 1  jsonl --bigwig"
  echo "  wall:            ${BUILD_S}s   ($(awk "BEGIN{printf \"%.1f\", $BUILD_S/$N}")s/shard)"
  echo "  peak RSS:        $(( BUILD_RSS / 1024 )) MB"
  echo "  shards produced: $SHARDS_AFTER_BUILD (fiver/hazel)"
  echo "  burrow size:     $(fmt_mb "$SIZE_AFTER_BUILD")"
  echo
  echo "stage 2  finish-merging (converge -> single Hazel)"
  echo "  wall:            ${MERGE_S}s"
  echo "  peak RSS:        $(( MERGE_RSS / 1024 )) MB"
  echo "  shards after:    $SHARDS_AFTER_MERGE"
  echo "  final hazel(s):  $HAZELS"
  echo "  burrow size:     $(fmt_mb "$SIZE_AFTER_MERGE")"
  echo
  TOTAL_S=$(( BUILD_S + MERGE_S ))
  echo "total wall:        ${TOTAL_S}s   ($(awk "BEGIN{printf \"%.1f\", $TOTAL_S/$N}")s/shard)"
  echo "index:in ratio:    $(awk "BEGIN{printf \"%.3f\", $SIZE_AFTER_MERGE/$IN_BYTES}")"
  echo
  echo "--- extrapolation to full corpus (6543 shards) ---"
  echo "  serial build-only CPU-time: $(awk "BEGIN{printf \"%.1f h\", $BUILD_S/$N*6543/3600}")"
  echo "  projected final index size: $(awk "BEGIN{printf \"%.2f TB\", $SIZE_AFTER_MERGE/$IN_BYTES*1.6}")"
} | tee "$SUMMARY"
