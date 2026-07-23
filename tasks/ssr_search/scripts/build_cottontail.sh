#!/usr/bin/env bash
# Build the Cottontail SSR binaries we need, using the task's mamba toolchain
# (gcc 13, C++20) and bazelisk. Production-optimized (-c opt -O3 -march=native).
#
# Bazel's C++ auto-config picks up CC/CXX via --repo_env so it uses the conda
# gcc 13 (system g++ 8.5 cannot compile C++20). Bazel's output tree and
# bazelisk's download cache are redirected onto scratch (home dirs are small).
set -euo pipefail

ROOT=/scratch/fast/kun/projects/trec-rag-26
ENV=$ROOT/tasks/ssr_search/env
CT=$ROOT/tmp/Cottontail                       # upstream reference checkout

export PATH="$ENV/bin:$PATH"
export CC="$ENV/bin/x86_64-conda-linux-gnu-gcc"
export CXX="$ENV/bin/x86_64-conda-linux-gnu-g++"
export BAZELISK_HOME="$ROOT/tasks/ssr_search/.bazelisk"   # bazel binary cache
OUTPUT_USER_ROOT="$ROOT/tasks/ssr_search/.bazel"          # build output tree

cd "$CT"
# NB: ssr-client / fluffy are interactive GNU-readline shells (need
# <readline/history.h>); we don't need them (ssr-client.py + our own engine
# cover it), so they're excluded to avoid a readline sysroot dependency.
# zlib lives in the mamba env ($ENV/include), but the conda gcc only searches
# its sysroot by default and Bazel rejects absolute `-I` copts as non-hermetic.
# Fix: symlink zlib's headers into the compiler's sysroot (a builtin search dir),
# so <zlib.h> resolves as a builtin header — Bazel is happy, no CPATH needed.
# Linking still needs -lz: feed $ENV/lib via LIBRARY_PATH (link paths are not
# hermeticity-checked). Bake an rpath so binaries find conda libstdc++ (gcc-13)
# + libz at runtime with no LD_LIBRARY_PATH.
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
  //apps:jsonl //apps:ssr-server //apps:rank \
  //apps:fiver2hazel //apps:merge-hazels //apps:finish-merging
