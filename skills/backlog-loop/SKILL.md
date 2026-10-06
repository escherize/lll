---
name: backlog-loop
description: Work the lll backlog unattended - pick issues that are genuinely safe to finish without a human, implement and verify them, and close them honestly or hand them back. Covers the selection filter that decides what an agent may take, what counts as verification, when to stop, and the traps that have actually cost runs. Use when running a long autonomous session against the board, when asked to "work the backlog", "find something to do", "do whatever is obvious", or when scheduling a recurring agent to burn down issues. Triggers on "backlog loop", "work the backlog", "autonomous", "unattended", "overnight", "burn down issues", "what can you pick up".
---

# Working the backlog unattended

> One stage of the loop in [software-factory](../software-factory/SKILL.md), which maps all six
> and says what hands to what.

The loop is easy. Picking what to put in it is the whole job.

Most issues on a mature board are NOT safely automatable, and the failure mode
is not "the agent gets stuck" - it is the agent confidently finishing the wrong
thing and closing the issue. A night spent on a task that needed one human
sentence is worse than a night spent idle, because now the board says done.

So: spend your judgement on selection, then be mechanical about the rest.

## The filter: may an agent take this?

Take an issue only if you can answer YES to all five.

**1. Does it name an end state you can measure?**
"The font flashes" became `transferSize: 0` on reload. "205 done issues load
eagerly" is a count you can assert. "Make the board cleaner" is not - it has no
failing state, so it has no passing one either.

**2. Is every acceptance criterion checkable without a person?**
Read them literally. "The dedicated IPv4 is released" is not checkable by you -
releasing it is irreversible and outward-facing. An issue can be 80% automatable
and still have one criterion that ends the run.

**3. Is the work reversible?**
Code and config in a branch: yes. Production data, a released address, a deploy,
anything a person will see before you can undo it: no. Reversibility is what
makes an unattended mistake cheap.

**4. Does it contain an unmade decision?**
This is the one that catches people. An issue saying "either A or B is fine"
contains a decision, and a decision is not yours unless the issue names a
default and says why. Real examples from this board: what 115 issues assigned to
dead run-identities should be reassigned TO; whether a repo link belongs to the
team or the project; whether repeated `--state` should union or refuse. All
well-specified. None automatable.

The exception, and it is worth looking for: **the codebase may have already
decided the same question somewhere else.** An issue offering "clear the
environment in the task, or stub it in the tests" looked like a decision until
`e2e_begin` turned out to unset every `LLL_*` it does not set itself, with a
comment explaining why. That is the house answer to "how does a suite get a
known environment", so following it is not choosing - it is consistency, and it
is the better change because the next reader finds one rule instead of two.

Search for the precedent before concluding a decision is unmade. Cite it in the
commit. If there is no precedent, it is a decision and it is not yours.

**5. Is the blast radius bounded and known?**
"Change the filter parser" touches every noun that filters. "Add a header to
one route" does not. Prefer the second when working alone.

If any answer is NO: leave it, and say on the issue exactly which question
failed and what a human needs to supply. That comment is the deliverable.

### The trap inside the filter

An issue can pass all five and still be wrong, because **the issue text may be
false**. Issues are written by people and agents who did not verify.

Before implementing, reproduce the problem yourself. Measured cases from real
runs: an audit reported 10 duplicate sites and there were 14, split across two
different concerns that must not be merged. A usability report's top two
complaints were both false - the help text it said was missing was present on
eleven lines. A "regression I caused" turned out to predate the change by five
days.

If you cannot reproduce it, the issue is not ready. Say so and move on. Do not
implement a fix for a problem you never saw.

## The loop

```sh
lll issue list --state todo --limit 50      # candidates
lll issue view KEY --raw                    # read it FULLY, including comments
```

Comments carry the reasons an issue is harder than its title. One issue on this
board looks like a two-line normalisation and carries a comment explaining it
became a cross-surface policy change. The title lied; the comment did not.

Then, per issue:

1. **Reproduce.** Prove the problem exists, with output you can paste.
2. **Claim it.** `lll issue claim KEY` then `lll issue update KEY --state in-progress`.
   Claim is atomic and fails if another member got there first - that refusal is
   the point, let it stop you. (Same token = same member: see the claim trap below.)
3. **Implement.** Smallest change that satisfies the criteria. Nothing else.
   Found a second problem? File it, do not fix it.
4. **Verify.** See below. Not "tests pass".
5. **Record.** Comment with the evidence you actually ran, and what you did NOT
   do.
6. **Close** - or return it to todo with what is missing.

Work one issue per commit. A commit that fixes three issues cannot be reverted
when one of them was wrong.

