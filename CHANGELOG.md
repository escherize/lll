# Changelog

All notable changes to lll. The format follows Keep a Changelog; versions
follow SemVer, with 0.x meaning the CLI surface can still move between
minors. Issue keys are on the project's own board (`lll issue view KEY`).

## [Unreleased]

### Changed

- `issue update --description-replace "old=new"` replaces exactly one match
  and composes with `--description-append`. The legacy old/new pair remains
  accepted for one release, hidden from help, with a deprecation hint (LLL-506).

## [0.6.1] - 2026-09-19

Local boards can now be disposable or shared with a small team without
inheriting a hosted connection or assembling credentials by hand.

### Added

- `lll up --scratch` (`--local`) creates an isolated throwaway board with fresh
  ports, data, and config. It ignores inherited `LLL_*` values, home config,
  and the caller's `.lll.toml`, and prints the temporary CLI connection
  (LLL-487).
- `lll up --bind LAN_OR_TAILSCALE_IP` starts a shareable board on that address,
  advertises a reachable board/login URL, and keeps random administrator and
  browser-gate secrets private across restarts. An inherited hosted URL or
  token cannot redirect this explicit local boot (LLL-497).
- `lll member passes --count 10` creates distinct human members and one-year
  API tokens, then writes a private `0600` handoff file with each person's
  credential and the shared board login link. Browser edits still use the
  board process identity (LLL-497).

## [0.6.0] - 2026-09-19

The CLI now uses one authenticated member identity, and retries of issue
creation can be made safe with a caller-supplied key.

### Removed

- The separate `me` / `LLL_ME` identity setting, its setter, and mismatch
  warnings. Old config keys are ignored; `whoami` reports the member in the
  token and its source (LLL-445). Scripts that set `me` should drop it.

### Added

- `lll issue create --idempotency-key KEY` reuses an issue when the same team,
  key and creation body are retried, and refuses a changed body with 409. A
  keyed create checks server support before writing; unkeyed creates keep their
  existing behavior (LLL-438).
- `lll issue list --since` catches up on recently changed issues, document
  lists can filter with `--kind`, and search accepts a one-command `--team`
  override (LLL-439, LLL-440, LLL-483).
- Label creation accepts `--color`; GitHub issue import can set a default
  emoji for imported issues (LLL-470, LLL-469).
- `lll up --admin-ui` explicitly exposes the local administration UI. The
  default board no longer serves that UI or prints administrator credentials
  in its startup banner (LLL-372).

### Changed

- A locally started board authenticates as a member and renews that member's
  identity after token revocation, including its realtime subscription.
  Supplied member tokens remain authoritative (LLL-445).
- Saved member-token config files are private to their owner, including
  existing files rewritten by the CLI (LLL-475).
- `issue view` fetches independent records concurrently while preserving
  output and errors. Member, team, project and label lists read every page
  instead of silently stopping after 200 records (LLL-436, LLL-476).
- `issue next` stays within its selected team; project and label moves check
  all referencing issues before proceeding (LLL-477, LLL-479).
- HTTP reads reject incomplete response bodies. A failed saved-view refresh
  retains the previous rail content instead of clearing it (LLL-478, LLL-480).
- The landing page downloads the latest published release, and its demo board
  screenshot shows the current interface (LLL-459, LLL-425).

## [0.5.0] - 2026-09-17

A Markdown mirror of the board, and quicker ways to reach what is on it.

### Added

- `lll export [DIR]` exports a team's issues, documents and attachment bytes
  as Markdown. `lll import dir DIR` imports that mirror into an empty team;
  `--replace` explicitly deletes the team's existing issues first. Comments
  export but do not import, preserving their original authorship (LLL-454).
- Cmd+K opens a command palette from any board page to jump to an issue,
  document, section or team (LLL-447).
- `software-factory` and `codebase-skills` ship as built-in skills: the map
  of the development workflow and the interview for adapting it to a repo.

### Changed

