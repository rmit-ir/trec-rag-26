#!/usr/bin/env bash
# Ramping k6 load test for the SSR fan-out shim (:8099). Doubles VUs each step,
# prints a latency/throughput table (VUs/rps/p50/p95/max/err%), and stops at the
# first step where p95 > 10s (the breaking point).
#
# ── HOW TO RUN ────────────────────────────────────────────────────────────────
# 1) Get k6 once (static binary, no root; skip if `k6` is already on PATH):
#      cd /scratch/fast/kun/projects/trec-rag-26
#      curl -sSL https://github.com/grafana/k6/releases/download/v0.55.0/k6-v0.55.0-linux-amd64.tar.gz | tar xz
#      export K6="$PWD/k6-v0.55.0-linux-amd64/k6"
#
# 2) Confirm SSR is up:  curl -s localhost:8099/healthz  -> {"status":"ok","shards":26}
#
# 3) Run the ramp (defaults: local shim, VUs 2..256, 30s/step):
#      K6="$K6" bash tasks/ssr_search/scripts/ssr_loadtest.sh
#
# Variations (all env-overridable):
#   # hosted endpoint instead of the local shim:
#   SSR_URL=https://index-climbmix-ssr.dsync.net/search K6="$K6" bash tasks/ssr_search/scripts/ssr_loadtest.sh
#   # custom ramp / longer steps (e.g. pin the break between 16-32 VUs):
#   VUS="8 16 20 24 28 32" DURATION=60s K6="$K6" bash tasks/ssr_search/scripts/ssr_loadtest.sh
#   # k=N results per query (default 10):
#   K=20 K6="$K6" bash tasks/ssr_search/scripts/ssr_loadtest.sh
#   # rebuild the query set from data/outputs/aus_agent ssr search steps:
#   bash tasks/ssr_search/scripts/ssr_loadtest.sh --harvest
#
# If K6 is unset the script looks for `k6` on PATH and errors with the download hint.
# ──────────────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")"                               # so k6 finds ./ssr_loadtest_queries.json
K6="${K6:-k6}"
SSR_URL="${SSR_URL:-http://127.0.0.1:8099/search}"
VUS="${VUS:-2 4 8 16 32 64 128 256}"
DURATION="${DURATION:-30s}"
QFILE=ssr_loadtest_queries.json

# --harvest: rebuild the query set from all ssr search steps in the outputs.
if [ "${1:-}" = "--harvest" ]; then
  ROOT="$(cd ../../.. && pwd)"
  python3 - "$ROOT" > "$QFILE" <<'PY'
import glob, json, sys
root=sys.argv[1]; qs=set()
for f in glob.glob(f"{root}/data/outputs/aus_agent/*.output.json"):
    try: d=json.load(open(f))
    except Exception: continue
    for s in d.get("trace",{}).get("steps",[]):
        a=(s.get("arguments") or {}) if s.get("tool_name")=="search" else {}
        if a.get("search_engine")=="ssr" and a.get("query"): qs.add(a["query"])
json.dump(sorted(q for q in qs if q.strip()), sys.stdout)
PY
  echo "re-harvested $(python3 -c "import json;print(len(json.load(open('$QFILE'))))") SSR queries -> $QFILE"
  exit 0
fi

command -v "$K6" >/dev/null 2>&1 || { echo "k6 not found (set K6=/path/to/k6 or install; see header)"; exit 1; }
export SSR_URL
TMP="$(mktemp -d)"
echo "SSR load test -> $SSR_URL   queries=$(python3 -c "import json;print(len(json.load(open('$QFILE'))))")   steps: $VUS"
printf "%5s %7s %8s %8s %9s %9s %7s\n" VUs reqs rps p50ms p95ms maxms err%
for VU in $VUS; do
  "$K6" run --vus "$VU" --duration "$DURATION" --summary-export="$TMP/s_$VU.json" --no-color ssr_loadtest.js >/dev/null 2>&1 || true
  read -r p50 p95 mx rps cnt err <<<"$(python3 - "$TMP/s_$VU.json" <<'PY'
import json, sys
try:
    m=json.load(open(sys.argv[1]))["metrics"]; d=m["http_req_duration"]; r=m["http_reqs"]
    f=m.get("http_req_failed",{}); g=lambda o,k: o.get(k, o.get("values",{}).get(k))
    print(g(d,"med"), g(d,"p(95)"), g(d,"max"), g(r,"rate"), g(r,"count"), (g(f,"rate") or 0)*100)
except Exception:
    print("0 0 0 0 0 0")
PY
)"
  printf "%5s %7.0f %8.1f %8.0f %9.0f %9.0f %6.1f%%\n" "$VU" "$cnt" "$rps" "$p50" "$p95" "$mx" "$err"
  if python3 -c "import sys;sys.exit(0 if float('$p95')>10000 else 1)" 2>/dev/null; then
    echo ">>> BREAKING POINT (p95 > 10s) at $VU VUs"; break
  fi
done
rm -rf "$TMP"