This loop ends at a pushed branch and an open PR.
[merge-gate](../merge-gate/SKILL.md) is the stage after it: landing the change,
confirming it reached the artifact people install, and closing the issue
honestly. Neither half is the whole job.

## Verification

`mise run gate` is necessary and not sufficient. It says you broke nothing. It
does not say you fixed anything.

**Reproduce the failure, fix, then reproduce the fix under the same conditions.**
Not the gate's conditions - the issue's. A test-environment bug is verified by
running the tests WITH the hostile variable exported, not by a clean run:
`LLL_ME=x LLL_TOKEN=y mise run test` went from 2 failed / 304 passed to 306
passed, and only that pair of numbers is evidence. A clean green run would have
proved nothing at all, because a clean run was already green before the fix.

**Verify the claim the issue made, through the path a user takes.** The gate was
green for five days while `mise run seed` was completely broken, because the
gate does not run seed. A green gate is evidence about the gate's coverage as
much as about your change.

- A header change: read the header off a running server.
- A UI change: drive it in a browser and look at the screenshot.
- A performance change: measure the thing, before and after.
- A deletion: prove the symbol had no callers, with the search you ran.

**Read the exit code you actually care about.** `mise run gate > log; echo done`
reports the exit status of `echo`. Append `echo "GATE_EXIT=$?"` immediately
after the gate and grep the log for it. A run reported "exit 0" here while mise
had refused to start at all.

**Re-run a suspicious failure two or three times before concluding you caused
it.** Flaky assertions on this board have parked finished work as broken.

## Closing honestly

Close only what is done. This is the rule the whole loop depends on, because a
board that lies is worse than no board.

- Criteria met and verified → comment with the evidence. CLOSE IT WHEN THE
  WORK IS ON MAIN, not when the PR opens: see
  [merge-gate](../merge-gate/SKILL.md), which owns that stage. A board saying
  done while main lacks the change is worse than a board saying nothing.
- Partly done → back to todo, with a comment naming precisely what remains.
  Do not close "most of it".
- Blocked on a human → back to todo, with the question stated in one sentence.
- Cannot reproduce → say so with what you tried, and close only if the issue was
  about a symptom that demonstrably no longer occurs. Name it as
  "not reproducible", never as "fixed".

Leaving four issues in todo with honest comments is a better night's work than
closing four issues you half-did.

## When to stop

Stop and hand back when:

- The next step is irreversible or outward-facing (deploy, release, delete,
  anything a user sees).
- You have hit the same failure twice and your second theory was also wrong.
  Two wrong theories means you do not understand the problem.
- The change is growing past the issue. Scope growth unattended is how a small
  fix becomes an unreviewable diff.
- You would have to decide something the issue did not decide.

Stopping is a result. Report it as one.

## Traps that have actually cost runs here

- **The gate does not cover everything.** seed, deploy config, and anything
  behind the board token are outside it. Ask what your change touches and
  whether the gate can see it.
- **Suites encode old behaviour twice.** Changing one asserted behaviour broke a
  second assertion further down that depended on the first as a side effect.
  Grep for the old behaviour, not just the old string.
- **Deploy context archives HEAD.** Uncommitted changes do not deploy, and a
  context built before committing silently carries the previous version.
- **Isolate before editing.** Work in a worktree; a second agent in one checkout
  overwrites your edits rather than conflicting with them. Branch from the
  commit you mean, not whatever the worktree defaulted to. Never stash: that
  stack is shared with every other session and worktree.
  [parallel-work](../parallel-work/SKILL.md) owns this stage.
- **The claim is the lock**, not the branch. `lll issue claim` is atomic and
  server-side, and its refusal is how two agents avoid doing the same work
  twice. Claim before writing code, not before pushing. It refuses other
  MEMBERS only: a re-claim by the holder succeeds, so agents sharing one token
  get no exclusion from it. Give each agent its own member, or lock outside lll.

  (Working on lll itself? Its repo carries a `parallel-work` skill with the rest:
  ports, servers, what a worktree does not isolate, and getting the branch out.
  This skill ships inside the binary, so it does not link to it.)
- **Do not point test agents at the hosted board.** Give them a pinned wrapper
  against a throwaway board. Ephemeral identities that name themselves leave
  permanent auth records behind; that is an existing issue on this board, not a
  hypothetical.

## What this does not decide

Whether any of this belongs inside `lll` itself rather than in a skill. The
selection filter is judgement and reads well as prose. The mechanical half -
finding candidates, recording that an issue was considered and rejected, and why
- is board state, and board state belongs in lll. A label like `needs-decision`
applied by the loop would make the filter's output durable and queryable instead
of living in one agent's head. Worth deciding before the loop runs often enough
for its rejections to matter.
