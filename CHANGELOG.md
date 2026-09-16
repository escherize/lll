# Changelog

All notable changes to lll. The format follows Keep a Changelog; versions
follow SemVer, with 0.x meaning the CLI surface can still move between
minors. Issue keys are on the project's own board (`lll issue view KEY`).

## [0.3.0] - 2026-09-15

The release shaped by lll running its own board with several agents working
it at once. That pressure asked for surfaces an agent needs rather than a
person — one command that says what to work on next, identities that are
not people, events that leave the process, and the operating instructions
carried inside the binary. It also put real text through the board, which
is how two panics were found.

### Breaking

- **Repeated `--state` and `--label` mean the union.** `--state todo
  --state in-progress` returns both; it used to silently keep the last one
  and drop the rest. A flag repeated where repetition means nothing is now
  refused rather than quietly ignored.
- **`me` no longer mints members.** A `me` naming nobody used to create
  that member on the spot, which is how a board accumulates identities
  nobody chose. It is now an error that names the fix.
- **Deleting a member requires admin authority.** Migration
  `1789200000_member_delete_admin.js` sets `members.deleteRule = null`;
  deletion is refused for ordinary tokens and checked against assignments
  and comment authorship first.
- **Claims, releases and assignment edits are one server transaction.**
  Authenticated endpoints commit the claim and every accompanying issue
  field together, against an observed claim id. **Deploy the server before
  distributing the client**: an older server refuses with an explicit
  upgrade instruction rather than falling back to unsafe two-request
  writes.
- **`lll up` serves one address.** The separate `:8091` API service is
  retired; the board proxies `/api/` and `/_/` on its own port.

### Added

- `lll issue next`: the one issue to work now — ready and unclaimed, then
  priority, then oldest, then most-unblocking. `--claim` takes it, so an
  agent starts work in one command. `lll watch --ready` streams the same
  agenda as it changes.
- `lll webhook add|list|remove`: the server POSTs issue events to your
  URLs, with bounded retries and backoff for deliveries that fail.
- `lll api METHOD PATH`: raw authenticated passthrough to the board's
  PocketBase API, with `--schema` printing the collection and field
  reference — an escape hatch that does not require finding the admin UI.
- `lll bot NAME`: an agent identity in one command, member and token,
  printed once. Bot members are a distinct kind that cannot log in, are
  owned by a person, badged on the board, and rotatable.
- `lll import github OWNER/REPO`: brings a GitHub backlog in through `gh` —
  title, body, labels and state, each issue carrying its `gh#N` ref.
  Re-importing skips what it already brought.
- `lll skill list` / `lll skill get NAME`: the agent operating instructions
  ship inside the binary, so an agent working from another repo can read
  them without this checkout.
- Attachments: `issue attach KEY FILE`, `issue unattach`, `issue cat`, and
  upload from the board. Files are protected, appended rather than
  replaced, and refused to anonymous readers.
- Surgical description edits: `issue update --description-replace-old/-new`
  and `--description-append`, plus `--if-unchanged-since STAMP` so a
  concurrent edit is refused instead of overwritten.
- Homebrew distribution: `brew install escherize/lll/lll`, with the tap
  formula rendered and pushed by the release workflow.
- Provenance: an issue records who created it and the host, path, branch
  and commit it was created from, shown on the board and in exports.
- `lll issue pr` records `gh#N` back on the issue once `gh` confirms the
  PR, and adopts the existing PR when the branch already has one.
- `doc list --search`, `doc link`/`unlink`, `finding list --limit`, a
  positional finding slug, `-l` for `--label`, `issue list --page N` and
  sorting by title.
- `lll login --url` discovers and persists the board's advertised endpoint
  through `/.well-known/lll`; an older server falls back to manual
  configuration.
- `LLL_CONFIG_HOME` chooses the config root, for harnesses that cannot set
  `HOME`.
- The board shows live claims and can claim and release.
- Docs have an address: `/t/TEAM/doc/SLUG` renders a decision, finding, PRD
  or wiki page through the same markdown renderer as issue descriptions,
  with the properties `doc view` prints beside it. Read-only for now — the
  point is that a reason can be linked to, from an issue or a review.

### Changed

- The board renders every issue in the team. Past roughly 200 it used to
  truncate silently; pagination, ordering and live updates now hold across
  a full board.
- The saved column view rides a cookie the server reads on first paint, so
  the board no longer flashes the wrong columns before correcting itself.
  The webfont is cached rather than refetched, for the same reason.
- The 401 board gate has a field to paste the token into, instead of only
  explaining where the token lives.
- Issue table columns are measured in grapheme display cells, so emoji and
  wide characters line up.
- Errors say what to do: rejected edits restore the authoritative values,
  board write failures name themselves instead of vanishing, and creation
  errors appear inside the dialog that caused them.
- `cmd+enter` sends a comment, and a successful send clears the box.
- The e2e suites run from outside the checkout, so a gate no longer mutates
  the tree another agent is reading — including the tracked `.lll.toml`.

### Fixed

- **An issue description killed the board.** The hover preview capped on
  byte length and sliced on rune indices, so a description of ~100 accented
  characters or 60 emoji panicked a goroutine outside any HTTP handler and
  took the server process down.
- **`watch --json` panicked on any multi-byte record**, for the same
  byte-versus-rune reason — one emoji anywhere in the payload ended the
  stream.
- Related findings and comments no longer draw on top of each other on the
  issue page: both carried the same grid area, so a named cell held two
  sections at once. The DOM was right all along; only geometry could see it.
- The last hidden column can be shown again; unhiding it no longer restores
  the hide from the saved view.
- An expired boot token is re-minted the way a rejected one already was.
- `mise run scratch` and `mise run seed` read their own isolated config
  rather than the developer's real token on machines that export
  `XDG_CONFIG_HOME`, which moving `HOME` alone stopped being enough for.
- `issue list --sort priority` leads with urgent and leaves the
  unprioritised last. PocketBase sorts on the stored number and `none` is
  0, so the ascending fetch led with issues nobody had triaged and buried
  the urgent ones — and because the ordering decided which page you got,
  urgent work past `--limit` fell off the list entirely rather than merely
  sorting late.
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
