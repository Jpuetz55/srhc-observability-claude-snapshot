#!/usr/bin/env bash
# Install the repo's git hooks into .git/hooks/.
# Run once per clone:
#   bash scripts/install_githooks.sh
#
# Alternatively, set core.hooksPath to point at scripts/githooks/ directly:
#   git config core.hooksPath scripts/githooks
# That picks up new hooks without re-running this installer, but doesn't work
# across all git versions / submodule setups, so this script symlinks
# explicitly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOKS_SRC="$REPO_ROOT/scripts/githooks"
HOOKS_DST="$REPO_ROOT/.git/hooks"

if [[ ! -d "$HOOKS_DST" ]]; then
  echo "ERROR: $HOOKS_DST not found (not a git working tree?)" >&2
  exit 1
fi

for hook in "$HOOKS_SRC"/*; do
  [[ -f "$hook" ]] || continue
  name="$(basename "$hook")"
  target="$HOOKS_DST/$name"
  rm -f "$target"
  ln -s "$hook" "$target"
  chmod +x "$hook"
  echo "installed $target -> $hook"
done
