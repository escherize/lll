#!/usr/bin/env bash
# Workaround for a lis 0.12.0 bindgen bug: the generated typedef for
# github.com/dlclark/regexp2 (a chroma dep, reached via goldmark-highlighting)
# gives `Capture` write permission — `embed mut Capture` and
# `mut Slice<mut Capture>` — but Capture has hidden fields and cannot carry
# it, so `lis check`, `lis build`, `lis test` and `lis emit` all fail inside
# generated code (infer.mut_without_effect).
#
# Fix: strip the two bad `mut`s from the cached typedef. One patch pass is
# not enough on a cold cache: a FAILED `lis check` does not warm-stamp the
# typedef cache, so the next lis command regenerates the broken file over the
# patch. Loop check -> patch until check passes; once it does, the cache is
# warm and later lis commands leave it alone. Every lis entry point in this
# repo (mise build/test, e2e.sh, fly-deploy.sh) runs this script first.
# Delete the script and its call sites when upstream bindgen is fixed.
set -euo pipefail
cd "$(dirname "$0")/.."
shopt -s nullglob

patch_typedefs() {
  local f
  for f in target/.lisette/typedefs/lis@v*/*/github.com/dlclark/regexp2@*/regexp2.d.lis; do
    # -i.bak + rm, not -i '': works with both BSD and GNU sed.
    sed -i.bak \
      -e 's/embed mut Capture,/embed Capture,/' \
      -e 's/mut Slice<mut Capture>/mut Slice<Capture>/' \
      "$f"
    rm -f "$f.bak"
  done
}

for _attempt in 1 2 3; do
  # A cold-cache check also generates the typedefs it is about to trip over.
  if lis check >/dev/null 2>&1; then exit 0; fi
  patch_typedefs
done
# Still failing after three rounds: not (only) the regexp2 bug. The caller's
# own lis command reports the real errors; the patch above is idempotent.
exit 0
