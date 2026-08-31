# lll

A Linear-style issue tracker in one binary: CLI-first, with a realtime web
board. Self-hosted — PocketBase runs embedded in-process, no SaaS.
Written in [Lisette](https://github.com/ivov/lisette), which compiles to Go.

- Teams, `ENG-123` identifiers, states, priorities, projects, labels,
  markdown comments.
- `--json` on reads and NDJSON event streams — built for scripts and coding
  agents as much as for humans.
- `lll up` starts everything: embedded PocketBase + the web board.

## Quickstart

```sh
curl -LsSf https://github.com/ivov/lisette/releases/latest/download/lisette-installer.sh | sh
mise install && mise run dev   # build, then PocketBase (:8090) + web board (:8100)
```

That is everything — PocketBase is embedded in the binary. `lis` (the Lisette
toolchain) is the one tool mise cannot install; the rest (go, jq) it pins.
Taken ports auto-increment; Ctrl-C stops everything; markup/CSS edits need a
rebuild (`mise run dev` does it).

Then, in another shell — with mise activated, `lll` anywhere under the
checkout is the binary you just built:

```sh
lll attach                               # writes .lll.toml; commit it
lll issue create -t "First issue" --priority 2
lll issue list
open http://127.0.0.1:8100               # or: lll board -w
```

## Attaching a repo

`lll attach` creates a team and writes one line — `team = "KEY"` — to
`.lll.toml` at the repo root. Commit that file. The key defaults to the repo
directory name; `-k KEY` overrides it.

That is the whole attachment, because the two halves of the config live in
different places:

| Half | Where | Keys |
|---|---|---|
| Which tracker | the repo's committed `.lll.toml` | `team` |
| How to reach it | `~/.config/lll/lll.toml`, once per machine | `url`, `me` |

So attaching a new repo on a machine already set up is `lll attach`, and an
already-attached repo on a new machine is `git clone` — no lll step at all.
Every worktree of that checkout is attached the moment it exists.

## Configuration

Precedence: env vars > the repo's `.lll.toml` > `~/.config/lll/lll.toml`. The
files **layer**: each supplies the keys it names, so a repo file carrying
`team` alone still gets `url` and `me` from the machine's. `.lll.toml` is
found by walking up from the working directory to the repo root — and no
higher, so a stray file above a checkout cannot capture it.

`lll config --list` prints every effective value and the file it came from,
after `git config --list --show-origin`:

```
file:/Users/you/.config/lll/lll.toml	url=http://127.0.0.1:8090
file:.lll.toml	team=ENG
unset	sort=
file:/Users/you/.config/lll/lll.toml	me=you
default	web_url=http://127.0.0.1:8100
```

| Env | TOML key | Meaning |
|---|---|---|
| `LLL_URL` | `url` | PocketBase base URL (default `http://127.0.0.1:8090`) |
| `LLL_TEAM` | `team` | Default team key; scopes `issue list`, required by `issue create` |
| `LLL_SORT` | `sort` | Default sort: `created`, `updated`, `priority`, `number`; `-` prefix descends |
| `LLL_WEB_URL` | `web_url` | Web board base URL for `board`, `issue url`, `view -w` |
| — | `me` | Your member name; authors your comments and receives assignments |
| `LLL_TOKEN` | `token` | PocketBase auth token sent as `Authorization: Bearer` on every request. A secret: `lll login` writes it to the home config, `lll token create` mints agent tokens — never the repo's .lll.toml |
| `LLL_ADMIN_EMAIL` / `LLL_ADMIN_PASSWORD` | — | PocketBase superuser for `lll up` and `lll token create` (a logged default is used when unset) |

`lll config init` writes a commented template. On its first boot `lll up`
guesses `me` from `$USER`, writes it to `~/.config/lll/lll.toml` and seeds a
matching member, so assignment works immediately — no prompt. It writes the
home config, never the repo's, because the repo's file is committed. That
guess is wrong on a shared machine: `lll config set me <name>` fixes it, in
the same file.

## CLI tour

Every command has `--help`; every read takes `--json`.

```sh
lll issue create -t "Fix login" --priority 1 --assignee bryan --label bug
lll issue list --state todo --sort -updated
lll issue start ENG-12        # state -> in-progress, creates branch eng-12-fix-login
lll issue claim ENG-12        # take it exclusively; non-zero if someone holds it
lll issue release ENG-12      # give it back
lll issue view                # ID inferred from the git branch
lll issue comment -b "done in abc123"   # markdown; renders on the web board
lll issue close
lll issue pr                  # gh pr create titled "ENG-12: Fix login"

lll watch --state in-review   # live NDJSON-able event stream for a query
lll issue watch ENG-12        # one issue + its comments, until Ctrl-C

lll team|member|project|label list      # the other nouns: list/create/view/add
lll attach                    # point this repo at a team, once
lll config --list             # every value and the file it came from
lll login                     # as a member; the token goes to the home config
lll token create bryan        # a static agent token (superuser only), printed once
lll logout                    # clear the stored token
lll board -w                  # open the web board
lll completions zsh           # bash, zsh, fish
```

Issue IDs resolve: explicit arg, else the current git branch
(`eng-12-fix-login` -> `ENG-12`).

## Web board

Server-rendered board at `/`, issue pages at `/issue/KEY-123`, search at
`/search?q=…`.

- Realtime: changes from the CLI, other browsers, or the board itself appear
  everywhere without reload, over one SSE connection per page.
- Drag-and-drop between state columns and reorder within them.
- Live search, filter chips (assignee/label/priority/state), hideable columns.
- `/search?q=…` searches the database, not the rendered board, so the query is
  a shareable URL and `curl` gets the same answer the browser does.
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

`scripts/import_sidecar.py` imports this project's own `.private` sidecar
tracker (Backlog.md tasks + wiki/decisions/findings) into an lll instance as
team `LLL`. It is idempotent — every record carries an `Origin: sidecar ...`
body line and a re-run creates nothing that is already there — so re-running
it is safe and is how new sidecar records get picked up:

```sh
LLL_TOKEN=<token> python3 scripts/import_sidecar.py --url <instance-url>
```

`--url` is required (it never guesses an instance) and the token comes from
`lll token create` (superuser-gated). Worklogs are not imported; the sidecar
stays their archive.

Layout:

- `src/` — Lisette source: `main.lis` dispatch, `commands/` one file per
  noun, `pb/` REST client, `realtime/` SSE client, `query/` filter builder,
  `config/`, `display/`, `gitctx/`, `models/`.
- `pb/` — PocketBase schema as code: `pb_migrations/`, applied on start.
- `gopb/` — tiny Go module embedding PocketBase behind one `Serve` function.
- `web/` — `templates/` (html/template) and `static/` (plain CSS), compiled
  into the binary via a `//go:embed` in `web/embed.go`: edits need a rebuild.

## Architecture

```
lll CLI ── REST ──> PocketBase (embedded; sqlite + migrations)
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
