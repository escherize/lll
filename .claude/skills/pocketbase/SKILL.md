---
name: pocketbase
description: How this project uses PocketBase - the local gopb wrapper, embedded JS migrations, Go hooks, collection rules and their public-by-default trap, realtime subscriptions, and token-based auth. Use before changing anything under pb/ or gopb/, before adding a collection or field, before touching collection rules or auth, and whenever a PocketBase API call 404s or returns unexpected data. Triggers on "add a collection", "add a field", "migration", "collection rule", "realtime", "subscription", "auth", "api key", "token", "PocketBase", "gopb", "Missing collection context".
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
- `pb/pb_data/` — the SQLite database (`data.db` + WAL) and `auxiliary.db` for
  PocketBase's own logs. Gitignored. Move it with `lll up --pb-dir`.
- `pb/embed.go` — embeds the migrations in the binary. `gopb` materializes
  them under the selected data directory before applying them.
- `gopb/` — a **nested Go module** wrapping PocketBase behind one `Serve` function;
  Go hooks own per-team issue numbering, defaults and write enforcement.

## gopb: a nested Go module, no longer commit-pinned

`gopb/` is its own Go module (`github.com/escherize/lll/gopb`) wrapping
PocketBase behind one `Serve` function.

The adapter keeps PocketBase's transitive types out of Lisette's bindgen.
Keep PocketBase calls behind this Go boundary rather than binding PocketBase
directly in `.lis` files.

`lisette.toml` declares this module with `{ path = "gopb" }`, alongside the
local `web`, `pb` and `skills` modules. Edit the local source and run
`mise run build` or `mise run gate`; no commit, push or dependency re-pin is
needed to test a gopb change. The old public pseudo-version loop is retired.

## Schema changes

Add a migration file under `pb/pb_migrations/`, named `<unix-ts>_<what>.js`,
matching the style of `1756400000_init.js`. It applies on the next `lll up`.

**Migrations are a merge hazard between concurrent agents.** Filenames are
timestamp-ordered and two agents both minting one for the same feature area will
collide or apply in a surprising order. Before writing one, check whether another
in-progress task also adds a field (`lll issue list --state in-progress`),
and prefer extending an unapplied migration over adding a second.

Use `lll api --schema` for the generated collection and field reference;
[`docs/api.md`](../../../docs/api.md) documents the API. Regenerate
`src/commands/api_schema.lis` with
`mise run api-schema` in the same change as schema edits; the gate checks it
against the migrations. `issues` is UNIQUE on `(team, number)`.

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
`@request.auth.id != ""` - any authenticated member, no per-record ACLs. Four
carve-outs, each deliberate:

- `claims.updateRule` is `null`. A member who could PATCH a claim could set its
  `member` to themselves and steal the hold; claims move through gopb's
  transactional route instead.
- `claims.deleteRule` is `null` (`1789800000_claim_delete_admin.js`, LLL-512).
  `/release` lets only the holder release without force, and a direct DELETE
  would skip that check. The expiry sweep deletes through the Go app, which
  collection rules do not apply to.
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

**Identity is the token** (LLL-445, decision `board-identity-is-a-member-token`).
A member token determines authorship. `me` and `LLL_ME` are no longer settings;
legacy file keys are ignored. A superuser token has no member identity, so
optional CLI authorship is empty and claims require a member token. `lll up`
uses admin credentials to bootstrap, then impersonates a member from `$USER`
(`local` when absent). The board and automatic renewals keep that member's identity.

- Humans: email + password, PocketBase's built-in auth.
- Bots: a static, non-refreshable token from
  `POST /api/collections/members/impersonate/{id}` with `{"duration": <seconds>}`.
  Superuser-only. Duration <= 0 falls back to the collection's configured
  lifetime. (Verified in v0.40.1: `apis/record_auth_impersonate.go`,
  `core/record_tokens.go`.) This is the API-key mechanism — do not build a
  key table.
- Rules ARE `@request.auth.id != ""`. Keep it at that: any authenticated
  member sees everything, no per-record ACLs, with the four carve-outs above.

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

- **`404 "Missing collection context"`** means the API cannot resolve the
  requested collection. Check the configured server and collection name,
  then the startup migration log. `lll up` embeds its migrations via
  `pb.Migrations()` and materializes them under the selected data directory;
  its issue hooks are registered in Go. Running outside the checkout is
  supported and does not prevent migrations from applying.
- **One process per database file.** Never point two `lll up` instances at the
  same `pb_data`, especially over a network filesystem.
- **`field+` / `field-` modifiers are not atomic.** PocketBase reads the record,
  applies the modifier in memory and saves the whole value. Sixteen concurrent
  `issues+` PATCHes kept as few as one edge. `serializeRecordUpdates`
  (`gopb/issue_writes.go`) locks each `issues` and `docs` record for the whole
  request (LLL-513). If another collection needs modifiers, add it there.
  Keep the Batch API disabled (PocketBase's default): `/api/batch` sub-requests
  skip router middleware, so they bypass this lock.
- JS migrations run in goja, not Node. Runtime issue hooks are Go in `gopb/`.
- PocketBase installs its own SIGINT/SIGTERM handler, which suppresses Go's
  default die-on-signal for the whole process. `up.lis` runs `Serve` in a task and
  exits when it returns.
