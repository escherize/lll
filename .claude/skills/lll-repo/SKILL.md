---
name: lll-repo
description: This checkout's specifics, layered over the generic skills that ship in the lll binary (software-factory, lll, backlog-loop, merge-gate, codebase-skills). Names the team (LLL on the hosted board), the gate (mise run gate), scratch and dev boards, the archived .private sidecar, and the repo-only skills for stages 2-4. Use whenever working in the lll repository itself, alongside any of the shipped skills. Triggers on "this repo", "the gate", "mise run", "scratch board", "team LLL", "archive", ".private".
---

# lll's own repo: the overlay on the shipped skills

The skills in `software-factory`, `lll`, `backlog-loop`, `merge-gate` and
`codebase-skills` ship inside the binary (`lll skill get NAME`), so they say
"your team" and "your project's gate". This page fills those blanks for THIS
repository. It does not ship: `scripts/sync_skills.py` mirrors only the
portable skills into `skills/`, and `skills/skills_test.go` fails if a
shipped body mentions this repo's team, gate or tickets.

Where this page and a shipped skill disagree about this repo, this page wins.

## The team and the board

This repo's work is tracked in team `LLL` on the hosted instance named in
`.lll.toml`. `lll issue list` from the checkout is the real work list. A seeded
demo board (`mise run seed`) is the fixture for exercising the tool; it is a
different url and team. Keep scratch and demo records off the hosted board.

The sidecar notes repo that used to hold the backlog, findings and decisions
was imported into the board and archived; its url is in `.private-remote`,
read-only. If a local `.private` is retained, run `mise run archive-protect`
once to remove write permissions; the gate verifies protection. This changes
permissions, not historical contents. See `docs/archive-history.md`. Fresh
checkouts need not clone an archive. Do not write new tasks there.

Projects name outcomes, not parallel waves. The policy and the historical
backfill are `lll doc view projects-name-outcomes-not-waves` and
`lll doc view historical-wave-project-audit`. Agents sharing one member token
share its claims: finding `shared-member-claims-do-not-isolate-sessions`.

## The gate

```sh
mise run gate > gate.log 2>&1; echo "GATE_EXIT=$?" >> gate.log   # build + unit tests + full e2e
grep GATE_EXIT gate.log
```

`mise run test` is the unit half. The gate does not run `mise run seed`,
`mise run scratch` or the release workflow; that is how seed was broken for
five days under a green gate.

## Stages 2 to 4 here

The shipped `software-factory` map leaves these to the repo. In this one:

- **2 isolate**: `parallel-work` - worktrees, the shared git state a worktree
  does not isolate, ports and servers in parallel, getting the branch out.
- **3 build**: load only when the work touches the area.
  - `lisette-interop` - Lisette and Go crossing: text offsets, partial I/O,
    package-level state (there is none; the compiler rejects it), embedded
    resources.
  - `datastar-fragments` - the live board: SSE routing, fragment ownership,
    drafts a broadcast must not clear.
  - `pocketbase` - anything under `pb/` or `gopb/`: migrations, collection
    rules (empty string means PUBLIC), realtime, auth.
- **4 verify**: `verify-gate` - an isolated board, `mise run doctor` before you
  trust it, the browser drivers, where evidence lives.

## Running a board by hand

Do not hand-roll isolation when others may be running a server too:

```sh
mise run scratch              # free ports, a temp --pb-dir, safe in parallel
mise run scratch -- --no-open # extra flags pass straight through to lll up
```

It picks both ports by BINDING them (a liveness probe cannot tell a free port
from a stranger's server), and runs on loopback with a fresh database, home
and working directory. Inherited `LLL_*` settings are cleared except an
explicit `LLL_TEAM`; the default team is SCRAT. The banner prints the board
login URL, the isolated config path and administrator credentials once:
`admin@local.invalid` / a generated password. A hosted login token does not
authenticate against the scratch database. The temporary directory is kept
after shutdown; the banner shows the `rm -rf` to run when finished.

`mise run dev` is the OTHER thing: it builds, then hardcodes port 8100 and
`pb/pb_data`, so it is the shared local board and two of them collide. Board at
:8100; the administration UI on the board's `/_/` path is disabled by default
and requires `lll up --admin-ui`. The separate API listener at :8090 keeps its
own administration routes.

Never `pkill -f "bin/lll up"` - the pattern matches every worktree's identical
binary path and kills every sibling agent's server. Kill only PIDs you started.

## Editing the shipped skills

`.claude/skills/<name>/SKILL.md` is the editable source for the five shipped
skills; `skills/` is a committed mirror. After editing one, run
`python3 scripts/sync_skills.py`. Keep them generic: no team key, no
`mise run`, no ticket keys, no relative links, and no names of skills that do
not ship. Anything specific to this repo goes on this page.
