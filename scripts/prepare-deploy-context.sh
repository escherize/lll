#!/usr/bin/env bash
# Prepare a clean HEAD plus freshly emitted Go for both CI and local deploys.
# The caller owns the empty output directory and its lifetime.
set -euo pipefail
if [ "$#" != 1 ] || [ ! -d "$1" ]; then
  echo "usage: bash scripts/prepare-deploy-context.sh EMPTY_DIRECTORY" >&2
  exit 2
fi
context=$(cd "$1" && pwd)
cd "$(dirname "$0")/.."
if [ -n "$(ls -A "$context")" ]; then
  echo "deploy context must be empty: $context" >&2
  exit 2
fi
command -v lis >/dev/null || { echo "lis not found" >&2; exit 1; }
git archive HEAD | tar -x -C "$context"
(cd "$context" && bash scripts/emit-relative.sh)
# Only the freshly emitted context may carry target/ into Docker.
sed '/^target\/$/d' "$context/.dockerignore" > "$context/.dockerignore.new"
mv "$context/.dockerignore.new" "$context/.dockerignore"
