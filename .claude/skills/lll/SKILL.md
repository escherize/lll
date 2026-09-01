---
name: lll
description: Use lll as the tracker and record for software work - claim a task before writing code, keep the board honest while you work, and leave a trail others can read. Covers the CLI (issues, comments, search, --raw, stdin bodies), the board, and the conventions that make a multi-agent backlog survive contact with parallel work. Use when working on lll itself or when exercising the lll board, and for the claim-before-code / record-what-you-learned conventions. Triggers on "lll issue", "claim a task", "file an issue", "what's on the board", "why did we", "record this decision", "log friction", "audit trail".
---

# Working through lll

lll is the tracker AND the record. The point is not project management: it is
that six months from now, someone (probably an agent) can ask *why is this like
this* and get an answer instead of a guess.

## Two trackers, know which one you are in

This skill covers the lll CLI, which is the product under development. When
you run `lll issue list` you are reading the lll board — in this checkout that
board is the FIXTURE (the seeded ENG demo data), not this project's work list.

Work on the lll project itself is claimed from the sidecar backlog:

```sh
cd .private && backlog task list --plain   # THIS project's real work
```

Every `lll` command below applies to whatever lll board you are pointed at —
use it when building lll, when exercising the board, or when a task tells you
to. It does NOT track this repo's engineering work; see
`.claude/skills/private-sync/SKILL.md` for that.

Two rules carry most of the value:

1. **Claim before you code.** Work nobody claimed gets done twice.
2. **Nothing lives only in your head.** If you learned it the hard way, write it
   down where the next person will trip over the same thing.

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

`claim` is the one command whose failure you must not ignore. It inserts a row
into a collection that is UNIQUE on the issue, so when two agents claim the
same issue at the same moment the database picks one and tells the other whose
it is. `--assignee` cannot do that: it is a PATCH, so both agents "succeed" and
neither finds out. Claim as the `me` in your config; `lll issue release KEY-12`
hands it back.

`lll issue start KEY-12` sets in-progress and creates the branch
`key-12-slug`, after which every command infers the issue from the branch:
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

**Filter server-side.** `--state`, `--assignee`, `--label`, `--project`,
`--search`, `--sort`, `--limit`, and `--json` on every read command.

## Always document friction and feature requests

**This is not optional and it is not a nicety.** Every agent hits the same walls,
and the ones that go unrecorded get hit again by the next agent, at full cost.
Real examples from this project: a shell-working-directory trap was recorded
after two occurrences and happened twice more; a byte-offset versus rune-index
bug was in a finding before it panicked in five places.

Where to file it depends on which tracker owns the work:

- **Work on the lll project itself** — file it in the sidecar backlog, NOT with
  the lll CLI: `cd .private && backlog task create "Title" -d "symptom, cause, what you tried"`.
  The lll board in this checkout is demo data; an issue filed there disappears
  into the fixture and nobody reads it.
- **Using some OTHER project's lll board** (or exercising lll as a product) —
  file with the CLI: `lll issue create -t "Title" -d -`.

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
into a shared one:

```sh
lll attach                 # once, in the repo: creates team KEY, writes .lll.toml
lll issue create -t "..."  # work, tracked as KEY-1, KEY-2, ...
lll team archive KEY       # done: leaves team lists and the board rail
```

Archiving hides, never deletes: `/t/KEY/` still renders with an "archived"
banner and everything stays readable, but new writes refuse and name the fix
(`lll team unarchive KEY`). `lll team list --archived` shows what is parked.
Archive rather than abandon — a board that lists only live teams is one you
can actually scan.

## Conventions that keep a parallel backlog honest

- **Push a claim immediately.** A claim nobody can see protects nobody.
- **Read the task in full before mutating it.** Its notes may carry a decision
  already made; implementing your own instead wastes both.
- **Correct a wrong acceptance criterion, out loud.** Never quietly pass one.
  A criterion that turned out to be unmeasurable is a finding about the task.
- **Check criteria against evidence you actually ran.** Not code presence, not
  grep output, not intent. If it is a UI change, look at it.
- **One task per change.** If you find a second problem, file it.

## Verification, before you claim anything works

Run what the user runs, not what you built. The gate is:

```sh
mise run gate     # build + unit tests + full e2e
```

If a failure looks unrelated to your change, **re-run the same tree two or three
times before concluding you caused it.** A flaky assertion here once caused
finished work to be parked as broken.

If you run a server by hand while others might be running one too, isolate it:
`LLL_URL=http://127.0.0.1:<free-port> lll up --port <free-port> --pb-dir <your-own-dir> --no-open`.
Never `pkill -f "bin/lll up"` — the pattern matches every worktree's identical
binary path and kills every sibling agent's server. Kill only PIDs you started.

## The board

`lll up` runs PocketBase and the board together; `mise run dev` builds first.
Board at :8100, PocketBase admin at :8090/_/. Changes made anywhere (CLI, web,
another agent) appear in every open browser without a reload, over one SSE
stream, so the CLI and the board are never out of sync.
