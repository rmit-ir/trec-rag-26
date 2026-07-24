#!/usr/bin/env bash
# Launch one cottontail-jsonl-server per fork group-burrow (ports BASE+g), each
# single-burrow + page-cache-bounded. The Python shim (fork_shim.py) fans a
# query across all of these via MultiShardSearchEngine.
#
#   launch_fork_servers.sh            # launch all groups
#   launch_fork_servers.sh stop       # kill all launched servers
#
# Env: BASE_PORT (7000), THREADS (4), RANK_THREADS (2).
#
# NB: group paths are built BY INDEX with printf (group_%04d), NOT by globbing
# into a bash array -- `GROUPS=( "$OUT"/group_* )` returns junk on this /scratch
# filesystem (ls/compgen/printf glob all give the right 26, but array-glob does
# not; unexplained readdir quirk). compgen -G is used only to COUNT groups.
set -euo pipefail

ROOT=/scratch/fast/kun/projects/trec-rag-26
ENV=$ROOT/tasks/ssr_search/env
BIN=$ROOT/tmp/Cottontail/bazel-bin/apps/cottontail-jsonl-server
OUT=$ROOT/data/built-indexes/fork-climbmix-full
LOGDIR=/tmp/fork-servers
export LD_LIBRARY_PATH="$ENV/lib:${LD_LIBRARY_PATH:-}"
BASE_PORT=${BASE_PORT:-7000}
THREADS=${THREADS:-4}
RANK_THREADS=${RANK_THREADS:-2}
# paragraph-aware evidence band (server-side); mirrors the pipeline chunk_band
BAND_MIN=${BAND_MIN:-200}
BAND_TARGET=${BAND_TARGET:-500}
BAND_MAX=${BAND_MAX:-700}

NG=$(compgen -G "$OUT/group_*" | wc -l)
group_dir(){ printf "%s/group_%04d" "$OUT" "$1"; }

if [ "${1:-}" = "stop" ]; then
  for ((g=0; g<NG; g++)); do
    port=$((BASE_PORT + g))
    pid=$(cat "$LOGDIR/server_$port.pid" 2>/dev/null || true)
    [ -n "$pid" ] && kill "$pid" 2>/dev/null && echo "killed $port (pid $pid)" || true
  done
  exit 0
fi

mkdir -p "$LOGDIR"
echo "[$(date '+%F %T')] launching $NG fork servers, ports $BASE_PORT..$((BASE_PORT+NG-1)), threads=$THREADS rank-threads=$RANK_THREADS"
for ((g=0; g<NG; g++)); do
  port=$((BASE_PORT + g))
  burrow="$(group_dir "$g")/burrow"
  if [ ! -f "$burrow/dna" ]; then echo "MISSING $burrow/dna -- skipping"; continue; fi
  old=$(cat "$LOGDIR/server_$port.pid" 2>/dev/null || true)
  [ -n "$old" ] && kill "$old" 2>/dev/null || true
  setsid "$BIN" --burrow "$burrow" --host 127.0.0.1 --port "$port" \
      --threads "$THREADS" --rank-threads "$RANK_THREADS" --no-auth \
      --paragraph --band-min "$BAND_MIN" --band-target "$BAND_TARGET" \
      --band-max "$BAND_MAX" \
      > "$LOGDIR/server_$port.log" 2>&1 &
  echo $! > "$LOGDIR/server_$port.pid"
done
echo "launched. waiting for /healthz on all $NG ..."
ok=0
for ((g=0; g<NG; g++)); do
  port=$((BASE_PORT + g))
  for _ in $(seq 1 120); do
    if curl -sf "http://127.0.0.1:$port/healthz" >/dev/null 2>&1; then ok=$((ok+1)); break; fi
    sleep 0.5
  done
done
echo "[$(date '+%F %T')] healthy: $ok/$NG (logs in $LOGDIR)"
[ "$ok" -eq "$NG" ] || { echo "WARNING: $((NG-ok)) servers not healthy"; exit 1; }
