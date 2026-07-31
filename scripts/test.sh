#!/usr/bin/env bash
# Run the test suite. Two modes:
#
#     bash scripts/test.sh                 # EVERYTHING (do this before you commit)
#     bash scripts/test.sh <target> ...    # just what you name
#
# A target is anything pytest accepts — a directory, a file, a `file::test_name`,
# a `-k` expression, a marker — plus these shorthands:
#
#     contract  shared  systems  dummy-api  aus-agent   (directories under tests/)
#     bm25-tune                                         (the tasks/bm25_tune harness)
#     live                                              (only the live-marked tests)
#
# Examples:
#     bash scripts/test.sh contract
#     bash scripts/test.sh tests/shared/test_fusion.py
#     bash scripts/test.sh tests/systems/test_facet_rag.py::test_run_one_plans_both_facets
#     bash scripts/test.sh -k "rrf or fuse"
#     bash scripts/test.sh live                  # needs credentials; hits real services
#
# WHY run the whole suite rather than the subset you touched: the systems share
# every layer beneath them. `src/utils/` clients, `src/tools/` dispatch, and
# `src/ragrun/` artifact writing are used by all five systems, so a change to one
# of them can only be cleared by the whole suite — and it takes ~6 seconds. Run
# the full suite before committing, and any time you change something under
# `src/utils/`, `src/tools/`, `src/ragrun/`, or `src/systems/`.
#
# The suite is hermetic: no credentials, no network (tests/conftest.py enforces
# both). The one exception is `live`, which you must ask for by name.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Every per-system dep group that a test `importorskip`s. Without these the
# gated tests SKIP and the run is green having proven nothing about the code they
# cover — the exact trap the old `test_mock.py` scripts fell into (they printed
# SKIPPED and exited 0 whenever SEARCH_API_KEY was unset). Keep in sync with
# .github/workflows/tests.yml and scripts/git-hooks/pre-commit.
#
# NOT named GROUPS: that is a bash built-in (the caller's numeric group ids) and
# assigning to it is silently ignored, so `uv run "${DEP_GROUPS[@]}"` would expand to
# a list of gids. Same trap as tasks/ssr_search/scripts/launch_fork_servers.sh:12.
DEP_GROUPS=(--group dev --group o3-deep-research --group aus-agent)

# Shorthands -> real pytest targets.
args=()
mode="selective"
for arg in "$@"; do
  case "$arg" in
    contract)   args+=("tests/contract") ;;
    shared)     args+=("tests/shared") ;;
    systems)    args+=("tests/systems") ;;
    dummy-api)  args+=("tests/dummy_api") ;;
    aus-agent)  args+=("tests/aus_agent_context") ;;
    # tasks/bm25_tune/ is a task, not a src/ package, so its modules are
    # stdlib-only at import time and need no dep group of their own — see
    # tests/bm25_tune/conftest.py. Hence: shorthand only, DEP_GROUPS unchanged.
    bm25-tune)  args+=("tests/bm25_tune") ;;
    live)       args+=(-m live); mode="live" ;;
    *)          args+=("$arg") ;;
  esac
done

if [[ ${#args[@]} -eq 0 ]]; then
  mode="full"
  echo "→ full suite (hermetic: no creds, no network)" >&2
fi

LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT

set +e +o pipefail
uv run "${DEP_GROUPS[@]}" pytest "${args[@]}" 2>&1 | tee "$LOG"
status=${PIPESTATUS[0]}
set -e

# A skip means a dep group did not install, so the gated tests silently did not
# run. The suite is skip-free by design and CI fails on this too, so surface it
# here rather than letting a green-looking run hide it. Not applied to `live`,
# where "no credentials configured" is a legitimate skip.
if [[ $status -eq 0 && "$mode" != "live" ]] \
   && grep -qE '[0-9]+ skipped' "$LOG"; then
  cat >&2 <<'MSG'

✗ a test was SKIPPED, which this suite never does by design.

  It means a dependency group failed to install, so the tests gated on it did
  not actually run. Check the skip reason above; if a new `importorskip` was
  added, add its dep group to the DEP_GROUPS list in this script, to
  .github/workflows/tests.yml, and to scripts/git-hooks/pre-commit.

MSG
  exit 1
fi

if [[ $status -ne 0 ]]; then
  cat >&2 <<'MSG'

✗ tests failed.

  Re-run just the failure with:
      bash scripts/test.sh <path>::<test_name>

MSG
  exit $status
fi

if [[ "$mode" == "selective" ]]; then
  cat >&2 <<'MSG'

Selected tests passed. Before committing — and after ANY change under
src/utils/, src/tools/, src/ragrun/ or src/systems/ — run the whole suite:

    bash scripts/test.sh

(~6s. Those layers are shared by all five systems, so a subset cannot clear them.)
MSG
fi