- Settings are grouped into six sections by the scope of the change (LLL-446).
- Claim expiry leaves a comment on the issue explaining the automatic release
  (LLL-452). Raw issue output uses absolute comment timestamps (LLL-453).
- Filter menus scroll, and dimensions with many options offer search
  (LLL-451, LLL-455).
- Issue view fetches eight requests instead of eleven (LLL-436).
- `lll up` can use its local superuser credentials when the configured member
  token belongs to another server. It opens the board's login URL, including
  on loopback (LLL-443, LLL-444).
- A configured `me` is advisory when a member token supplies the authenticated
  identity (LLL-445).

## [0.4.0] - 2026-09-17

Optimistic edits that hold at the server, and a first run that has something
on it.

### Added

- `If-Unmodified-Since` on `PATCH /api/collections/issues/records/{id}`: pass
  the `updated` stamp your read returned and the server answers 412 — without
  applying the write — when the record has changed since, naming the stamp to
  retry with. `lll issue update --if-unchanged-since` sends it, so an edit
  can no longer land on a record someone changed between the CLI's read and
  its write; the check used to run on the client, and the round trip was the
  race. The header applies to the `issues` collection; without it a PATCH
  behaves exactly as before (LLL-399).
- `lll up --demo`: a first run with something on it — a seeded board that
  teaches the tool and doubles as a rubric (LLL-433).
- The board's /search reaches docs: findings and decisions get result rows
  linking to their doc page, so the board answers "have we hit this before"
  the way the CLI does (LLL-398).
- A team can carry an emoji beside its key: `lll team set-emoji GLYPH` (or
  the settings field), shown in the rail next to the accent, so a multi-team
  board says which team you are reading at a glance (LLL-427).
- The gate verifies `lll api --schema` against the migrations: a reference
  that no longer matches what the server enforces fails CI naming the drifted
  lines — it had described a schema nobody has through two releases, with
  every gate green (LLL-435).
