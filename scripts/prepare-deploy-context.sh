#!/usr/bin/env bash
# Prepare a clean HEAD plus freshly emitted Go for both CI and local deploys.
# The caller owns the empty output directory and its lifetime.
set -Eeuo pipefail
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
context_stage=archive
trap 'context_status=$?; printf "prepare-deploy-context: %s failed (exit %s)\n" "$context_stage" "$context_status" >&2; exit "$context_status"' ERR
context_archive=$(mktemp "${TMPDIR:-/tmp}/lll-deploy-archive.XXXXXX")
trap 'rm -f "$context_archive"' EXIT
# A tar consumer may stop at its end marker before git finishes padding the
# stream. Finish the archive first so that closure cannot SIGPIPE its producer.
git archive --format=tar --output="$context_archive" HEAD
context_stage=extract
tar -x -f "$context_archive" -C "$context"
context_stage=emit
(cd "$context" && bash scripts/emit-relative.sh)
# Only the freshly emitted context may carry target/ into Docker.
context_stage=dockerignore
sed '/^target\/$/d' "$context/.dockerignore" > "$context/.dockerignore.new"
mv "$context/.dockerignore.new" "$context/.dockerignore"
