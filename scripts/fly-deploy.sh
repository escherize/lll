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

bash scripts/prepare-deploy-context.sh "$CTX"
fly deploy --remote-only --config "$CTX/fly.toml" "$CTX"
