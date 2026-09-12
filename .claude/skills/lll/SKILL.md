---
name: lll
description: Use lll as the tracker and record for software work - claim a task before writing code, keep the board honest while you work, and leave a trail others can read. Covers the CLI (issues, comments, search, --raw, stdin bodies), the board, and the conventions that make a multi-agent backlog survive contact with parallel work. Use when working on lll itself or when exercising the lll board, and for the claim-before-code / record-what-you-learned conventions. Triggers on "lll issue", "claim a task", "file an issue", "what's on the board", "why did we", "record this decision", "log friction", "audit trail".
---

# Working through lll

lll is the tracker AND the record. The point is not project management: it is
that six months from now, someone (probably an agent) can ask *why is this like
this* and get an answer instead of a guess.

## One tracker: this project runs on its own board

This skill covers the lll CLI, which is the product under development, and
the lll board is also where THIS project's work is tracked: team `LLL` on
the hosted instance named in `.lll.toml`. `lll issue list` from the checkout
is this project's real work list. (A seeded demo board - `mise run seed` -
is the fixture for exercising the tool; it is a different url and team.)

The sidecar notes repo that used to hold the backlog, findings and decisions
was imported here and archived; its url is in `.private-remote`, read-only.
If a local `.private` is retained, run `mise run archive-protect` once to remove
write permissions; the gate verifies protection. This changes permissions,
not historical contents. See `docs/archive-history.md`. Fresh checkouts need
not clone an archive.
Findings are `lll finding list` / `lll finding near PATH`, decisions are
`lll doc list` (kind decision), the backlog is the issue list.

## The loop

```sh
lll issue list --state todo            # what is open
lll issue view KEY-12                  # read it FULLY before you touch anything
lll issue claim KEY-12                 # exits non-zero if someone got there first
lll issue update KEY-12 --state in-progress
# ... work ...
lll issue comment KEY-12 -b "what changed and why"
lll issue close KEY-12
```

`claim` atomically acquires an issue for the member authenticated by your token.
A successful claim is immediately visible on the server; no Git push is needed.
If another member holds it, the command exits nonzero without taking over.
Claiming your own issue again succeeds and says it is already yours.
`--assignee` cannot replace another member's active claim: release it first.
`lll whoami` shows the authenticated identity. If `me` is configured, it must
agree with that identity. `lll issue release KEY-12` gives the claim back and
clears the assignee when it still matches the holder.

`lll issue start KEY-12` sets in-progress without changing Git. To create a
branch and record its host/path on the issue, use `lll issue start KEY-12 --branch`.
For separate Git commands, `lll issue branch-name KEY-12` only prints a suggested
name; it changes nothing. Once you
are on an issue branch, commands can infer the issue from it:
`lll issue view` with no argument is the issue you are on.

## What agents specifically need

**Read a URL, not a scrape.** Any command taking `KEY-12` also takes a pasted
board URL. `lll issue view KEY-12 --raw` prints the issue as plain markdown,
which is what you want in a prompt or a pipe. `--json` gives the raw record with
relations expanded.

**Pipe bodies in.** `-d -` and `-b -` read from stdin, so generated text never
needs a temp file:

```sh
printf '%s' "$analysis" | lll issue create -t "Title" -d -
git log --oneline -20 | lll issue comment KEY-12 -b -
```

**Set an emoji on every issue you create.** The board is scanned, not read, and an emoji
is the only thing legible at card size. This is not decoration: it is how a human sees at
a glance what a column is full of.

```sh
lll issue create -t "e2e flakes on a random port" --emoji 🐛
```

Use the kind of work, not your mood. A small vocabulary beats a large one, because the
value is in the pattern being recognisable:

| emoji | kind |
|---|---|
| 🐛 | bug |
| ✨ | feature |
| ♻ | refactor |
| 📝 | docs |
| 🔧 | tooling, build, CI |
| 🧪 | tests |
| ⚡ | performance |
| 🔒 | security |

**Filter server-side.** `lll issue list` supports `--state`, `--assignee`,
`--label`, `--project`, `--search`, `--sort`, `--limit`, and `--json`. Other
read commands expose their supported filters in `--help`.

## Always document friction and feature requests

**This is not optional and it is not a nicety.** Every agent hits the same walls,
and the ones that go unrecorded get hit again by the next agent, at full cost.
Real examples from this project: a shell-working-directory trap was recorded
after two occurrences and happened twice more; a byte-offset versus rune-index
bug was in a finding before it panicked in five places.

File work on this project in team `LLL` on the hosted board, using the CLI:
`lll issue create -t "Title" --emoji 🐛 -d -`. The old `.private/` sidecar is
read-only history. Do not write new tasks there. When using another project's
board, file in that project's team. Keep scratch/demo fixtures separate from
these real work records.

File it **when you hit it**, not at the end. Two kinds both count:

- **Friction**: a command that did not behave as documented, an error that did
  not name its fix, a step that needed knowledge nowhere written down, a tool
  that silently did nothing.
- **Feature requests**: the thing you reached for and it was not there.

