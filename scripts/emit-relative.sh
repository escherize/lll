#!/usr/bin/env bash
# Emit Go into target/ and rewrite the emitted go.mod's absolute replace
# paths (gopb, web) to relative, so a plain `go build` works from any copy
# or mount of target/ — a Docker build context, a cross-compile on a CI
# runner. Needed because lis cannot bindgen on linux (see Dockerfile header):
# linux binaries are built from this darwin emit.
#
# Runs against the checkout at cwd (fly-deploy.sh calls it inside its
# archive context; the release workflow calls it at the checkout root).
set -euo pipefail

bash scripts/lis-typedefs-workaround.sh
lis emit >/dev/null

# relative replace paths: target/../gopb and target/../web hold the path
# deps wherever target/ lands. -i.bak + rm works with BSD and GNU sed.
sed -i.bak -E 's|replace (github.com/escherize/lll/[a-z]+) => .*/(gopb\|web)$|replace \1 => ../\2|' target/go.mod
rm -f target/go.mod.bak
grep -n "replace" target/go.mod
