#!/usr/bin/env bash
set -euo pipefail

# Resolve the repository root relative to this script so the build works from
# any checkout location (developer machines, CI, fresh clones) instead of a
# hard-coded host path.
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT/web/study-ui"

if [ ! -d node_modules ]; then
  npm ci
fi

npm run build

cd "$ROOT"

rm -rf tools/study_web/static/*
mkdir -p tools/study_web/static
cp -a web/study-ui/dist/. tools/study_web/static/
touch tools/study_web/static/.gitkeep

echo "Built study web static assets into tools/study_web/static"
