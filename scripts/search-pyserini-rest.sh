#!/usr/bin/env bash
# Search the Pyserini REST API and print all results with jq.
# Usage: scripts/search-pyserini-rest.sh "your query" [index] [hits]
set -euo pipefail

QUERY="${1:?Usage: $0 \"query\" [index] [hits]}"
INDEX="${2:-climbmix-400b}"
HITS="${3:-10}"
BASE_URL="${PYSERINI_BASE_URL:-http://99.251.12.72:8081}"

cd "$(dirname "$0")/.."

# Load the token from .env if not already in the environment.
if [[ -z "${PYSERINI_API_TOKEN:-}" && -f .env ]]; then
  set -a; . ./.env; set +a
fi
: "${PYSERINI_API_TOKEN:?PYSERINI_API_TOKEN not set (add it to .env)}"

curl -fsS --max-time 30 \
  -H "Authorization: Bearer ${PYSERINI_API_TOKEN}" \
  --get "${BASE_URL}/v1/${INDEX}/search" \
  --data-urlencode "query=${QUERY}" \
  --data-urlencode "hits=${HITS}" \
  | jq .
