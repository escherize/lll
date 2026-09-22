---
name: verify-gate
description: Stage 4 of the factory - prove a change actually works against a running board, not just that the gate is green. Covers launching an isolated instance, health-checking it before you trust a run, driving the real user path with the browser suite, where evidence lives and that it survives cleanup. Use after the code compiles and before you open a PR, whenever an issue describes user-visible behavior, and when a gate passes but you have not reproduced the thing the issue reported. Triggers on "verify", "prove it works", "did the fix land", "drive the board", "evidence", "green but", "reproduce the fix".
---

# Verify - is it actually true?

`mise run gate` says you broke nothing. It does not say you fixed anything.
This page is the other half: reproducing the issue's own path against a
running board and leaving evidence a reviewer can re-run.

```
  Launch    an isolated board             mise run scratch
  Doctor    is it worth driving?          before the first drive, and after any surprise
  Drive     the real user path            scripts/browser_*.js, scripts/e2e_web.sh
  Evidence  what you captured, where      target/verify/<issue-key>/
  Cleanup   kill what you started         only PIDs you started
```

**The drivers already exist.** This skill does not add a test framework. It
says which of the fifteen `scripts/browser_*.js` drivers proves which feature,
and what to do when none of them covers the path your issue describes. The map
is in [features/](features/README.md).

## Launch

```sh
mise run scratch              # free ports, temp --pb-dir, safe in parallel
mise run scratch -- --no-open # flags pass through to lll up
```

It binds both ports rather than probing them, so it is safe while siblings are
running. Fresh database, fresh home, isolated config. Default team SCRAT.
Administrator credentials are `admin@local.dev` / `admin-local-123` and are not
printed. The banner prints the board login URL and the isolated config path,
and the `rm -rf` for the temp directory when you are finished.

`mise run dev` is the OTHER thing. It hardcodes port 8100 and `pb/pb_data`, so
two of them collide. Never drive a verification run against it while another
agent might be using the shared board.

## Doctor

**Run this before the first drive, and again after anything surprising.** It is
read-only and answers one question: is this instance worth driving?

```sh
bash scripts/doctor.sh                      # checks the scratch board it can find
bash scripts/doctor.sh --url http://127.0.0.1:PORT --board-token TOKEN
```

Green means the binary is the one you just built, the port is answering and
owned by us, and the board token authenticates. Red means stop - a run driven
against a wedged or stale instance produces evidence about the wrong thing, and
that is worse than no evidence.

**The failure doctor cannot see is a wedged UI on a healthy process.** The
process is up, the port answers, the token works, and the page is stuck in a
state no assertion expects. When a drive fails and doctor is green, relaunch
rather than retrying into the same state.

## Drive

Prefer a driver that already exists. [features/](features/README.md) maps each
user-facing feature to the script that proves it.

```sh
bash scripts/e2e_web.sh                     # the whole web suite, boots its own PB
bash scripts/e2e_web.sh --require-browser   # fail instead of skipping when playwright-cli is absent
```

`--require-browser` matters more than it looks. Without it the browser sections
skip silently when `playwright-cli` is missing, and a suite that skipped the
only section covering your change still exits 0.

Individual drivers are Playwright page functions under `scripts/browser_*.js`,
run through `scripts/browser_session.py`, which owns the session and redacts
tokens out of failures. Drive stable handles - the `#claim-form`, `.card-claim`
and `[name=title]` selectors the drivers already use - never coordinates or
tab order.

**When no driver covers your path:** drive it by hand through the scratch board
and say so in the evidence, or add a driver if the path is one this repo will
verify again. A new driver is stage 3 work with its own issue; do not smuggle
one into an unrelated change.

## Evidence

Write it to `target/verify/<issue-key>/`. That path is inside the build output,
so it is already ignored by git, and it is per-issue, so two agents verifying
different issues do not overwrite each other.

What a proof needs:

- **The real user path, not an internal setter.** A CLI write that produces the
  right row does not prove the board renders it.
- **The action and the resulting state**, not just the final screen.
- **The side effect alongside what is visible** - the row in PB, the SSE frame,
  the file written.
- **The command and its exit code**, captured so a reviewer re-runs it rather
  than trusting your word.

```sh
mkdir -p target/verify/LLL-123
bash scripts/e2e_web.sh --require-browser > target/verify/LLL-123/e2e.log 2>&1
echo "E2E_EXIT=$?" >> target/verify/LLL-123/e2e.log
grep E2E_EXIT target/verify/LLL-123/e2e.log
```

**Read the exit code you actually care about.** A pipeline's status is its LAST
command, so `bash scripts/e2e_web.sh | tail` reports `tail`. Capture to a log
and append the status on its own line, then grep for it.

## Cleanup

Kill only PIDs you started. **Never `pkill -f "bin/lll up"`** - the pattern
matches every worktree's identical binary path and kills every sibling agent's
server.

```sh
kill "$SCRATCH_PID"           # the one you started, nothing else
rm -rf "$SCRATCH_TMPDIR"      # the path the scratch banner printed
```

**Cleanup never eats the evidence.** `target/verify/<issue-key>/` survives
teardown by design. After cleanup, confirm the files are still at that path
before you claim the proof exists - a teardown that removes the proof fails
this stage even when the run passed.

Clean up after failed attempts too. A stuck drive that leaves a board and a
temp directory behind costs the next agent a confusing port collision.

## What this skill is not

It does not decide whether the change is worth making, and it does not merge.
A green drive plus captured evidence hands to [merge-gate](../merge-gate/SKILL.md).

If a drive proves the issue's path still fails, the change is not done - say so
on the issue with the evidence, and do not close it. Closing "when verified"
lost to closing "when it is on main" once already; a proof that was never run
loses to both.
