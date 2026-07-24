#!/usr/bin/env bash
# Build the WHOLE ClimbMix corpus (6,543 shards) as SSR-searchable Hazel burrows.
#
# Strategy: contiguous groups of GROUP_SIZE shards, each built independently:
#     jsonl --bigwig <group shards>   -> Bigwig burrow (fivers auto-consolidated)
#     finish-merging <burrow>         -> converge to ONE mmap'd Hazel per group
# Groups are independent, so the build fans out with bounded parallelism.
# Serving: point ssr-server at every group's json.burrow (SSR scores per-document
# intervals, so per-group address spaces are fine; docnos stay globally unique).
# An OPTIONAL final merge-hazels pass can weld all groups into one monolithic
# single-string Hazel (see --weld), but that is a 3.3 TB rewrite and not required.
#
# RAM safety: each concurrent group build is one process peaking at ~the size of
# its largest in-flight consolidation. We measure group 0's real peak first, then
# cap parallelism to keep total under RAM_BUDGET_GB.
#
# Resumable: a group whose burrow already holds exactly one hazel is skipped; a
# partial/failed burrow is deleted and rebuilt. Safe to re-run after any crash.
#
# Modes:
#   build_full_index.sh                 # driver: probe + fan out (background me)
#   build_full_index.sh --one <g>       # build a single group (used internally)
set -euo pipefail

SELF=$(readlink -f "$0")               # absolute path for self re-invocation
ROOT=/scratch/fast/kun/projects/trec-rag-26
ENV=$ROOT/tasks/ssr_search/env
BIN=$ROOT/tmp/Cottontail-claclark/bazel-bin/apps
COLL=$ROOT/data/climbmix-bm25-collection
OUT=$ROOT/data/built-indexes/${OUT_NAME:-ssr-climbmix-full}
export LD_LIBRARY_PATH="$ENV/lib:${LD_LIBRARY_PATH:-}"

GROUP_SIZE=${GROUP_SIZE:-16}
RAM_BUDGET_GB=${RAM_BUDGET_GB:-120}   # cap this build's total RSS (box shares RAM)
PARALLEL_CAP=${PARALLEL_CAP:-14}      # never exceed this many concurrent builds
LOG=$OUT/build.log
mkdir -p "$OUT"

mapfile -t ALL < <(ls "$COLL"/shard_*.jsonl | sort)
TOTAL=${#ALL[@]}
NGROUPS=$(( (TOTAL + GROUP_SIZE - 1) / GROUP_SIZE ))

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

group_dir(){ printf "%s/group_%04d" "$OUT" "$1"; }

# Is a group already complete (exactly one hazel, no leftover shards)?
group_done(){
  local burrow="$1/json.burrow"
  [ -d "$burrow" ] || return 1
  local nshards nhazel
  nshards=$(ls "$burrow" 2>/dev/null | grep -cE '^(fiver|hazel)\.' || true)
  nhazel=$(ls "$burrow" 2>/dev/null | grep -c '^hazel\.' || true)
  [ "$nshards" = "1" ] && [ "$nhazel" = "1" ]
}

# ---- build a single group (self-contained; recomputes its own shard slice) ----
build_one(){
  local g=$1
  local gdir; gdir=$(group_dir "$g")
  local burrow="$gdir/json.burrow"
  if group_done "$gdir"; then
    echo "group_$g SKIP (done)"; return 0
  fi
  rm -rf "$burrow"; mkdir -p "$gdir"
  local start=$(( g * GROUP_SIZE ))
  local shards=( "${ALL[@]:start:GROUP_SIZE}" )
  local t0=$SECONDS rc=0
  {
    echo "=== group $g: ${#shards[@]} shards, $(date '+%F %T') ==="
    ( cd "$gdir" && "$BIN/jsonl" --bigwig "${shards[@]}" )
    "$BIN/finish-merging" "$burrow"
  } >"$gdir/build.out" 2>&1 || rc=$?
  local dt=$(( SECONDS - t0 ))
  if [ "$rc" -ne 0 ] || ! group_done "$gdir"; then
    echo "group_$g FAIL rc=$rc after ${dt}s (see $gdir/build.out)"; return 1
  fi
  echo "group_$g OK ${dt}s $(du -sh "$burrow" | cut -f1)"
}

# Sample peak combined RSS (kB) of the build binaries while a probe pid runs.
# We match by comm name (jsonl/finish-merging) rather than by process-tree, so
# it is robust to bash exec/subshell nesting. Only valid when a single build is
# running (the probe), which is the only place we call it.
peak_rss_of(){
  local pid=$1 peak=0 rss
  while kill -0 "$pid" 2>/dev/null; do
    rss=$(ps -C jsonl -C finish-merging -o rss= 2>/dev/null | awk '{s+=$1} END{print s+0}')
    [ "$rss" -gt "$peak" ] && peak=$rss
    sleep 1
  done
  echo "$peak"
}

if [ "${1:-}" = "--one" ]; then
  build_one "$2"; exit $?
fi

# ---------------------------- driver ----------------------------
log "FULL BUILD start: $TOTAL shards, GROUP_SIZE=$GROUP_SIZE -> $NGROUPS groups"
log "output: $OUT   RAM_BUDGET_GB=$RAM_BUDGET_GB  PARALLEL_CAP=$PARALLEL_CAP"

# Count groups already done (resume).
done0=0
for ((g=0; g<NGROUPS; g++)); do group_done "$(group_dir "$g")" && done0=$((done0+1)); done
log "resume: $done0/$NGROUPS groups already complete"

# --- Probe: build the first not-done group, measuring peak RSS ---
probe_g=-1
for ((g=0; g<NGROUPS; g++)); do
  if ! group_done "$(group_dir "$g")"; then probe_g=$g; break; fi
done

if [ "$probe_g" -ge 0 ]; then
  log "probe: building group $probe_g to measure peak RSS ..."
  bash "$SELF" --one "$probe_g" &
  ppid=$!
  peak_kb=$(peak_rss_of "$ppid")
  wait "$ppid" || { log "probe group FAILED, aborting"; exit 1; }
  peak_gb=$(( peak_kb / 1024 / 1024 ))
  [ "$peak_gb" -lt 1 ] && peak_gb=1
  parallel=$(( RAM_BUDGET_GB / (peak_gb + 1) ))   # +1 headroom per process
  [ "$parallel" -gt "$PARALLEL_CAP" ] && parallel=$PARALLEL_CAP
  [ "$parallel" -lt 1 ] && parallel=1
  log "probe: group $probe_g peak RSS ~${peak_gb} GB -> parallelism=$parallel"
else
  parallel=$PARALLEL_CAP
  log "all groups already built? parallelism=$parallel"
fi

# --- Fan out the remaining groups, $parallel at a time ---
log "fanning out remaining groups at parallelism=$parallel"
seq 0 $((NGROUPS-1)) \
  | xargs -P "$parallel" -I{} bash "$SELF" --one {} \
  2>&1 | tee -a "$LOG" || true

# --- Final tally ---
done_now=0
for ((g=0; g<NGROUPS; g++)); do group_done "$(group_dir "$g")" && done_now=$((done_now+1)); done
tot_size=$(du -sh "$OUT" 2>/dev/null | cut -f1)
log "FULL BUILD end: $done_now/$NGROUPS groups complete, total $tot_size"
if [ "$done_now" -ne "$NGROUPS" ]; then
  log "WARNING: $((NGROUPS-done_now)) group(s) missing — re-run to resume"
  exit 1
fi
log "ALL GROUPS COMPLETE. Serve with: ssr-server : :contents: :id: $OUT/group_*/json.burrow"
