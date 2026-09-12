# Changelog

All notable changes to lll. The format follows Keep a Changelog; versions
follow SemVer, with 0.x meaning the CLI surface can still move between
minors. Issue keys are on the project's own board (`lll issue view KEY`).

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
