---
name: lll
description: Use lll as the tracker and record for software work - claim a task before writing code, keep the board honest while you work, and leave a trail others can read. Covers the CLI (issues, comments, search, --raw, stdin bodies), the board, and the conventions that make a multi-agent backlog survive contact with parallel work. Use when starting any nontrivial change, when recording why something was built a certain way, when you hit friction worth capturing, or when you need to know what is already known about a file or an area. Triggers on starting to write code, "claim a task", "file an issue", "what's on the board", "why did we", "record this decision", "log friction", "audit trail".
---

# Working through lll

lll is the tracker AND the record. The point is not project management: it is
that six months from now, someone (probably an agent) can ask *why is this like
this* and get an answer instead of a guess.

Two rules carry most of the value:

1. **Claim before you code.** Work nobody claimed gets done twice.
2. **Nothing lives only in your head.** If you learned it the hard way, write it
   down where the next person will trip over the same thing.

## The loop

```sh
lll issue list --state todo            # what is open
lll issue view KEY-12                  # read it FULLY before you touch anything
lll issue update KEY-12 --state in-progress --assignee "$(whoami)"
# ... work ...
lll issue comment KEY-12 -b "what changed and why"
lll issue close KEY-12
```

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

While you work, file anything that slowed you down or that you wished existed:

```sh
lll issue create -t "e2e picks random ports without checking they are free" -d -
```

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

## The board

`lll up` runs PocketBase and the board together; `mise run dev` builds first.
Board at :8100, PocketBase admin at :8090/_/. Changes made anywhere (CLI, web,
another agent) appear in every open browser without a reload, over one SSE
stream, so the CLI and the board are never out of sync.
