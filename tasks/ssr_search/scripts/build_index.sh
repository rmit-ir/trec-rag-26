#!/usr/bin/env bash
# Build a Cottontail burrow (SSR-searchable index) from one or more ClimbMix
# JSONL shards, using the `jsonl` app built by build_cottontail.sh.
#
#   build_index.sh <run-name> <shard.jsonl> [shard.jsonl ...]
#
# NB: apps/jsonl hardcodes the burrow name `json.burrow` in its cwd, so we cd
# into the output dir and run it there. Output lands under data/built-indexes/
# per the repo's "artifacts live under data/" rule.
#
#   --simple  : SimpleBuilder static burrow (fast to build; good for smoke tests)
#   --bigwig  : Bigwig dynamic burrow of Fiver shards (mergeable to mmap'd Hazel
#               via fiver2hazel — the production/long-term-serving format)
set -euo pipefail

ROOT=/scratch/fast/kun/projects/trec-rag-26
ENV=$ROOT/tasks/ssr_search/env
JSONL=$ROOT/tmp/Cottontail-claclark/bazel-bin/apps/jsonl
export LD_LIBRARY_PATH="$ENV/lib:${LD_LIBRARY_PATH:-}"

MODE=--simple
if [[ "${1:-}" == "--simple" || "${1:-}" == "--bigwig" ]]; then MODE=$1; shift; fi

RUN=${1:?usage: build_index.sh [--simple|--bigwig] <run-name> <shard.jsonl>...}
shift
OUT=$ROOT/data/built-indexes/ssr-$RUN
mkdir -p "$OUT"
# Absolutize shard paths before we cd.
SHARDS=(); for s in "$@"; do SHARDS+=("$(readlink -f "$s")"); done

echo "building $MODE burrow at $OUT/json.burrow from ${#SHARDS[@]} shard(s)"
cd "$OUT"
rm -rf json.burrow
SECONDS=0
"$JSONL" "$MODE" "${SHARDS[@]}"
echo "done in ${SECONDS}s -> $OUT/json.burrow"
du -sh "$OUT/json.burrow"
