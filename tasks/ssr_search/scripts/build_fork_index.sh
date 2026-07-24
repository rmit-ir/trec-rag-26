#!/usr/bin/env bash
# Build the full ClimbMix corpus as N stemmed SimpleWarren *group-burrows* with
# the fork's cottontail-jsonl-index, in parallel. SimpleWarren has no merge and
# the fork server is single-burrow, so a group == the unit for BOTH parallel
# build AND serving (each group gets its own cottontail-jsonl-server; a thin
# fan-out queries all groups + routes get_document to the owning one).
#
#   build_fork_index.sh              # driver: fan groups out at PARALLEL
#   build_fork_index.sh --one <g>    # build a single group (internal)
#
# Env: GROUP_SIZE (default 256), PARALLEL (default 24), STEM (default porter),
#      OUT_NAME (default fork-climbmix-full).
set -euo pipefail

ROOT=/scratch/fast/kun/projects/trec-rag-26
ENV=$ROOT/tasks/ssr_search/env
BIN=$ROOT/tmp/Cottontail-uwaterloo/bazel-bin/apps
COLL=$ROOT/data/climbmix-bm25-collection
OUT=$ROOT/data/built-indexes/${OUT_NAME:-fork-climbmix-full}
export LD_LIBRARY_PATH="$ENV/lib:${LD_LIBRARY_PATH:-}"
GROUP_SIZE=${GROUP_SIZE:-256}
PARALLEL=${PARALLEL:-24}
STEM=${STEM:-porter}
SELF=$(readlink -f "$0")
mkdir -p "$OUT"

mapfile -t ALL < <(ls "$COLL"/shard_*.jsonl | sort)
TOTAL=${#ALL[@]}
NGROUPS=$(( (TOTAL + GROUP_SIZE - 1) / GROUP_SIZE ))

group_dir(){ printf "%s/group_%04d" "$OUT" "$1"; }
group_done(){ [ -f "$1/burrow/.done" ]; }   # sentinel written on success

build_one(){
  local g=$1
  local gdir; gdir=$(group_dir "$g")
  local burrow="$gdir/burrow"
  if group_done "$gdir"; then echo "group_$g SKIP (done)"; return 0; fi
  rm -rf "$gdir"; mkdir -p "$gdir/in"
  local start=$(( g * GROUP_SIZE ))
  local shards=( "${ALL[@]:start:GROUP_SIZE}" )
  for s in "${shards[@]}"; do ln -s "$s" "$gdir/in/"; done
  local stemflag=""; [ -n "$STEM" ] && stemflag="--stem $STEM"
  local t0=$SECONDS rc=0
  "$BIN/cottontail-jsonl-index" --input "$gdir/in" --burrow "$burrow" \
      --docno-field id $stemflag --overwrite > "$gdir/build.out" 2>&1 || rc=$?
  rm -rf "$gdir/in"
  local dt=$(( SECONDS - t0 ))
  if [ "$rc" -ne 0 ] || ! grep -q '"rows_indexed"' "$gdir/build.out"; then
    echo "group_$g FAIL rc=$rc after ${dt}s (see $gdir/build.out)"; return 1
  fi
  touch "$burrow/.done"
  echo "group_$g OK ${dt}s $(du -sh "$burrow" | cut -f1) ($(grep -oE '"rows_indexed": [0-9]+' "$gdir/build.out" | grep -oE '[0-9]+') docs)"
}

if [ "${1:-}" = "--one" ]; then build_one "$2"; exit $?; fi

echo "[$(date '+%F %T')] FORK BUILD: $TOTAL shards, GROUP_SIZE=$GROUP_SIZE -> $NGROUPS groups, PARALLEL=$PARALLEL, STEM=$STEM"
echo "output: $OUT"
done0=0; for ((g=0; g<NGROUPS; g++)); do group_done "$(group_dir "$g")" && done0=$((done0+1)); done
echo "resume: $done0/$NGROUPS already done"
seq 0 $((NGROUPS-1)) | xargs -P "$PARALLEL" -I{} bash "$SELF" --one {} 2>&1 || true
done_now=0; for ((g=0; g<NGROUPS; g++)); do group_done "$(group_dir "$g")" && done_now=$((done_now+1)); done
echo "[$(date '+%F %T')] FORK BUILD END: $done_now/$NGROUPS groups, total $(du -sh "$OUT" 2>/dev/null | cut -f1)"
[ "$done_now" -eq "$NGROUPS" ] || { echo "WARNING: $((NGROUPS-done_now)) missing — re-run to resume"; exit 1; }
