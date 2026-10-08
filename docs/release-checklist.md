# Release checklist

A release ships the CLI binary. Every merge to main already deploys the
server, so the release proves that the binary people install works against
the live server, and that no half-finished work goes out with it.

`mise run release-check CUT=<sha>` runs steps 2-4 and prints a table with one
row per check. A FAIL row makes it exit non-zero; a WARN row does not. It only
reads production: it never writes to the hosted board or to Fly. This file is
printed at the end of every run. Do the manual steps below in order.

## 1. Declare the cut line

Pick the commit on main that the release ships. Name it out loud (on the
release issue and in chat): "the cut is `<sha>`; anything that merges after it
is the next version". Without a declared cut the loop does not end, because
agents keep opening PRs.

Then run `mise run release-check CUT=<sha>` and fix every FAIL before you go on.

## 2-4. Automated

Main is green and deployed at the cut, no security work is half-landed, and
version skew works in both directions. See the table above.

## 5. Agent DX fleet

Run a small agent-dx fleet: 5 workers over the cases that the release touched.
Use a binary built from the cut. Follow `docs/agent-dx-fleet/how-to-run.md`
for isolation, provisioning and judging.

It passes when the board check confirms every artifact and fewer than 2
workers hit a tool-owned failure. A repeated tool failure gets its own issue
and a fix, then a fresh run.

## 6. Release order

Each constraint below was found by breaking it.

1. Bump the version in `lisette.toml` and the literal in
   `src/buildinfo/version.lis`, and merge the bump. The release workflow
   refuses a tag that disagrees with `lisette.toml`.
2. Write the changelog last: move `[Unreleased]` in `CHANGELOG.md` to the new
   version. PRs keep landing while you write it, so re-read `git log` against
   the entry just before you tag.
3. Tag the cut and push the tag: `git tag v<version> <sha> && git push origin v<version>`.

## 7. Verify the published artifact

A green release workflow is not proof that people can install the release.

1. Download the released binary for your platform outside the checkout and run
   it:
   `cd "$(mktemp -d)" && gh release download v<version> -R escherize/lll --pattern lll-<os>-<arch> && chmod +x lll-* && ./lll-* --version`.
   It must print the new version.
2. Run `brew upgrade lll` on a real machine, then `lll --version`.
3. Smoke-test the installed binary against the hosted board: `lll whoami` and
   `lll issue list --limit 1`.

## 8. Rollback

- CLI: never rewrite or move a published tag. Ship a patch release
  (`v<version+patch>`) through steps 6 and 7.
- Server: redeploy Fly's previous image. If data is damaged, restore from a
  `pb_data` volume snapshot as in `docs/hosted-recovery.md`.
