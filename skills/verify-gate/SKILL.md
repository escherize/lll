---
name: verify-gate
description: Stage 4 of the software-factory loop - prove a change does what the issue asked, not just that the gate is green. Covers reading the gate's exit code honestly, reproducing the issue's own path in an isolated environment, health-checking that environment before you trust a run, capturing evidence a reviewer can re-run, and cleaning up without deleting the proof. Use after the code compiles and before you open a PR, whenever an issue describes user-visible behavior, and when a gate passes but you have not reproduced the thing the issue reported. Triggers on "verify", "prove it works", "did the fix land", "evidence", "green but", "reproduce the fix".
---

# Verify - is it actually true?

> One stage of the loop in `lll skill get software-factory`, which maps all
> six. This page is the method. Your repo supplies the commands: its gate, its
> throwaway environment, its drivers. Where your repo's instructions (AGENTS.md,
> CONTRIBUTING, a repo skill) name them, use those.

**The gate is necessary and not sufficient.** Your project's gate is the one
command that must pass before a change lands: build, tests, whatever CI
enforces. It says you broke nothing. It does not say you fixed anything. This
page is the other half: reproduce the issue's own path, under the issue's
conditions, and leave evidence a reviewer can re-run.

```
  Gate      nothing else broke             your project's gate, exit code read honestly
  Before    the failure, reproduced        the issue's path, on the unfixed code
  Launch    an isolated environment        free ports, a temp data dir, a fresh config
  Doctor    is it worth driving?           before the first drive, and after any surprise
  Drive     the real user path             the entry point the issue names
  Evidence  what you ran and what it said  a per-issue directory the build ignores
  Cleanup   stop what you started          by PID, and the evidence survives
```

## Gate - read the exit code you actually care about

A pipeline's status is its LAST command, so `GATE | tail` reports `tail`.
Capture to a log, append the status on its own line, then grep for it:

```sh
GATE > gate.log 2>&1; echo "GATE_EXIT=$?" >> gate.log
grep GATE_EXIT gate.log
```

**The gate cannot see everything.** Demo-seeding scripts, scratch
environments and the release workflow often run outside it. Ask what your
change touches and whether the gate looks there. If it does not, that path is
yours to drive.

## Before - reproduce the failure first

Reproduce what the issue reports on the code as it was, the same way you will
check the fix. A fix verified against a failure you never saw is a guess: the
test may pass because it never exercised the broken path. Keep the "before"
output; it is half of the evidence.

## Launch - an isolated environment

Run the thing the issue describes against an instance nobody else is using:
ports chosen by binding them (a probe cannot tell a free port from a stranger's
server), a temporary data directory, and a config and home directory that are
not yours. A shared dev instance is the wrong place to verify while another
agent might be using it, and your real config is the wrong place to write test
state.

If your repo has a command that does this, use it. If it does not, that is
worth an issue of its own: every agent verifying in parallel will otherwise
hand-roll it and collide.

## Doctor - is it worth driving?

**Check the instance before the first drive, and again after anything
surprising.** Is the binary the one you just built? Does the port answer, and
is it owned by the process you started? Does the credential authenticate?
A run driven against a wedged or stale instance produces evidence about the
wrong thing, and that is worse than no evidence.

The failure a health check cannot see is a wedged UI on a healthy process: the
process is up, the port answers, and the page is stuck in a state no assertion
expects. When a drive fails and the health check is green, relaunch rather than
retrying into the same state.

## Drive - the real user path

Drive the entry point the issue names, not whichever one is convenient. A
write through an internal setter that produces the right row does not prove the
interface a user touches renders it. If the change reaches users through two
entry points, drive both.

Prefer a driver your repo already has. When none covers the path, drive it by
hand and say so in the evidence, or add a driver if the path is one the repo
will verify again. A new driver is its own change with its own issue; do not
smuggle one into an unrelated fix.

Drive stable handles (ids, names, form selectors), never coordinates or tab
order. Make a missing tool fail the run: a suite that silently skips the only
section covering your change still exits 0.

## Evidence - what a proof needs

Write it under a per-issue directory inside your build output (already ignored
by version control, and per-issue so two agents do not overwrite each other).

- **The real user path, not an internal setter.**
- **The action and the resulting state**, not just the final screen.
- **The side effect alongside what is visible**: the stored row, the event
  sent, the file written.
- **The command and its exit code**, captured so a reviewer re-runs it rather
  than trusting your word.
- **Before and after**, from the same command.

Then record it on the issue (`lll skill get lll`): what you ran, the exit code,
and where the full output is.

## Cleanup - stop only what you started

Stop processes by the PID you started, never by a name pattern. A pattern
matches every sibling agent's identical binary path and kills their servers.

**Cleanup never deletes the evidence.** After teardown, confirm the evidence is
still at its path before you claim the proof exists. A teardown that removes
the proof fails this stage even when the run passed.

Clean up after failed attempts too. A stuck drive that leaves a server and a
temp directory behind costs the next agent a confusing port collision.

## What this skill is not

It does not decide whether the change is worth making, and it does not merge.
A green gate plus captured evidence hands to `lll skill get merge-gate`.

If a drive proves the issue's path still fails, the change is not done. Say so
on the issue with the evidence, and do not close it.
