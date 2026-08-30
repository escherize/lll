# lll

A Linear-style issue tracker in one binary: CLI-first, with a realtime web
board. Self-hosted — PocketBase runs embedded in-process, no SaaS, no auth.
Written in [Lisette](https://github.com/ivov/lisette), which compiles to Go.

- Teams, `ENG-123` identifiers, states, priorities, projects, labels,
  markdown comments.
- `--json` on reads and NDJSON event streams — built for scripts and coding
  agents as much as for humans.
- `lll up` starts everything: embedded PocketBase + the web board.

## Quickstart

No separate PocketBase install — it is embedded, and the test suite drives it
through `lll up`. Go 1.27 is pinned in `mise.toml`; `lis`, the Lisette
toolchain, ships as a GitHub release rather than a mise plugin, so it is the
one tool you install yourself:

```sh
curl -LsSf https://github.com/ivov/lisette/releases/latest/download/lisette-installer.sh | sh
mise install             # go, jq
mise run dev             # build, then PocketBase (:8090) + web board (:8100)
```

`mise run dev` builds first and runs from the checkout root for you, from any
subdirectory. The board reads `web/templates/` and `web/static/` from disk;
taken ports auto-increment; Ctrl-C stops everything.

Then, in another shell — with mise activated, `lll` anywhere under the
checkout is the binary you just built, so there is nothing to install or
symlink:

```sh
lll team create -k ENG -n "Engineering"
lll config init                          # writes .lll.toml; set team = "ENG"
lll issue create -t "First issue" --priority 2
lll issue list
open http://127.0.0.1:8100               # or: lll board -w
```

## Configuration

Precedence: env vars > `./.lll.toml` > `~/.config/lll/lll.toml`. The first
file found is used whole; env vars override individual fields.

| Env | TOML key | Meaning |
|---|---|---|
| `LLL_URL` | `url` | PocketBase base URL (default `http://127.0.0.1:8090`) |
| `LLL_TEAM` | `team` | Default team key; scopes `issue list`, required by `issue create` |
| `LLL_SORT` | `sort` | Default sort: `created`, `updated`, `priority`, `number`; `-` prefix descends |
| `LLL_WEB_URL` | `web_url` | Web board base URL for `board`, `issue url`, `view -w` |
| — | `me` | Your member name; authors your comments |
| `LLL_ADMIN_EMAIL` / `LLL_ADMIN_PASSWORD` | — | PocketBase superuser for `lll up` (a logged default is used when unset) |

`lll config init` writes a commented template.

## CLI tour

Every command has `--help`; every read takes `--json`.

```sh
lll issue create -t "Fix login" --priority 1 --assignee bryan --label bug
lll issue list --state todo --sort -updated
lll issue start ENG-12        # state -> in-progress, creates branch eng-12-fix-login
lll issue view                # ID inferred from the git branch
lll issue comment -b "done in abc123"   # markdown; renders on the web board
lll issue close
lll issue pr                  # gh pr create titled "ENG-12: Fix login"

lll watch --state in-review   # live NDJSON-able event stream for a query
lll issue watch ENG-12        # one issue + its comments, until Ctrl-C

lll team|member|project|label list      # the other nouns: list/create/view/add
lll board -w                  # open the web board
lll completions zsh           # bash, zsh, fish
```

Issue IDs resolve: explicit arg, else the current git branch
(`eng-12-fix-login` -> `ENG-12`).

## Web board

Server-rendered board at `/`, issue pages at `/issue/KEY-123`.

- Realtime: changes from the CLI, other browsers, or the board itself appear
  everywhere without reload, over one SSE connection per page.
- Drag-and-drop between state columns and reorder within them.
- Live search, filter chips (assignee/label/priority/state), hideable columns.
- Issue pages: inline field editing, markdown comments.

## Development

```sh
lis check          # type check
lis test           # unit tests
mise run build     # binary at target/.lisette/bin/lll
mise run test      # unit tests
mise run e2e       # full e2e: CLI + watch + web board + lll up
mise run gate      # all three -- what a change must pass before it lands
```

`scripts/e2e.sh` runs an ephemeral PocketBase on a random port via `lll up`
itself — no external binary — plus `jq` and `python3`. It never touches your
data.

Layout:

- `src/` — Lisette source: `main.lis` dispatch, `commands/` one file per
  noun, `pb/` REST client, `realtime/` SSE client, `query/` filter builder,
  `config/`, `display/`, `gitctx/`, `models/`.
- `pb/` — PocketBase schema as code: `pb_migrations/` (applied on start) and
  `pb_hooks/main.pb.js` (per-team issue numbering).
- `gopb/` — tiny Go module embedding PocketBase behind one `Serve` function.
- `web/` — `templates/` (html/template) and `static/` (plain CSS), read from
  disk on every request: edit and refresh, no rebuild.

## Architecture

```
lll CLI ── REST ──> PocketBase (embedded; sqlite + migrations + hooks)
                        │ realtime SSE (JSON records)
browser <── HTML/SSE ── lll up web board (Datastar fragment morphing)
```

One Lisette codebase compiled to Go. The CLI talks to PocketBase's REST API
directly — no SDK. The board renders html/templates, holds one subscription
to PocketBase realtime, and pushes re-rendered fragments to every open page
over SSE; [Datastar](https://data-star.dev) morphs them into the DOM by
element id. `lll up` runs PocketBase in-process (see `gopb/`) and the board
in one process; it reuses an already-running PocketBase at `LLL_URL` instead
of starting its own.
