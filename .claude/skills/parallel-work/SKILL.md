---
name: parallel-work
description: Work on lll alongside other agents without colliding - take a worktree, branch from the right commit, let the board's claim be the lock, and get the work out as a pushed branch or a PR that records itself on the issue. Covers isolation, the shared git state that is NOT isolated, running servers and gates in parallel, and what never to do to a sibling's session. Use whenever more than one agent may be working in this repo, before the first edit of any task, and when asked to "work in a worktree", "run agents in parallel", "fan out", or "open a PR". Triggers on "worktree", "parallel", "multiple agents", "fan out", "branch", "open a PR", "isolate".
---

# Working alongside other agents

> One stage of the loop in [software-factory](../software-factory/SKILL.md), which maps all six
> and says what hands to what.

Two agents in one checkout is not a merge problem, it is a corruption problem:
they overwrite each other's edits, run servers on each other's ports, and kill
each other's processes. Isolate first, then the only thing left to coordinate is
who owns which issue - and the board already answers that.

## Isolate before the first edit

Take a worktree. Not a branch in the shared checkout, and not a second clone.

```sh
# The harness's EnterWorktree, or by hand:
git worktree add .claude/worktrees/<name> -b <branch> origin/main
mise trust .claude/worktrees/<name>/mise.toml
```

Trust the new worktree's config before running any mise task. Mise trusts by
path, so trusting the main checkout does not cover a new worktree. Without
this step it reports `error parsing config file` and refuses to start the
gate; that is a trust failure before verification runs (LLL-149).

A worktree is cheaper than a clone - it shares the object store - and that
sharing is exactly what the rest of this file is about.

**Branch from the commit you mean.** A worktree helper may branch from
`origin/main`, which can be far behind the local `main` you were just reading.
That has produced a worktree missing 127 commits, including the schema the task
depended on. Check before you start:

```sh
git rev-list --left-right --count main...origin/main   # left = local-only
```

## What a worktree does NOT isolate

- **The stash stack is shared.** Every worktree and every session pops the same
  stack. Never `git stash`. To set work aside, make a WIP commit on your own
  branch. If you truly must stash, `git stash push -u -m "<unique-tag>"`, record
  the SHA from `git stash list --format='%H %gs'`, and `git stash apply <sha>` -
  never `pop`.
- **Refs are shared**, so two worktrees cannot check out the same branch, and
  one agent's force-push rewrites what another is building on. Do not force-push.
- **The remote is shared.** Push your branch. Never push `main`, never merge
  into it. Integration is the owner's, and a merge you did not coordinate is the
  one action nobody can see coming.

## The claim is the lock

Git does not stop two agents working the same issue; the board does.

```sh
lll issue claim KEY-123      # atomic, server-side, exits non-zero if taken
```

That refusal is the coordination mechanism - let it stop you and pick something
else. Claim BEFORE writing code, not before pushing, or two agents discover the
collision after both have done the work. Release what you abandon
(`lll issue release KEY-123`) so it returns to the pool rather than looking busy.

**The claim excludes members, not agents.** A second claim by the member that
already holds the issue succeeds ("already yours"), from any directory or
session. Agents that share one token are one member, so claim gives them no
exclusion at all: a fleet run that followed this section on a shared token
found it with a probe card. Until LLL-525 lands, give each agent its own
member, or take an external lock before claiming (that fleet used a local
`mkdir` lock with stale takeover gated on the server state and the lock's age).

One issue per branch, one issue per commit. A commit spanning three issues
cannot be reverted when one of them was wrong.

## Servers and ports

Several agents each want a running board. They must not share one.

```sh
mise run scratch        # free ports, temp --pb-dir, fresh home - parallel-safe
mise run seed           # the same, plus demo fixtures to look at
```

`scratch` picks ports by BINDING them, because a liveness probe cannot tell a
free port from a stranger's server. `mise run dev` is the opposite: it hardcodes
port 8100 and `pb/pb_data`, so two of them collide and one is the shared local
board. Use `dev` only when you mean that one.

**Never `pkill -f "bin/lll up"`.** Every worktree's binary has the same path, so
that pattern kills every sibling agent's server. Kill only PIDs you started, and
remove only the temp directory your own run printed.

Gates are parallel-safe: the e2e suite binds free ports, uses its own temp data
directory, and since LLL-369 runs from outside the checkout, so a gate no longer
mutates the tree another agent is reading.

## Keep formatting inside the issue

`lis format` without a path formats the whole project. On lis 0.12.0 this
rewrote 111 files during a scoped auth change (LLL-461). Pass each intended
source file explicitly, then inspect the diff before committing:

```sh
lis format src/commands/issue.lis
lis format src/commands/issue.lis --check
git diff --stat
git diff --check
```

A directory path formats every source file beneath it. Even a single-file
format can change unrelated existing lines in that file; review those too.
For a new helper in a large existing file, format a temporary `.lis` file
containing the helper and apply its formatted text to the intended source.
Keep repository-wide formatting in its own change rather than expanding the
current issue. Never restore another session's edits to shrink a diff.

## Getting the work out

Push the branch. A worktree can be deleted with the session, and unpushed work
dies with it.

```sh
lll issue pr            # gh pr create, and records gh#N back on the issue
```

That last part is the point (LLL-169): the PR and the issue find each other
without anyone remembering to paste a link. It records the reference only after
gh confirms the PR exists, so a failed or ambiguous run leaves the issue
unchanged and tells you to retry the reference alone -
`lll issue ref KEY gh#N` - rather than creating a second PR.

**Uncommitted work does not deploy.** The deploy context is an archive of HEAD,
so a context built before committing silently carries the previous version.

## Do not let test agents touch the real board

Agents exercising lll must run against a throwaway board, never the hosted one.
Give them a wrapper with the URL, team and token pinned, and an isolated HOME,
so a forgotten environment variable cannot reach production:

```sh
#!/usr/bin/env bash
export HOME=/tmp/agent-home LLL_URL=http://127.0.0.1:PORT LLL_TEAM=DEMO LLL_TOKEN=...
exec /path/to/lll "$@"
```

Without it they mint members on the real board. That is not hypothetical:
68 of 71 members there are synthetic identities left behind by ephemeral runs
(LLL-374), and members cannot be deleted without the superuser.

The warning is about throwaway runs. A durable member for each long-lived
worker in a fleet is fine, and it is the only way the claim locks between
workers: agents sharing one member token share every claim (see the claim
section of [lll](../lll/SKILL.md)).

## Finishing

Leave the board and the remote in a state someone else can read:

- comment on the issue with what changed and the evidence you ran
- close it, or return it to todo saying what remains - see [backlog-loop](../backlog-loop/SKILL.md)
  for the selection and honesty rules this pairs with
- push the branch; say its name and the commits in your report
- then [merge-gate](../merge-gate/SKILL.md) takes it from the open PR
  onwards; do not close the issue here, it closes when the work is on main
- if you entered a worktree, commit before you finish, because it can be removed
  with the session