- `lll skill get merge-gate`: a skill for the half after the pull request —
  what to verify once CI is green, and how to land without eating anyone's
  state (#100).

### Changed

- `issue update --if-unchanged-since` cannot be combined with `--assignee`:
  assignment writes go through the claim route, which arbitrates with its own
  claim stamp, and a precondition that silently stopped guarding would be
  worse than none. Run them as two updates (LLL-399).

## [0.3.2] - 2026-09-16

What a team is on a server that has more than one, and what happens to a
hold when the agent that took it is gone.

### Breaking

- **Team keys are uppercase.** They were stored as typed, so `eng` and `ENG`
  were two teams the unique index was happy with and prose could not tell
  apart, while the derived issue key, the rail and the docs all assumed
  uppercase. Normalised on write in the server, so the raw API obeys it too,
  and on lookup, so `LLL_TEAM=eng` and `/t/eng/` resolve rather than fail. A
  migration uppercases existing rows; a key whose uppercase form is already
  taken is left alone rather than merged, because the two teams own separate
  issues (LLL-235).
- **A claim older than 24 hours releases itself.** The server sweeps hourly
  and frees holds that outlived the agent that took them, clearing the
  assignee exactly when a deliberate `issue release` would - only when it is
  still the holder. Nothing announces it; if you mean to hold an issue for
  longer than a day, say so on the issue (LLL-183).

### Added

- Documents have an address: `/t/KEY/doc/SLUG` renders a decision, finding,
  PRD or wiki page with its markdown, kind, slug, retrieval coordinates and
  linked issues, and answers `?raw` with the source. Decisions and findings
  were the one record kind reachable only from a terminal, which is where
  "why is this like this" is usually asked. An issue's related findings now
  link to it (LLL-405).
- `lll label move NAME --to KEY` and `lll project move NAME --to KEY`, with
  a team select on each settings row. The scope was write-once, so a label
  created in the wrong team could only be deleted and remade - losing every
  issue that referenced it. The move is refused while issues outside the
  destination still reference the record, and names them (LLL-100).
- Findings carry a confidence: a suspected or refuted finding says so
  wherever it renders (LLL-396).

### Changed

- `issue list --sort priority` leads with the most urgent work, and
  unprioritised issues sort last in either direction - absent is not a
  priority below low. It also fetched the wrong page before: the first
  `--limit` rows of PocketBase's numeric order, so on a board with more
  unprioritised issues than the limit the urgent ones were never read at
  all (LLL-382).
- The issues table, the projects list and settings answer for the team in
  the URL rather than the one the server booted with. On a multi-team server
  every other team's name, accent, labels and projects were uneditable on the
  web, and the rail moved the current-team marker under the reader (LLL-426).
- Moving one card reads one column instead of the whole team (LLL-428).

### Fixed

- Related findings and comments no longer draw on top of each other on the
  issue page (LLL-424).
- `mise run seed` and `mise run api-schema` isolate their config root, not
  just `HOME`: `XDG_CONFIG_HOME` outranks it, so on a machine exporting one
  they read the developer's own config and died against a throwaway database
  (LLL-423, LLL-430).
- `lll api --schema` describes the schema the server actually has: bot
  member fields and the webhooks collection had been missing since they
  landed (LLL-430).

## [0.3.1] - 2026-09-16

### Fixed

- `lll --version` reports lll's version. It ran `git describe` at startup
  and answered with whatever repository the caller stood in, so the 0.3.0
  binary said `lll 0.2.0` outside a checkout, and `lll 9.9.9` inside a
  project tagged `v9.9.9`. The version is a literal now. The gate asserts
  it matches `[project] version` in lisette.toml, and that the answer is
  the same inside the checkout and outside it.

## [0.3.0] - 2026-09-15

The release shaped by several agents working one board at once: a command
that says what to work on next, identities that are not people, events that
leave the process, and the operating instructions carried in the binary.

### Breaking

- **Repeated `--state` and `--label` mean the union.** `--state todo
  --state in-progress` returns both. It used to keep the last one silently
  and drop the rest. A flag repeated where repetition means nothing is now
  refused instead of ignored.
- **`me` no longer mints members.** A `me` naming nobody used to create
  that member on the spot, which is how a board fills with identities
  nobody chose. It is now an error that names the fix.
- **Deleting a member requires admin authority.** Migration
  `1789200000_member_delete_admin.js` sets `members.deleteRule = null`.
  Deletion is refused for ordinary tokens, and checked against assignments
  and comment authorship first.
- **Claims, releases and assignment edits are one server transaction.**
  Deploy the server before you distribute the client. An older server
  refuses these writes and names the upgrade. It does not fall back to an
  unsafe two-request write. The endpoints commit the claim and every
  accompanying issue field together, against an observed claim id.
- **`lll up` serves one address.** The separate `:8091` API service is
  retired. The board proxies `/api/` and `/_/` on its own port.

### Added

- `lll issue next` prints the one issue to work now: ready and unclaimed,
  then priority, then oldest, then most-unblocking. `--claim` takes it, so
  an agent starts work in one command. `lll watch --ready` streams the same
  agenda as it changes.
- `lll webhook add|list|remove`: the server POSTs issue events to your
  URLs, with bounded retries and backoff for deliveries that fail.
- `lll api METHOD PATH`: authenticated passthrough to the board's
  PocketBase API. `--schema` prints the collection and field reference. It
  reaches what the CLI does not wrap, without the admin UI.
- `lll bot NAME`: an agent identity in one command, member and token,
  printed once. A bot member cannot log in, is owned by a person, is badged
  on the board, and is rotatable.
- `lll import github OWNER/REPO` brings a GitHub backlog in through `gh`:
  title, body, labels and state, each issue carrying its `gh#N` ref.
  Re-importing skips what it already brought.
- `lll skill list` and `lll skill get NAME`. The agent operating
  instructions ship inside the binary. An agent working from another repo
  reads them without this checkout.
- Attachments: `issue attach KEY FILE`, `issue unattach`, `issue cat`, and
  upload from the board. Files are protected, appended rather than
  replaced, and refused to anonymous readers.
- Surgical description edits: `issue update --description-replace-old/-new`
  and `--description-append`. `--if-unchanged-since STAMP` refuses a write
  when someone edited the issue first.
- Homebrew distribution: `brew install escherize/lll/lll`. The release
  workflow renders the tap formula and pushes it.
- Provenance: an issue records its creator, and the host, path, branch and
  commit it was created from. Both show on the board and in exports.
- `lll issue pr` records `gh#N` on the issue once `gh` confirms the pull
  request, and adopts the existing one when the branch already has it.
- Smaller additions:
  - `doc list --search`
  - `doc link` and `doc unlink`
  - `finding list --limit`, and a positional finding slug
  - `-l` for `--label`
  - `issue list --page N`, and sorting by title
- `lll login --url` discovers and persists the board's advertised endpoint
  through `/.well-known/lll`. An older server falls back to manual
  configuration.
- `LLL_CONFIG_HOME` chooses the config root, for harnesses that cannot set
  `HOME`.
- The board shows live claims, and can claim and release.
- Docs have an address. `/t/TEAM/doc/SLUG` renders a decision, finding, PRD
  or wiki page through the renderer that issue descriptions use, with the
  properties `doc view` prints beside it. A decision can now be linked to
  from an issue or a review. Read-only for now.

### Changed

- The board renders every issue in the team. Past roughly 200 it used to
  truncate silently. Pagination, ordering and live updates now hold across
  a full board.
- The saved column view rides a cookie the server reads on first paint, so
  the board no longer shows the wrong columns before correcting itself. The
  webfont is cached rather than refetched, for the same reason.
- The 401 board gate takes the token in a field, instead of only explaining
  where the token lives.
- Issue table columns are measured in grapheme display cells, so emoji and
  wide characters line up.
- Errors say what to do. Rejected edits restore the authoritative values,
  board write failures name themselves instead of vanishing, and creation
  errors appear inside the dialog that raised them.
- `cmd+enter` sends a comment, and a successful send clears the box.
- The e2e suites run from outside the checkout. A gate no longer writes to
  the tree another agent is reading, including the tracked `.lll.toml`.

### Fixed

- **An issue description could kill the board.** The hover preview capped
  on byte length and sliced on rune indices. A description of about 100
  accented characters, or 60 emoji, panicked a goroutine outside any HTTP
  handler, and the server process died.
- **`watch --json` panicked on any multi-byte record.** One emoji in the
  payload ended the stream, for the same reason: byte length fed to a rune
  index.
- Related findings and comments no longer draw on top of each other on the
  issue page. Both claimed one named grid area, so a single cell held two
  sections. The markup was correct; only the geometry was wrong.
- The last hidden column can be shown again. Unhiding it no longer restores
  the hide from the saved view.
- An expired boot token is re-minted, as a rejected one already was.
- `mise run scratch` and `mise run seed` read their own isolated config.
  Moving `HOME` stopped being enough once `LLL_CONFIG_HOME` and
  `XDG_CONFIG_HOME` outranked it. On a machine that exports the XDG one,
  both read the developer's real token.
- `issue list --sort priority` leads with urgent and leaves the
  unprioritised last. PocketBase sorts on the stored number, where `none`
  is 0, so the ascending fetch led with untriaged issues and buried the
  urgent ones. The order also decided which page you got: urgent work past
  `--limit` left the list entirely.
- `issue update --project ""` clears the project, `--` ends options in
  every verb, and search results supersede stale in-flight queries.

### Removed

- The `:8091` API service, the retired generated-typedef patch script, and
  the `private-sync` skill.

## [0.2.0] - 2026-09-08

The release shaped by running lll against thirty agents at a time, ten
tasks over, and fixing what they tripped on; then by moving the project's
own tracker onto lll.

### Breaking

- **Identity comes from the token.** The author of every write is the
  member the token names; a `me` that names someone else is refused with
  both names. A superuser token names nobody, so `me` attributes there as
  before. Fleets mint one token per member (`lll token create NAME`).
- **Anonymous record requests get a 401.** PocketBase applied rules as
  filters, so a request with no token read as an empty board. Rules are
  unchanged; the refusal comes before the lookup and leaks nothing.
- **`issue start` sets the state and nothing else.** The git branch switch
  and the work-site stamp are behind `--branch`. It used to switch whatever
  checkout it was run from.
- **A claim owns the assignee.** `issue update --assignee NAME` on an issue
  someone else holds is refused naming the holder; `--assignee none`
  releases the claim as well. Claiming what you already hold succeeds.
- **The silent re-mint is the board's alone.** A CLI holding the admin pair
  no longer upgrades a dead member token to the superuser under the covers;
  it gets the honest refusal.

### Added

- `lll search TEXT`: full-text search over issues, comments and docs, ranked
  (BM25 with a title weight, phrase and all-terms bonuses, a key pins its
  record), grouped by what you would open, each hit with the matching line
  and its neighbours under the source it came from. A local corpus cache
  under `~/.cache/lll/` with delta sync keeps warm queries under a second;
  `--refresh` refills. The board's `/search` runs the same engine.
- Dependencies: `issue block KEY BLOCKER`, `issue unblock`, "Blocked by" and
  "Blocks" in `issue view`, `issue list --ready` (open, every blocker done)
  and `--blocked`. Self-blocks and cycles are refused.
- `issue watch KEY --until TEXT` blocks until a comment containing TEXT
  arrives, at once if it is already there; `--timeout N` gives up.
- Comments are numbered; `issue comment edit KEY N -b` and `issue comment
  delete KEY N` change your own, `--force` anyone's.
- `issue update --assignee none` clears an assignee.
- `finding view SLUG`, `finding read`, `finding new`, `finding list --search`
  and `-p PATH`; `doc read`, `doc show`, `doc create`; `issue new`.
- `--help` on every verb, and it never runs the verb.
- Every verb dispatches through one command table per noun; help,
  completions and parsing come from the same declaration.
- A flag takes any number of aliases. Added across the fleet runs: `read`
  and `show` for `view`, `--assign`, `-t`/`--title` and `-d` both ways,
  `--body`/`-m`/`--message`, `--query`, `--path`.
- Bare arguments: `issue create "title"`, `member add name`,
  `issue comment KEY "body"`.
- `lll token create --duration`; an expired token is named as expired from
  its own payload, with the re-mint.
- `whoami` works for agent tokens and names a `me` mismatch.
- The board proxies `/api/` and `/_/` on its own port: one address.
- A landing page at `docs/`; a DX review harness; `scripts/import_sidecar.py`.

### Changed

- Error messages name the fix: an unknown flag prints the verb's flag
  table; a plural noun (`lll issues list`) names the singular with the verb
  kept; a flat verb (`lll comment`) names its noun; a sub-verb where the ID
  goes (`comment add KEY`) is told the ID comes first; `--project TEAM` is
  told the team scopes the command; guessed verbs (`assign`, `move`,
  `edit`, `find`) are pointed at the verb.
- Writes say what they did: `Commented on KEY as NAME`, `Updated KEY:
  state=todo, priority=3`, `Claimed KEY for NAME (already yours since …)`.
- The unknown-team error names the file or env var the key came from.
- `issue view` caps the area-matched related findings at five, linked ones
  first and always shown; `--raw` keeps the whole list.
- The board heals its own stale token instead of announcing its team is
  missing.
- The gate never deletes the tracked `.lll.toml`.

### Removed

- The `.private` sidecar tracker. The project's tasks, findings and
  decisions live on its own lll board; the sidecar is archived read-only.

## [0.1.0] - 2026-09-03

First release: issues, teams, members, projects, labels, docs, findings,
claims, the web board over embedded PocketBase, `lll up`, realtime
`watch`, Fly deployment.

[0.6.0]: https://github.com/escherize/lll/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/escherize/lll/compare/v0.4.0...v0.5.0
[0.2.0]: https://github.com/escherize/lll/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/escherize/lll/releases/tag/v0.1.0
