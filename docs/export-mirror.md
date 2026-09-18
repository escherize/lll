# Markdown export mirror

`lll export [DIR]` writes the configured team as Markdown: one file per issue,
one per document, attachment bytes beside the issue that owns them. The default
destination is `mirror/` under the current directory.

```sh
lll export mirror
rg 'regression' mirror/issues mirror/docs
```

Each mirror holds:

| path | what | round-trips |
|---|---|---|
| `issues/KEY-N.md` | YAML front matter plus the description | yes |
| `issues/KEY-N.comments.md` | the issue's comments | no, export only |
| `issues/KEY-N/` | attachment bytes, when the issue has any | bytes yes, names no |
| `docs/SLUG.md` | a document | not imported |

Front matter carries the fields the prose does not: state, priority, assignee,
project, labels, and the issue's `number` and `sort`. Those last two matter
more than they look — an import supplies them, so a restored `ENG-7` comes back
as `ENG-7` rather than being renumbered, and every cross-reference in every
description still points where it did.

The export is byte-stable: the same server state exported twice produces
identical files, so a scheduled mirror under Git commits only real changes.
Comment timestamps are absolute for the same reason (LLL-453).

## Reading it back

```sh
lll import dir mirror            # into a team with no issues
lll import dir mirror --replace  # delete every issue in the team, then import
```

This is a restore, not a sync. `lll import dir` refuses a team that already has
issues, because mixing two sets of numbering is not something it can undo;
`--replace` empties the team first. There is no merge and no per-field diff:
two writable copies of the same record need a reconciler, and
`lll doc view issue-text-and-state-live-in-lll` rejected that trade. Editing a
file in the mirror changes nothing until you import it, and importing rebuilds
the team from what is on disk.

A malformed file fails the whole import with nothing written — every file is
parsed before the first record is created.

What does come back: numbers, sort order, titles, descriptions, states,
priorities, emoji, assignees, projects, labels, refs, the original creation
origin, `blocked_by` dependency links, documents with their kind and retrieval
coordinates, and attachment bytes. Issue links inside documents and dependency
links between issues are stored as KEYS and re-resolved after every issue
exists, which works only because numbers round-trip.

Four things do not come back:

- **comments**, because nothing can forge another member's authorship
- **`created` / `updated`**, because a restored record is a new record and
  PocketBase stamps it on insert
- **attachment filenames**, because PocketBase assigns its own stored name on
  upload; the bytes are identical, the name gains a suffix
- **the original creator**, unless the import runs with superuser
  credentials. `gopb/provenance.go` attributes every member-authenticated
  create to the member making it, so an import run by a member is recorded as
  filed by that member. The mirror still carries the original name for a
  person reading it; the `origin` block (host, path, branch, commit, tool) is
  restored either way.

## What this is not

It is not a database backup. It carries no record ids, no member accounts and
no comment authorship. Use the [hosted recovery procedure](hosted-recovery.md)
— Fly volume snapshots — for a restorable backup. This is for reading the
tracker without a server, grepping it, and keeping its history in Git beside
the code's.
