# Changelog

All notable changes to lll. The format follows Keep a Changelog; versions
follow SemVer, with 0.x meaning the CLI surface can still move between
minors. Issue keys are on the project's own board (`lll issue view KEY`).

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

[0.2.0]: https://github.com/escherize/lll/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/escherize/lll/releases/tag/v0.1.0
