---
name: merge-gate
description: Land work that is already in a pull request - merge it, confirm it reached the artifact people actually install, close the issue honestly, and know when to stop merging. Covers the merge mechanics that bite, the exit codes that lie, release ordering, and why a green check is evidence about CI's vantage point rather than about your change. Use after a PR is open and green, when asked to "merge it", "merge when CI passes", "ship it", "cut a release", or "close it out". Triggers on "merge", "land it", "ship", "release", "tag", "deploy", "close the issue", "green".
---

# The half after the pull request

> One stage of the loop in [software-factory](../software-factory/SKILL.md), which maps all six
> and says what hands to what.

Every other skill here ends at "open the PR". That is the wrong place to stop.

The stage that decides whether a pile of agents is a software factory or a pull
request generator is the merge gate, and it is the stage nobody writes down.
Published numbers from teams running this at scale put fully autonomous PRs at
a **55.1% merge rate** against **86.2%** for PRs that took a human commit
(dotnet/runtime, via Firecrawl's factory writeup, 2026). Opening PRs is not the
achievement. Landing them is.

This skill is the procedure. It is short on theory because every line of it was
paid for.

## Before you merge

**Read the check rollup, not the vibe.** A PR is mergeable when CI is green AND
`mergeable` says so:

```sh
gh pr view N --json statusCheckRollup,mergeable,mergeStateStatus
```

`mergeable` comes back `UNKNOWN` on the first read while GitHub computes the
merge commit. That is not a conflict. Read it again before concluding anything.

**A red check is not automatically your fault, and not automatically a flake.**
Classify it: see the `ci-watch` skill if it is installed (it is a global
skill, not one of this repo's, so there is no link to it here), or the
short version - find which STEP failed. A failure asserting something your diff
could not have caused is a strong infrastructure signal. A failure naming your
own change is not. Never rerun a real failure hoping it passes.

Two failures from one session, to calibrate:

- A PR changing one expression in a JSON printer failed with `label 'docs' was
  not created`. The diff could not touch labels. It was a transient read whose
  assertion piped a command into grep without checking the command succeeded.
- A PR failed on a claim-refusal assertion that checked for the literal string
  `bcm`, the author's username. CI runs as `runner`. The feature worked; the
  test was machine-specific.

The first is infrastructure. The second is yours. They look identical in the
summary line.

## Updating PR metadata

Older GitHub CLI versions can fail `gh pr edit --body-file` with the
classic-project GraphQL deprecation at `repository.pullRequest.projectCards`
(reproduced with 2.65.0; 2.95.0 succeeds). If you hit that error, use the REST
fallback already exercised here. Do not apply it to an unrelated permission or
network failure.

Keep the exact Markdown in a file and encode it as JSON; shell interpolation
can change newlines or execute characters from the body. For an existing PR:

```sh
pr_repo=OWNER/REPO
pr_number=123
pr_body=/tmp/pr-body.md
pr_payload=$(mktemp /tmp/pr-metadata.XXXXXX)
python3 - "$pr_body" "$pr_payload" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[2]).write_text(json.dumps({"body": Path(sys.argv[1]).read_text()}))
PY
gh api --method PATCH "repos/$pr_repo/pulls/$pr_number" \
  --input "$pr_payload" --jq .html_url
gh pr view "$pr_number" --repo "$pr_repo" --json title,body
rm "$pr_payload"
```

Confirm the PATCH succeeded and the returned body matches the file before
recording the edit as complete. A title change can use the same JSON payload's
`title` field. This updates metadata; it does not replace the merge checks.

## Merging

```sh
gh pr merge N --merge
```

**Do not pass `--delete-branch` from a worktree.** `gh` tries to check out the
default branch locally to clean up, and fails when another worktree holds it:

```
failed to run git: fatal: 'main' is already used by worktree at '/path/to/repo'
```

The merge **already happened server-side**. Reading that error as a merge
failure and retrying is how a PR gets merged twice or abandoned half-landed.
Confirm, then delete the branch separately:

```sh
gh pr view N --json state,mergeCommit     # confirm first
git push origin --delete <branch>
```

**Merge oldest first** when several are open, and re-read `mergeable` between
merges. Each merge moves the target, and a PR that was CLEAN five minutes ago
may now conflict.

## The exit code you are reading is probably not the one you want

This is the single most repeated mistake in this repository's history, and it
has produced confidently wrong "it passed" claims more than once.

**A pipeline's status is its LAST command.**

```sh
mise run gate | tail -5 ; echo "exit=$?"     # WRONG: that is tail's status
```

Append the marker inside the same command and grep for it:

```sh
mise run gate > gate.log 2>&1; echo "GATE_EXIT=$?" >> gate.log
grep GATE_EXIT gate.log
```

**`gh run watch --exit-status` exits non-zero when it attaches to a run that has
already finished.** That is not a failed run. Always confirm the conclusion
directly:

```sh
gh run view <id> --json status,conclusion
```

**A task runner refusing to start also exits non-zero.** `mise ERROR ... are not
trusted` and `no task e2e-web found` both look like test failures from a
distance. Read the log, not the number.

## After it lands, before you believe it

**A green check is evidence about CI's vantage point. It is not evidence about
the thing people install.**

The canonical failure: `v0.3.0` was tagged, built, published with three
binaries, and pushed to a Homebrew tap, with every check green. The release
workflow asserts `lll --version` equals the tag - and runs it **inside the tag
checkout**, the one directory on earth where the old `git describe` call gave
the right answer. Downloaded from the release, the binary reported `lll 0.2.0`.
In an unrelated repository tagged `v9.9.9`, it reported `lll 9.9.9`.

So: **download the artifact and run it.**

```sh
curl -sL -o /tmp/tool https://github.com/OWNER/REPO/releases/download/vX/asset
chmod +x /tmp/tool && (cd / && /tmp/tool --version)
```

Run it from a directory that is NOT the checkout. Half the class of bugs this
catches only appear outside it.

The same rule scales down. After merging to main, watch main's own gate, because
that is usually what gates the deploy, and it is the first run that sees your
change combined with everyone else's.

## Release ordering, when there is a release

Order is load-bearing and each constraint below was discovered by violating it:

1. **The version bump lands before the tag.** If the release workflow asserts
   that the tag matches a manifest (`lisette.toml`, `package.json`, `Cargo.toml`),
   a tag pushed against the old version fails immediately.
2. **The changelog is written last.** PRs keep landing while you write it. Four
   landed between the entry and the tag in one session; the entry had to be
   amended before the tag to stay true.
3. **Declare a cut line and say so out loud.** Without one the loop does not
   terminate, because agents keep opening PRs. Anything merging after the line
   belongs to the next version.
4. **Anything advertising the release lands after the tag.** A landing page
   whose download links point at a release that does not exist yet is worse than
   a stale one: every install link 404s.
5. **Never rewrite a published tag to fix a bad release.** Ship the next patch.
   The tag, the assets, and any package formula are already out; re-pointing
   them breaks whoever fetched first.

## Closing honestly

**Close an issue when the work is on main, not when the PR opens.** A board that
says done while main does not have the change is worse than a board that says
nothing.

While the PR is open the issue is genuinely in progress. When it lands:

```sh
lll issue close KEY-123
lll issue release KEY-123      # or the board still reads as busy
```

Comment with the evidence you actually ran before closing - the before and after,
the command, the number. "Fixed" with no evidence is the thing this whole
workflow exists to prevent.

**Generated artifacts move with their source.** A migration that adds a field
and a generated schema reference that does not document it will be caught by
whatever check exists, one hour or one release later. Regenerate in the same PR.

## When to stop merging

- **The cut line you declared.** Honour it or it was not a line.
- **A real failure, twice.** Two reruns of the same step is not a flake wearing
  a disguise; it is a standing problem. Stop and say which step.
- **Main is red.** Never merge onto a broken main to "fix it forward" unless the
  merge IS the fix and you can say why.
- **The next step is irreversible and nobody asked for it.** Tagging publishes
  binaries and writes to public package indexes. Deleting, force-pushing and
  merging to main directly are never yours to improvise.

Stopping is a result. Report which PRs landed, which did not, and why.

## The number worth keeping

Of the PRs an agent opened, what share landed **without a human commit**? That
single ratio is the field's one durable measure of a factory, and it cannot be
answered here today without rereading a transcript. If you find yourself
merging a stack, count it and write it on the issue.

## What this skill is not

It is not an orchestration layer. Anthropic's 2026 agentic coding trends report
puts it plainly: multi-agent "doesn't make sense for 95% of agent-assisted
development tasks". The gap this fills is a checklist, not another tier of
agents. If you are tempted to add one, re-read the 55.1% number first: the
constraint is the gate, not the throughput.