Do not fix drive-by problems inline. File them and return to your task, so one
change stays one change and the finding survives even if the fix does not happen.

Describe the **symptom, the cause if you found it, and what you tried**. A title
alone is a note to nobody.

## The audit trail

The trail is only worth having if it answers questions later. Three kinds of
record, and they are not interchangeable:

| kind | what it is | when |
|---|---|---|
| **comment on an issue** | what changed and why, on the work item | during the work |
| **decision** | a choice with alternatives and consequences, immutable | when a choice constrains future work |
| **finding** | a trap, learned the hard way, tied to an area | the moment it costs you time |

**Write the decision when you make it, not when you ship it.** A decision
recorded after the fact is a rationalisation: it remembers what you did and
forgets what you rejected. The rejected options are the valuable half, because
the next person will think of them too.

Good decisions name what was NOT chosen and why. "Used X" is worthless. "Used X
because Y needs a reconciler and two writable copies" is worth the file.

## Side projects: attach, work, archive

A team is cheap — give every side project its own instead of piling issues
into a shared one. It does not have to be a repo: `lll attach` in a plain
directory writes `.lll.toml` there and every subdirectory inherits it, so a
folder of notes gets tracked without a `git init`.

```sh
lll attach                 # once, repo or plain dir: creates KEY, writes .lll.toml
lll issue create -t "..."  # work, tracked as KEY-1, KEY-2, ...
lll team archive KEY       # done: leaves team lists and the board rail
```

Archiving hides, never deletes: `/t/KEY/` still renders with an "archived"
banner and everything stays readable, but new writes refuse and name the fix
(`lll team unarchive KEY`). `lll team list --archived` shows what is parked.
Archive rather than abandon — a board that lists only live teams is one you
can actually scan.

## Conventions that keep a parallel backlog honest

- **Claim before editing.** A successful CLI claim is already visible to other agents.
- **Read the task in full before mutating it.** Its notes may carry a decision
  already made; implementing your own instead wastes both.
- **Correct a wrong acceptance criterion, out loud.** Never quietly pass one.
  A criterion that turned out to be unmeasurable is a finding about the task.
- **Check criteria against evidence you actually ran.** Not code presence, not
  grep output, not intent. If it is a UI change, look at it.
- **One task per change.** If you find a second problem, file it.

When dividing work among reviewers or implementers, derive each task's file
list from the current checkout. Search for its target symbols with `rg -n`,
then read the matches to distinguish definitions, callers and unrelated names.
Do not assign paths from memory. Include the search command, its matching
path/line output and the checkout commit in the task brief or rules file so
the recipient can verify the scope. If there are no matches, investigate and
record that uncertainty before assigning a file list.

Recipients should verify that evidence against their checkout before editing.
If a symbol moved, search for it again and record the corrected path on the
issue; an outdated file list does not prove there is no work to do.

## Group work by outcome

Projects name durable destinations, such as Release 1 or multi-project server
mode. A parallel wave is a scheduling record, not automatically a project.
Before closing scoped work, check its project association against the outcome;
leave explicitly deferred or unrelated work outside a release commitment.
Read live counts with `lll project view NAME`. Closed-item counts do not prove
release readiness. Policy and the historical backfill are recorded in
`lll doc view projects-name-outcomes-not-waves` and
`lll doc view historical-wave-project-audit`.

## Verification, before you claim anything works

Run what the user runs, not what you built. The gate is:

```sh
mise run gate     # build + unit tests + full e2e
```

If a failure looks unrelated to your change, **re-run the same tree two or three
times before concluding you caused it.** A flaky assertion here once caused
finished work to be parked as broken.

If you run a server by hand while others might be running one too, do not
hand-roll the isolation — `mise run scratch` is it:

```sh
mise run scratch              # free ports, a temp --pb-dir, safe in parallel
mise run scratch -- --no-open # extra flags pass straight through to lll up
```

It picks both ports by BINDING them (a liveness probe cannot tell a free port
from a stranger's server), and runs on loopback with a fresh database, home
and working directory. Inherited `LLL_*` settings are cleared except an
explicit `LLL_TEAM`; the default team is SCRAT. The banner prints the board
login URL, local admin credentials and isolated config path. CLI access to
this database needs its own local authentication; a hosted login token does
not authenticate against the scratch database. The temporary directory is
kept after shutdown; the banner shows the `rm -rf` to run when finished.

`mise run dev` is the OTHER thing: it hardcodes port 8100 and `pb/pb_data`, so
it is the shared local board and two of them collide. Use it when you want the
persistent one, `scratch` when you want a board to poke at.

Never `pkill -f "bin/lll up"` — the pattern matches every worktree's identical
binary path and kills every sibling agent's server. Kill only PIDs you started.

## The board

`lll up` runs PocketBase and the board together; `mise run dev` builds first.
Board at :8100, PocketBase admin at :8090/_/. Changes made anywhere (CLI, web,
another agent) appear in every open browser without a reload, over one SSE
stream, so the CLI and the board are never out of sync.
