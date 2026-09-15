---
name: pocketbase
description: How this project uses PocketBase - the embedded gopb wrapper and its commit-pin loop, schema changes via JS migrations, pb_hooks, collection rules and their public-by-default trap, realtime subscriptions, and auth (email+password for humans, static impersonate tokens for bots). Use before changing anything under pb/ or gopb/, before adding a collection or field, before touching collection rules or auth, and whenever a PocketBase API call 404s or returns unexpected data. Triggers on "add a collection", "add a field", "migration", "pb_hooks", "collection rule", "realtime", "subscription", "auth", "api key", "token", "PocketBase", "gopb", "Missing collection context".
---

# PocketBase in lll

lll embeds PocketBase in-process. There is no separate server to install or run:
`lll up` starts it, applies migrations, upserts the superuser, then serves the board.

**Standing guidance from the user (2026-08-28): prefer PocketBase's own tools —
filters, realtime subscription options, hooks, the admin UI, collection rules,
auth — over reimplementing the same thing in lll code.** PocketBase is a large
piece of software that has already solved most of what an issue tracker needs.
Reach for lll code only when PocketBase genuinely has no answer.

## The layout

- `pb/pb_migrations/*.js` — schema as code. Applied automatically before the
  server starts listening.
- `pb/pb_hooks/main.pb.js` — JS hooks running in goja. Currently: per-team issue
  numbering and default board `sort`.
- `pb/pb_data/` — the SQLite database (`data.db` + WAL) and `auxiliary.db` for
  PocketBase's own logs. Gitignored. Move it with `lll up --pb-dir`.
- `gopb/` — a **nested Go module** wrapping PocketBase behind one `Serve` function.

## gopb: a nested Go module, no longer commit-pinned

`gopb/` is its own Go module (`github.com/escherize/lll/gopb`) wrapping
PocketBase behind one `Serve` function.

It exists because binding PocketBase directly breaks Lisette's bindgen on two
transitive typedefs (`golang.org/x/crypto/acme` pulls the GOEXPERIMENT-only
`encoding/json/jsontext`; `github.com/dop251/goja/parser` has Go-style `\uXXXX`
escapes the lexer rejects). Do not try to `lis add` PocketBase itself — see
`.private/findings/claude-task12/`.

**Historical note that is now obsolete:** under the toolchain in use through
2026-08-28, lis had no local-path dependencies, so every edit to `gopb/gopb.go`
required commit + push of the public repo + `lis add
github.com/escherize/lll/gopb@<new-commit>` to re-pin the pseudo-version.
**lis ships `lis add --path <dir>`** (verified on 0.11.3 and 0.12.0: `lis add --help` shows
`--path <dir>  Add a local Go module`), which removes that loop entirely.
`lisette.toml` still carries the pinned pseudo-version
`v0.0.0-20260828210548-11804d3d2b7d`; converting it to a path dep is filed
separately. Until that lands, assume the pin is live and check `lisette.toml`
before promising a quick gopb change.

## Schema changes

Add a migration file under `pb/pb_migrations/`, named `<unix-ts>_<what>.js`,
matching the style of `1756400000_init.js`. It applies on the next `lll up`.

**Migrations are a merge hazard between concurrent agents.** Filenames are
timestamp-ordered and two agents both minting one for the same feature area will
collide or apply in a surprising order. Before writing one, check whether another
in-progress task also adds a field (`backlog task list --plain` for In Progress),
and prefer extending an unapplied migration over adding a second.

Existing collections: `teams` (key UNIQUE, name), `members` (name UNIQUE, email),
`projects`, `labels`, `issues`, `comments`. `issues` is UNIQUE on `(team, number)`.

**Issue keys like `ENG-1` are derived, never stored** — every display site builds
them from `team.key + "-" + number`. Renaming a team rewrites every key for free.
The exception: `ENG-1` typed into a description or comment body is stored text and
goes stale.

## Collection rules: `""` is public, not private

In PocketBase, an empty-string rule means **anyone**, and `null` means
**superuser only**. That inversion is the trap: a collection created with
default rules is wide open, and it reads like the opposite.

`init.js` did ship every collection at `""`. It no longer stands:
`1788400000_collection_rules.js` moved them to `AUTH`, which is
`@request.auth.id != ""` - any authenticated member, no per-record ACLs. Three
carve-outs, each deliberate:

- `claims.updateRule` is `null`. A member who could PATCH a claim could set its
  `member` to themselves and steal the hold; claims move through gopb's
  transactional route instead.
- `members.deleteRule` is `null` (`1789200000_member_delete_admin.js`, LLL-341).
  Deleting an account is a superuser act, because a browser-only check would
  leave direct API deletion as a bypass.
- `users` is `null` across the board. lll does not use that collection, and
  PocketBase's stock `createRule` is public self-registration nobody asked for.

**A new collection does not inherit any of this.** Add one and you must set its
rules in the same migration, or it ships public.

## Auth (shipped)

`members` IS an auth collection (`1788300000_members_auth.js`); every actor -
human or agent - is one member record.

**Identity is the token, and `me` may only agree with it** (TASK-317, decision
`identity-is-the-token`). The author of a write is the member the token names; a
configured `me` naming someone else is refused with both names. A superuser
token names nobody, so under it `me` attributes as before. This is why `me` does
not create members: a field that may only agree with who you are must not be
able to mint who you are (LLL-374).

- Humans: email + password, PocketBase's built-in auth.
- Bots: a static, non-refreshable token from
  `POST /api/collections/members/impersonate/{id}` with `{"duration": <seconds>}`.
  Superuser-only. Duration <= 0 falls back to the collection's configured
  lifetime. (Verified in v0.40.1: `apis/record_auth_impersonate.go`,
  `core/record_tokens.go`.) This is the API-key mechanism — do not build a
  key table.
- Rules ARE `@request.auth.id != ""`. Keep it at that: any authenticated
  member sees everything, no per-record ACLs, with the three carve-outs above.

`issues.assignee` already relates to `members`, so `@request.auth.id` *is* a
member id — "my issues" is one filter, and authorship stops being a convention.

## Realtime

The board holds **one** PocketBase subscription for everything, bridged to
browsers over a single SSE stream (`run_server` in `src/commands/serve.lis`).

Issue subscriptions are team-scoped at most and **never state-filtered**:
PocketBase emits nothing when an update moves a record *out* of a subscription
filter, so a filtered column would silently go stale. Filter in the view, not in
the subscription.

Per-record collection rules would fragment the one shared subscription into one
per viewer. That is a good reason not to add them.

## Gotchas

- **`404 "Missing collection context"`** means migrations never ran. Almost always
  because `lll up` was run outside the checkout: `pb/pb_migrations` and
  `pb/pb_hooks` are passed to `gopb.Serve` as cwd-relative paths (task-30).
- **One process per database file.** Never point two `lll up` instances at the
  same `pb_data`, especially over a network filesystem.
- `pb_hooks` JS runs in goja, not Node. `/// <reference path="../pb_data/types.d.ts" />`
  at the top gives editor types; the file is regenerated by PocketBase on boot.
- PocketBase installs its own SIGINT/SIGTERM handler, which suppresses Go's
  default die-on-signal for the whole process. `up.lis` runs `Serve` in a task and
  exits when it returns.
