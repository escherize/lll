# Use lll as the tracker for Matt Pocock's skills

[Matt Pocock's engineering skills](https://github.com/mattpocock/skills) turn a
conversation into a spec, the spec into tickets with blocking edges, and the
tickets into work an agent picks up. They read one file,
`docs/agents/issue-tracker.md`, to learn how to reach your tracker. Put the
file below in your repo and `to-spec`, `to-tickets`, `triage` and `wayfinder`
publish to an lll board.

The skills ask a tracker for six things. lll has a command for each:

| The skills need | lll command |
|---|---|
| A ticket per slice | `lll issue create` |
| Tickets under their spec | `--parent KEY` |
| Blocking edges | `lll issue block KEY BLOCKER` |
| The frontier: unblocked, unclaimed tickets | `lll issue next` |
| A claim before work | `lll issue next --claim`, `lll issue claim KEY` |
| Triage labels | `lll label create`, `--add-label` |

## Before you start

- A board and a team your agents can write to. See [Set up a board](setup.md).
- The repo attached to that team with `lll attach`, so commands need no
  `--team`.
- The skills installed, as their README describes.

## 1. Create the triage labels

`to-tickets` applies `ready-for-agent`, and `triage` uses all five:

```sh
for name in needs-triage needs-info ready-for-agent ready-for-human wontfix; do
  lll label create "$name"
done
```

## 2. Tell the skills where issues live

Run `/setup-matt-pocock-skills`. At **Section A: Issue tracker**, answer
**Other** and paste the file below as the description, or write it to
`docs/agents/issue-tracker.md` yourself.

````markdown
# Issue tracker: lll

Issues and specs for this repo live on an lll board. Use the `lll` CLI for all
operations. The team comes from `.lll.toml`; issue keys look like `ENG-42`.

## Conventions

- **Create an issue**: `lll issue create "Title" -b -` with the body on stdin.
  Add `--json` and read `.key` when you need the new key.
- **Read an issue**: `lll issue view KEY --json` returns the record with its
  comments, blockers (`blocked_by_refs`) and children (`children_refs`).
- **List issues**: `lll issue list --state todo --label NAME --json`. The
  result is an envelope: read `.items`, and `.totalItems` for a count.
- **Make an issue a sub-issue of a parent**: `lll issue create --parent KEY`,
  or `lll issue update KEY --parent PARENT` afterwards.
- **Blocking**: `lll issue block KEY BLOCKER` records that KEY cannot start
  until BLOCKER is done. `lll issue unblock` removes it. A ticket is unblocked
  when every blocker is done.
- **Count open blockers**: `lll issue list --parent PARENT --blocked` lists the
  children that still wait on something.
- **Comment on an issue**: `lll issue comment KEY -b -` with the body on stdin.
- **Apply / remove labels**: `lll issue update KEY --add-label NAME` /
  `--remove-label NAME`. Create a label once with `lll label create NAME`.
- **Close**: post the explanation with `lll issue comment`, then
  `lll issue close KEY`.

Give each session its own label with `--agent NAME` (or `LLL_AGENT`), so the
board shows which session wrote what.

## When a skill says "publish to the issue tracker"

Create an lll issue.

## When a skill says "fetch the relevant ticket"

Read it as in **Read an issue** above.

## Picking up work

- **Frontier**: `lll issue next --label ready-for-agent` prints the key of the
  one issue to work next: ready, unclaimed, highest priority first. It exits 5
  when nothing is ready.
- **Claim**: `lll issue next --label ready-for-agent --claim` takes that issue
  atomically. If another worker wins the race it prints no key and exits
  non-zero. To claim a ticket you already chose: `lll issue claim KEY`.
- A claim is released when you close the issue. `lll issue release KEY` gives
  it back without closing.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as
tickets.

- **Map**: an issue labelled `wayfinder:map`, holding the Notes /
  Decisions-so-far / Fog body.
- **Child ticket**: `lll issue create --parent MAP --label wayfinder:<type>`
  (`research`/`prototype`/`grilling`/`task`).
- **Blocking**: see **Blocking** under Conventions.
- **Frontier query**: `lll issue list --under MAP --ready --json`. The items
  include the map itself; skip it, and skip any item whose `claim` is set.
- **Claim**: `lll issue claim KEY`, the session's first write.
- **Resolve**: `lll issue comment KEY -b -` with the answer, then
  `lll issue close KEY`, then append a context pointer to the map's
  Decisions-so-far with `lll issue update MAP --description-append "..."`.
````

## 3. Publish tickets and work them

Run `/to-spec`, then `/to-tickets`. The skill publishes the spec's slices in
dependency order, so each blocking edge names a real key.

Start each worker with:

```sh
key=$(lll issue next --label ready-for-agent --claim --agent worker-1)
```

## What the commands print

Run on a scratch board, lll 1.8.0, on 2026-11-21. One spec, two tickets under
it, the second blocked by the first:

```console
$ lll issue block SCRAT-3 SCRAT-2
SCRAT-3 is blocked by SCRAT-2

$ lll issue list --parent SCRAT-1 --blocked
SCRAT-3  ○ todo    Download button calls the serializer    just now

$ lll issue next --label ready-for-agent --claim --agent worker-1
Claimed SCRAT-2 for scratch
SCRAT-2
```

A second worker asking while the first ticket is open gets nothing, and exit
code 5:

```console
$ lll issue next --label ready-for-agent --claim --agent worker-2
Nothing to do: no other ready issues; 1 open issue matches but is blocked (SCRAT-3): ...
```

After `lll issue close SCRAT-2`, the same command hands the second worker the
ticket that was waiting:

```console
$ lll issue next --label ready-for-agent --claim --agent worker-2
Claimed SCRAT-3 for scratch
SCRAT-3
```

`Claimed ...` goes to stderr and the key to stdout, so `key=$(...)` captures
the key alone.

## Limits

- **Verified:** every command in the tracker file, against a scratch board.
  **Not verified:** a full `/to-spec` and `/to-tickets` run publishing to lll.
  Those skills only run when a person invokes them.
- Both workers in the example share one member, so the claim separates them by
  agent label. Agent labels are self-asserted. For workers that must not be
  able to take each other's tickets, give each one its own bot member. See
  [permissions for people and agent workers](permissions.md).
- `lll issue next` has no flag to stay inside one spec. Scope it with a label
  or `--project`, or use `lll issue list --under KEY --ready`.
- The skills' setup step offers GitHub, GitLab and local Markdown by name. lll
  goes in under **Other**, as freeform text.
