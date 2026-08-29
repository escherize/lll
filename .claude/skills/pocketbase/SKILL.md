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
**lis 0.11.3 ships `lis add --path <dir>`** (verified: `lis add --help` shows
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
**superuser only**. Every collection in `init.js` currently has
`listRule`/`viewRule`/`createRule`/`updateRule`/`deleteRule` set to `""`, so
anything that can reach the port can read, edit and delete everything. That is
fine on localhost and unacceptable anywhere else. See task-32 and ADR-1.

## Auth (decided in ADR-1, not yet implemented)

`members` becomes an auth collection; every actor — human or agent — is one member
record.

- Humans: email + password, PocketBase's built-in auth.
- Bots: a static, non-refreshable token from
  `POST /api/collections/members/impersonate/{id}` with `{"duration": <seconds>}`.
  Superuser-only. Duration <= 0 falls back to the collection's configured
  lifetime. (Verified in v0.40.1: `apis/record_auth_impersonate.go`,
  `core/record_tokens.go`.) This is the API-key mechanism — do not build a
  key table.
- Rules become `@request.auth.id != ""`. Keep it at that: any authenticated
  member sees everything, no per-record ACLs.

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
