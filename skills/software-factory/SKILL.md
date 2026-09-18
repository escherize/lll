---
name: software-factory
description: Start here. The map of how work moves through this repo end to end - pick an issue, isolate, build, verify, merge, record - and which skill owns each stage. Use when you are starting work and do not know which skill applies, when you have finished one stage and need the next, when onboarding to this repo, or when asked "how do I work on this" / "what skill do I use". Triggers on "where do I start", "what next", "which skill", "how does this repo work", "software factory", "the loop", "onboard".
---

# How work moves through this repo

Six stages. Each has a skill that owns it. This page is the map: it says what
each stage is for, when you are in it, and what you hand to the next one.

**Open the stage skill when you get there.** This page deliberately does not
repeat their contents. A map that reproduces the territory gets followed
instead of the territory, and then it rots while the territory moves.

```
  1 intake      backlog-loop     which issue may I take?
  2 isolate     parallel-work    where do I work without colliding?
  3 build       (this codebase)  lisette-interop, datastar-fragments, pocketbase
  4 verify      the gate         mise run gate, and the path the issue describes
  5 merge       merge-gate       land it, confirm it reached the artifact
  6 record      lll              the claim, the evidence, the decision
```

Stage 6 is not last. It runs through all of them.

## 1. Intake - what may I take?

[backlog-loop](../backlog-loop/SKILL.md)

Most issues on a mature board are NOT safely automatable, and the failure that
costs a night is not getting stuck. It is confidently finishing the wrong thing
and closing the issue.

That skill is a filter of five questions. Spend your judgement there, then be
mechanical about the rest.

You are in this stage when you have no issue yet, or when the one you picked
turns out to contain a decision that is not yours.

Hands to stage 2: one issue, claimed.

## 2. Isolate - where do I work?

[parallel-work](../parallel-work/SKILL.md)

Two agents in one checkout is not a merge problem, it is a corruption problem.
Take a worktree before the first edit.

The part people miss is what a worktree does NOT isolate: the stash stack, the
refs, and the remote are shared. Never `git stash` here.

Hands to stage 3: a worktree, a branch cut from the commit you meant, and a
claim on the board that is the actual lock.

## 3. Build - the codebase itself

Three skills, loaded only when the work touches their area. Do not read them
speculatively; they are reference, not process.

- [lisette-interop](../lisette-interop/SKILL.md) - Lisette and Go crossing:
  text offsets, partial I/O, package-level state (there is none; the compiler
  rejects it), embedded resources.
- [datastar-fragments](../datastar-fragments/SKILL.md) - the live board: SSE
  routing, fragment ownership, drafts a broadcast must not clear.
- [pocketbase](../pocketbase/SKILL.md) - anything under `pb/` or `gopb/`:
  migrations, collection rules (empty string means PUBLIC), realtime, auth.

One issue per change. Found a second problem? File it and carry on.

## 4. Verify - is it actually true?

No skill of its own, because the rule is one sentence:

```sh
mise run gate     # build + unit tests + full e2e
```

**`mise run gate` is necessary and not sufficient.** It says you broke nothing.
It does not say you fixed anything. Reproduce the failure the issue describes,
fix it, then reproduce the fix under the issue's conditions rather than the
gate's.

Two rules that have each cost this repo real time:

- **Read the exit code you actually care about.** A pipeline's status is its
  LAST command, so `mise run gate | tail` reports `tail`. Append
  `echo "GATE_EXIT=$?"` and grep the log for it.
- **The gate cannot see everything.** seed, scratch and the release workflow run
  outside it. Ask what your change touches and whether the gate looks there.

Hands to stage 5: a green gate, and evidence from the path a user takes.

## 5. Merge - land it

[merge-gate](../merge-gate/SKILL.md)

The stage that decides whether this is a factory or a pull request generator,
and the one nobody writes down. Published numbers put fully autonomous PRs at a
**55.1% merge rate** against **86.2%** for PRs that took a human commit.

That skill carries the merge mechanics that bite, the exit codes that lie,
release ordering, and why a green check is evidence about CI's vantage point
rather than about your change.

Hands to stage 6: the change on main, confirmed in the artifact people install.

## 6. Record - the part that survives

[lll](../lll/SKILL.md)

Runs through every stage, not after them. Claim before code. Comment with the
evidence you ran. Write the decision when you make it, not when you ship it,
because a decision recorded afterwards remembers what you did and forgets what
you rejected.

**File friction the moment you hit it.** Every agent hits the same walls, and
the ones that go unrecorded get hit again at full cost by the next one.

## The one number worth keeping

Of the issues you took, what share landed without a human having to intervene?
That ratio is the field's one durable measure of a setup like this, and it
cannot be answered here today without rereading a transcript. If you work a
stack, count it and say so on the last issue.

## When the map is wrong

If a stage skill contradicts this page, the stage skill wins and this page is
stale - say so on the board rather than guessing. If two stage skills
contradict each other, that is a bug in the factory and worth an issue of its
own; it happened once already, between closing "when verified" and closing
"when it is on main". The second rule won, because a board that says done while
main does not have the change is worse than a board that says nothing.
