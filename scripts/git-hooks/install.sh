#!/usr/bin/env bash
# Install this repo's git hooks by pointing core.hooksPath at scripts/git-hooks.
#
# Git hooks are NOT cloned, so every clone must run this once:
#     bash scripts/git-hooks/install.sh
#
# Using core.hooksPath (rather than copying into .git/hooks) means the hooks stay
# version-controlled — editing scripts/git-hooks/pre-commit takes effect for
# everyone who has run this, with no re-install.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

chmod +x scripts/git-hooks/pre-commit
git config core.hooksPath scripts/git-hooks

echo "installed: core.hooksPath = $(git config core.hooksPath)"
echo "hooks active:"
for h in scripts/git-hooks/*; do
  case "$(basename "$h")" in
    install.sh|README.md) ;;
    *) echo "  - $(basename "$h")" ;;
  esac
done
echo
echo "Uninstall with: git config --unset core.hooksPath"
