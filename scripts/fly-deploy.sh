#!/usr/bin/env bash
# Deploy to Fly. lis cannot bindgen on linux (see Dockerfile header), so the
# build context is a clean archive of HEAD plus a fresh darwin `lis emit`,
# with the emitted go.mod's absolute replace paths rewritten to relative.
# Uncommitted changes deliberately do not deploy: the archive is HEAD.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v lis >/dev/null || { echo "lis not found" >&2; exit 1; }
command -v fly >/dev/null || { echo "fly not found: brew install flyctl" >&2; exit 1; }

CTX="$(mktemp -d)"
trap 'rm -rf "$CTX"' EXIT

git archive HEAD | tar -x -C "$CTX"

echo "emitting Go into the deploy context..."
(cd "$CTX" && bash scripts/lis-typedefs-workaround.sh && lis emit >/dev/null)

# relative replace paths: the container's module lives at /src/target, the
# path deps at /src/gopb and /src/web.
sed -i '' -E 's|replace (github.com/escherize/lll/[a-z]+) => .*/(gopb\|web)$|replace \1 => ../\2|' "$CTX/target/go.mod"
grep -n "replace" "$CTX/target/go.mod"

# the checkout's .dockerignore excludes target/ (a stale emit must not ride
# along on a hand-run `fly deploy`); this context's emit is fresh by
# construction, so drop that exclusion here.
grep -v '^target/$' .dockerignore > "$CTX/.dockerignore" || true

exec fly deploy --remote-only --config "$CTX/fly.toml" "$CTX"
