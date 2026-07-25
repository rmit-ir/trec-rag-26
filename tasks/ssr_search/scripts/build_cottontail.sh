#!/usr/bin/env bash
# Build the UWaterlooIR Cottontail fork's ClimbMix indexer/server binaries with
# the task's mamba toolchain (gcc 13 + bazelisk). The fork ships StemmingTokenizer
# + HashingFeaturizer + a configurable-window jsonl server — the SSR stack we run.
#
# Hermetic-toolchain tricks (mamba gcc isn't on the default include/link paths):
#   - symlink the mamba zlib headers (zlib.h / zconf.h) into the compiler's
#     builtin sysroot include dir so Bazel's actions find them without -I flags;
#   - point LIBRARY_PATH + an -rpath linkopt at $ENV/lib so the binaries resolve
#     the mamba libstdc++/zlib at link and run time;
#   - use a fork-specific Bazel output root (tmp/.bazel-fork) to keep this build
#     independent of any other Cottontail checkout's cache.
set -euo pipefail

ROOT=/scratch/fast/kun/projects/trec-rag-26
ENV=$ROOT/tasks/ssr_search/env
CT=$ROOT/tmp/Cottontail                 # the fork

export PATH="$ENV/bin:$PATH"
export CC="$ENV/bin/x86_64-conda-linux-gnu-gcc"
export CXX="$ENV/bin/x86_64-conda-linux-gnu-g++"
export BAZELISK_HOME="$ROOT/tmp/.bazelisk"
OUTPUT_USER_ROOT="$ROOT/tmp/.bazel-fork"

cd "$CT"
# zlib headers into the compiler sysroot (builtin search dir) + rpath (see the
# hermetic-toolchain notes in this script's header).
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
  //apps:cottontail-jsonl-index //apps:cottontail-jsonl-query \
  //apps:cottontail-jsonl-server

echo "fork binaries at: $CT/bazel-bin/apps/"
ls -la "$CT/bazel-bin/apps/" | grep -E 'cottontail-jsonl|finish-merging|fiver2hazel' || true
