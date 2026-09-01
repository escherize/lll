# lll

A Linear-style issue tracker in one binary: CLI-first, with a realtime web
board. Self-hosted — PocketBase runs embedded in-process, no SaaS.
Written in [Lisette](https://github.com/ivov/lisette), which compiles to Go.

- Teams, `ENG-123` identifiers, states, priorities, projects, labels,
  markdown comments.
- `--json` on reads and NDJSON event streams — built for scripts and coding
  agents as much as for humans.
- `lll up` starts everything: embedded PocketBase + the web board.

## Install

Prebuilt binaries — no checkout, no toolchain:

```sh
mkdir -p ~/bin && curl -LsSf -o ~/bin/lll \
  https://github.com/escherize/lll/releases/latest/download/lll-darwin-arm64 \
  && chmod +x ~/bin/lll
```

Linux: swap in `lll-linux-amd64` or `lll-linux-arm64`. Binaries are attached
to [GitHub releases](https://github.com/escherize/lll/releases) by the
release workflow on every `v*` tag; `lll --version` names the release. This
covers every client command; `lll up` (the server) reads `pb/` from disk and
still wants a checkout.

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

## Setup, exactly

Four actors, each configured once, none written twice:

| Actor | Once | Writes |
|---|---|---|
| Server | `lll up` with `LLL_ADMIN_*`, `LLL_TEAM`, `LLL_BIND`, `LLL_BOARD_TOKEN` in env (Fly: secrets) | nothing on disk but the database |
| Your machine (human path) | `lll login --url https://your-host:8091` — prompts for email + password | `url`, `token`, and `me` (when unset) in the home config |
| Each repo or directory | `lll attach`, commit the file if it is a repo | `team = "KEY"` in `.lll.toml`, at the repo root or in the working directory |
| Each agent (agent path) | superuser mints `lll token create <name>` | nothing — `LLL_TOKEN` (+ `LLL_URL`) in its env |

Humans log in with email + password; agents ride minted tokens. A new or
imported member has a random password nobody knows, so a superuser first runs
`lll member set-password NAME --email their@email` — then their `lll login
--url ...` works. On a local `lll up`, plain `lll login` (the url default is
`http://127.0.0.1:8090`) is enough.

Inviting someone is those two halves in one command: `lll member invite NAME
--email their@email` creates the member, generates a temporary password, and
prints the exact lines they run. The password is shown once and stored
nowhere, so send it before you close the terminal.

Clones and git worktrees of an attached repo need no step at all; env beats
files, repo file beats home file, and each key resolves independently
(`lll config --list` shows every winner and its origin).

## Attaching a repo, or any directory

`lll attach` creates a team and writes one line — `team = "KEY"` — to
`.lll.toml`. Inside a git repository that file goes at the repo root; commit
it. Outside one it goes in the working directory, and every subdirectory
inherits it — a scratch project needs no `git init` to be tracked. The key
defaults to the directory name; `-k KEY` overrides it.

That is the whole attachment, because the two halves of the config live in
different places:

| Half | Where | Keys |
|---|---|---|
| Which tracker | the directory's `.lll.toml`, committed when it is a repo | `team` |
| How to reach it | `~/.config/lll/lll.toml`, once per machine | `url`, `me` |

So attaching a new repo on a machine already set up is `lll attach`, and an
already-attached repo on a new machine is `git clone` — no lll step at all.
Every worktree of that checkout is attached the moment it exists.

### The side-project loop

A team is cheap, so give every side project its own and archive it when the
work is done. A repo is not required — a plain directory of notes attaches the
same way, and its subdirectories inherit the team:

```sh
lll attach                    # once, repo or plain dir: creates KEY, writes .lll.toml
lll issue create -t "..."     # work, tracked under KEY-1, KEY-2, ...
lll team archive KEY          # done: leaves team lists and the board rail
```

Archiving hides, never deletes: `/t/KEY/` still renders (with an "archived"
banner) and every issue and comment stays readable. New writes refuse —
`lll issue create`, `lll attach`, and the archived board's editors all answer
with the fix — and `lll team unarchive KEY` brings the team back whole.
`lll team list --archived` shows what is parked.

## Configuration

Precedence: env vars > the repo's `.lll.toml` > `~/.config/lll/lll.toml`. The
files **layer**: each supplies the keys it names, so a repo file carrying
`team` alone still gets `url` and `me` from the machine's. `.lll.toml` is
found by walking up from the working directory. Inside a repo the walk stops
at the repo root — and no higher, so a stray file above a checkout cannot
capture it. Outside any repo it stops at the first of: the file, a directory
holding `.git` (someone's checkout is not this directory's tracker), or your
home directory **exclusive** — a `.lll.toml` sitting directly in `$HOME` is
never read, because `~/.config/lll/lll.toml` is how you set machine-wide
defaults on purpose.

`lll config --list` prints every effective value and the file it came from,
after `git config --list --show-origin`:

```
file:/Users/you/.config/lll/lll.toml	url=http://127.0.0.1:8090
file:.lll.toml	team=ENG
unset	sort=
file:/Users/you/.config/lll/lll.toml	me=you
default	web_url=http://127.0.0.1:8100
```

A hosted instance answers on two ports, and `url` wants the API one. The board
rides 443 (`https://your-host`), the API rides `:8091` — so
`url = "https://your-host"` reaches the board, which 404s every API call.
`lll config check` asks the configured url whether it is a PocketBase API and
answers in one line.

Client settings — what every `lll` command reads:

| Env | TOML key | Meaning |
|---|---|---|
| `LLL_URL` | `url` | PocketBase **API** base URL (default `http://127.0.0.1:8090`; hosted, `https://your-host:8091` — not the board's bare host) |
| `LLL_TEAM` | `team` | Default team key; scopes `issue list`, required by `issue create` |
| `LLL_ME` | `me` | Your member name; authors your comments and receives assignments |
| `LLL_SORT` | `sort` | Default sort: `created`, `updated`, `priority`, `number`; `-` prefix descends |
| `LLL_WEB_URL` | `web_url` | Web board base URL for `board`, `issue url`, `view -w`. Unset, it derives from `url`: `https://<url-host>` (port dropped — the hosted board rides 443) when the url is non-local, else `http://127.0.0.1:8100` |
| `LLL_TOKEN` | `token` | PocketBase auth token sent as `Authorization: Bearer` on every request. A secret: `lll login` writes it to the home config, `lll token create` mints agent tokens — never the repo's .lll.toml |

Server settings — read only by `lll up` (env only, no TOML key; on a host,
set them as secrets):

| Env | Meaning |
|---|---|
| `LLL_ADMIN_EMAIL` / `LLL_ADMIN_PASSWORD` | PocketBase superuser, upserted at boot (a logged default is used when unset) |
| `LLL_BIND` | Bind address for both ports (default `127.0.0.1`; `0.0.0.0` when hosting) |
| `LLL_BOARD_TOKEN` | Pins the web board's access token; unset, each boot mints and prints a fresh one |

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
lll team archive KEY          # park a finished team; unarchive brings it back
lll attach                    # point this repo at a team, once
lll config --list             # every value and the file it came from
lll config check              # does the configured url answer as a PocketBase API?
lll login --url https://host:8091   # one-command machine setup: auth + persist url/token/me
lll login                     # as a member, against the configured url
lll member invite NAME --email e@x.com  # add a colleague + temp password, in one
lll member set-password NAME --email e@x.com  # superuser gives a member credentials
lll token create bryan        # a one-year agent token (superuser only), printed once
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
