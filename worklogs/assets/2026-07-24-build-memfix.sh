#!/usr/bin/env bash
# Build cottontail-jsonl-server INSIDE the memfix worktree with a DEDICATED
# bazel output_user_root (tmp/.bazel-memfix) so it does not clobber the main
# checkout's bazel state. Adapted from tasks/ssr_search/scripts/build_cottontail.sh.
set -euo pipefail

ROOT=/scratch/fast/kun/projects/trec-rag-26
ENV=$ROOT/tasks/ssr_search/env
CT=$ROOT/tmp/Cottontail-memfix                 # the worktree

export PATH="$ENV/bin:$PATH"
export CC="$ENV/bin/x86_64-conda-linux-gnu-gcc"
export CXX="$ENV/bin/x86_64-conda-linux-gnu-g++"
export BAZELISK_HOME="$ROOT/tmp/.bazelisk"
OUTPUT_USER_ROOT="$ROOT/tmp/.bazel-memfix"     # DEDICATED to this worktree

cd "$CT"
SYSROOT_INC="$($CXX -print-sysroot)/usr/include"
for h in zlib.h zconf.h; do
  [ -e "$SYSROOT_INC/$h" ] || ln -s "$ENV/include/$h" "$SYSROOT_INC/$h"
done
export LIBRARY_PATH="$ENV/lib"
bazel --output_user_root="$OUTPUT_USER_ROOT" \
  build -c opt --keep_going \
  --repo_env=CC="$CC" --repo_env=CXX="$CXX" \
  --action_env=LIBRARY_PATH="$LIBRARY_PATH" \
  --cxxopt=-O3 --cxxopt=-march=native --cxxopt=-DNDEBUG \
  --linkopt=-Wl,-rpath,"$ENV/lib" --linkopt=-Wl,-O2 \
  //apps:cottontail-jsonl-server
