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

# relative replace paths: target/../<mod> holds each path dep wherever target/
# lands. -i.bak + rm works with BSD and GNU sed.
#
# The module name comes from the LEFT side, not from a list of known
# directories. An earlier version matched `(gopb|web)` on the right and so
# silently skipped `pb` when TASK-80 added it, which got as far as a Fly build
# failing on `replacement directory /var/folders/.../pb does not exist`.
# Enumerating the modules here means every new one is a deploy-time surprise;
# deriving it means there is nothing to keep in sync. (Matching on the right
# would also be a trap: `gopb` ends with `pb`, so a careless alternation
# rewrites the tail of the wrong path.)
sed -i.bak -E 's|^replace (github.com/escherize/lll/([a-z]+)) => /.*$|replace \1 => ../\2|' target/go.mod
rm -f target/go.mod.bak

# Nothing absolute may survive: a leftover path is a macOS path inside a linux
# container, and the failure lands minutes later in a Docker layer rather than
# here. Fail at the source instead.
if grep -qE '^replace .* => /' target/go.mod; then
  echo "emit-relative: an absolute replace path survived the rewrite:" >&2
  grep -nE '^replace .* => /' target/go.mod >&2
  exit 1
fi
grep -n "replace" target/go.mod
