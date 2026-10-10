# lll

lll is a Linear-style issue tracker in one binary: a CLI with a realtime web
board. It is self-hosted, with PocketBase embedded in the process, and written
in [Lisette](https://github.com/ivov/lisette), which compiles to Go.

- Teams, `ENG-123` identifiers, states, priorities, projects, labels and
  markdown comments.
- `--json` on reads and NDJSON event streams, for scripts and coding agents.
- `lll up` starts the server and the web board in one process.

![The lll board: six state columns with issue cards, a left rail, and a search
field](docs/board.png)

## Install

```sh
brew install escherize/lll/lll
```

Without Homebrew, download the binary (macOS on Apple silicon shown; on Linux
use `lll-linux-amd64` or `lll-linux-arm64`):

```sh
mkdir -p ~/bin && curl -LsSf -o ~/bin/lll \
  https://github.com/escherize/lll/releases/latest/download/lll-darwin-arm64 \
  && chmod +x ~/bin/lll
```

The binary includes PocketBase, the migrations and the web assets, so
`lll up` runs from any directory. Binaries are on
[GitHub releases](https://github.com/escherize/lll/releases).

## Quickstart

These commands run as written on a machine with only lll installed. A team is
one tracker; its key (`DEMO`) prefixes every issue id (`DEMO-1`).

```sh
mkdir my-board && cd my-board
LLL_TEAM=DEMO lll up           # lll server (:8090) + web board (:8100)
```

The first boot creates the team, writes `.lll.toml` here, and creates a
member named after `$USER`. A taken port moves to the next free one. If an lll
server already answers at the API url, `lll up` uses it, unless only a repo
`.lll.toml` chose that url: then it stops with exit 4. Ctrl-C stops
everything.

`lll up` prints one line per fact:

| Line | Says |
|---|---|
| `lll` | the installed version |
| `api` | the server's API url, with `(already running)` when it reused one |
| `team` | the team the board shows |
| `member` | the member the board and the CLI act as |
| `admin` | where the administrator credentials are kept, never the password |
| `cli` | whether it logged your CLI in, or why not |
| `board` | the board's url |
| `board  login` | a link that signs your browser in; `lll board` prints it again |

With `LLL_ADMIN_EMAIL` and `LLL_ADMIN_PASSWORD` unset, the first boot
generates a password for `admin@local.dev`. Read it with
`jq -r .password pb/pb_data/.lll-admin.json`. `lll up` logs the CLI in only
when your home config holds no token and names no other server; it never
replaces a login.

In a second shell, in `my-board`:

```sh
lll whoami          # your member, server and team
lll issue create -t "First issue" --priority 2 --emoji 🧪   # DEMO-1
lll issue claim DEMO-1
lll issue comment DEMO-1 -b "Started on it"
lll issue close DEMO-1   # done; closing also releases your claim
lll board -w        # opens the board, signed in
```

Attach a repository to the team (a new one stands in for yours):

```sh
git init -q ../my-repo && cd ../my-repo
lll attach --key DEMO     # writes team = "DEMO" to .lll.toml; commit that file
lll issue list            # DEMO-1, from inside the repo
```

Invite a colleague with a single-use link, or with an email and a temporary
password:

```sh
lll invite create --team DEMO    # prints <board>/join/<code>
lll member invite kim --email kim@example.com
```

The link leads to `/me`, which shows a CLI token for
`lll login --url <board> --token -`. A loopback board works only on this
machine; see [Share a board](#share-a-board-on-a-lan-or-tailscale).

`lll up --scratch` starts a throwaway board that ignores your home config and
every inherited `LLL_*` value. Its banner names the temporary data directory;
delete it when finished.

## Upgrade

Run `lll upgrade`. On a Homebrew install it runs `brew upgrade lll`;
otherwise it prints the download command.

Warning: before you upgrade a machine that runs `lll up`, stop it and back up
its data directory (`pb/pb_data`, or your `--pb-dir`). The new version
migrates the database on first start; the backup is the only way back.
Upgrade the server first, then its clients.

From 1.0, the surface in [docs/cli-contract.md](docs/cli-contract.md) follows
SemVer. [docs/upgrading-to-1.0.md](docs/upgrading-to-1.0.md) lists every
0.9 -> 1.0 change a script can observe; [CHANGELOG.md](CHANGELOG.md) has the
full history.

## Share a board on a LAN or Tailscale

<!-- example-check: skip: needs a LAN or Tailscale address -->
```sh
mkdir hack-board && cd hack-board
LLL_TEAM=HACK lll up --bind <your-LAN-or-Tailscale-IP>
# in a second terminal, in hack-board:
lll member passes --count 10 --prefix hack
```

`lll member passes` writes a private handoff file (mode 0600) with ten member
tokens, the API address and a board login link. Send each teammate only their
own block and the link. Browser edits act as the board process's identity,
not as each teammate. Do not publish the handoff file or the data directory.

The administration UI at the board's `/_/` returns 404 unless you start with
`lll up --admin-ui`.

## Setup

| Actor | Once | Writes |
|---|---|---|
| Server | `lll up` with server settings in env (on a host: secrets) | the database |
| Your machine | `lll login --url https://your-host --email you@example.com` | `url`, `token`, `team` in the home config |
| Each repo or directory | `lll attach` | `team` in `.lll.toml` |
| Each agent | a superuser runs `lll token create <name>` | nothing; `LLL_TOKEN` and `LLL_URL` in its env |

Humans log in with email and password; agents use minted tokens. Plain
`lll login` needs an existing member, and without `--url` it refuses (exit 2)
a url that only a repo `.lll.toml` or `LLL_URL` chose. The superuser is not
a member.

With the server's admin credentials, one command creates your member and logs
in:

<!-- example-check: skip: needs a hosted server and its administrator credentials -->
```sh
lll login --url https://your-host --email you@example.com \
  --create --password <pick one> \
  --admin-email <admin> --admin-password <admin pw>
```

`LLL_ADMIN_EMAIL` and `LLL_ADMIN_PASSWORD` can replace the admin flags only
when no token is configured. The member is named after your email's local
part unless you pass `--name`.

Without them, someone who has them invites you. The command prints a
temporary password, shown once, and the login line to send:

<!-- example-check: skip: needs a hosted server -->
```sh
lll member invite NAME --email their@email --url https://your-host
```

Add `--team KEY` (repeatable) to limit the member to those teams, and
`--read-only` to forbid writes. A member's bots never get more than their
owner. `lll member access NAME` shows and changes a member's scope.

## Attach a repo or any directory

`lll attach --key KEY` writes `team = "KEY"` to `.lll.toml`, creating team
KEY if it is missing. In a git repository the file goes at the repo root;
commit it, and every clone and worktree is attached. Outside a repository it
goes in the working directory, and subdirectories inherit it. Without
`--key`, a server with one team picks that team.

A plain directory works too. Archive a team when its work is done:

```sh
mkdir ../notes && cd ../notes
lll attach --key NOTES        # once: creates team NOTES, writes .lll.toml here
lll issue create -t "Outline the talk"   # NOTES-1
lll team archive NOTES        # done: leaves team lists and the board rail
lll team list --archived      # every team, the archived ones marked
lll team unarchive NOTES      # back, whole
```

An archived team stays readable at `/t/KEY/` and refuses new writes.

## Configuration

Settings resolve per key: environment variables, then the repo's
`.lll.toml`, then `~/.config/lll/lll.toml`. `.lll.toml` is found by walking
up from the working directory, stopping at the repo root, a directory holding
`.git`, or your home directory. A `.lll.toml` directly in `$HOME` is never
read. `lll config list` shows each value and its origin.

The home config's token is sent only to the url saved beside it. When a repo
`.lll.toml`, `LLL_URL` or `--url` names another server, commands that need
the token exit 6. `LLL_URL` and `LLL_TOKEN` set together work as a pair.

Scoped commands (`issue`, `project`, `label`, `doc`, `finding`, `watch`)
take `--team KEY` for one invocation. An explicit issue key targets its own
team.

Client settings:

| Env | TOML key | Meaning |
|---|---|---|
| `LLL_URL` | `url` | API base URL; default `http://127.0.0.1:8090`, hosted: the board's address |
| `LLL_TEAM` | `team` | default team key |
| `LLL_SORT` | `sort` | default sort: `created`, `updated`, `priority`, `number`, `title`; `-` descends |
| `LLL_WEB_URL` | `web_url` | board base URL for browser links |
| `LLL_TOKEN` | `token` | auth token; a secret, never in a repo's `.lll.toml` |

`lll board` never puts the board token into a link to a repo file's
`web_url`.

Server settings, environment only, read by `lll up`:

| Env | Meaning |
|---|---|
| `LLL_ADMIN_EMAIL` / `LLL_ADMIN_PASSWORD` | server administrator; set both or neither |
| `LLL_ALLOWED_ORIGINS` | extra browser origins that may read API responses; default none |
| `LLL_BIND` | bind address for both ports; default `127.0.0.1` |
| `LLL_BOARD_TOKEN` | pins the board's access token; default a new one each boot |

## CLI tour

In `my-repo` from the quickstart:

```sh
cd ../my-repo
lll label create bug
lll issue create -t "Fix login" --priority 1 --assignee "$USER" --label bug   # DEMO-2
lll issue list --state todo --sort -updated
lll issue branch-name DEMO-2  # print demo-2-fix-login; changes nothing
lll issue start DEMO-2        # state -> in-progress; leaves Git untouched
lll issue start DEMO-2 --branch  # also create or switch to that branch, and record the work site
lll issue claim DEMO-2        # take it exclusively; non-zero if someone holds it
lll issue view                # DEMO-2, inferred from the git branch
lll issue comment -b "done in abc123"   # markdown; renders on the web board
lll issue ref DEMO-2 gh#42    # append once; also retries a failed PR-reference save
lll issue release DEMO-2      # give it back
lll issue close               # DEMO-2 again, from the branch
```

These need a GitHub remote, or stream until Ctrl-C:

<!-- example-check: skip: needs a GitHub remote, or streams until Ctrl-C -->
```sh
lll issue pr                  # gh pr create titled "DEMO-2: Fix login"; records gh#N
lll watch --state in-review   # live NDJSON-able event stream for a query
lll issue watch DEMO-2        # one issue + its comments, until Ctrl-C
```

More nouns and helpers:

```sh
lll team list
lll team create SIDE -n "Side project"
lll team delete SIDE          # delete a team holding no issues (archive keeps ids working)
lll config list               # every value and the file it came from
lll config get team           # one effective value, for scripts
lll config check              # does the configured url answer as a PocketBase API?
lll whoami                    # which member, server and team you are acting as
lll member invite lee --email lee@example.com  # add a colleague + temp password, in one
lll bot create bot-myrepo     # a bot member you own, and an agent prompt with its token; refuses an existing bot
lll bot rotate bot-myrepo --env > agent.env  # a new token (the old one stops working), printing only the LLL_URL/LLL_TOKEN exports
lll board -w                  # open the web board
lll completions zsh           # bash, zsh, fish
```

These need a hosted server, a LAN board or administrator credentials:

<!-- example-check: skip: needs a hosted server, a LAN board or administrator credentials; logout would end the session -->
```sh
lll member set-password NAME --password <pw>  # superuser gives a member credentials
lll member delete NAME        # delete a member with nothing assigned (superuser only)
lll token create NAME         # a one-year agent token (superuser only), printed once
lll logout                    # clear the stored token
```

`lll issue attach ENG-1 ./shot.png` attaches a file (at most 20 per issue,
20 MiB each); `issue download` and `issue detach` take the filename.

Scripts rely on [docs/cli-contract.md](docs/cli-contract.md)
(`lll help contract`): exit codes, `--json` fields and permanent spellings.
Data goes to stdout and notices to stderr. Exit codes: 1 error, 2 usage, 3
not found, 4 refused, 5 nothing to do, 6 not authenticated. For `lll watch`
output, start from `lll watch --help`.

## Web board

The board is server-rendered: all teams at `/`, one team at `/t/KEY/`, issues
at `/issue/KEY-123`, docs at `/t/KEY/docs`, search at `/search?q=TEXT`, and
your login at `/me`. Changes appear in every open page without a reload.
Cards drag between state columns. `/search` queries the database, so a search
is a shareable URL; `lll search TEXT` runs the same engine.

## Development

Install the Lisette toolchain, then let mise provision Go and jq and start the
board:

```sh
curl -LsSf https://github.com/ivov/lisette/releases/latest/download/lisette-installer.sh | sh
mise install && mise run dev
```

```sh
mise run build     # binary at target/.lisette/bin/lll
mise run test      # unit tests
mise run e2e       # full e2e: CLI + watch + web board + lll up
mise run gate      # build, test and e2e: what a change must pass to land
```

Markup and CSS are embedded, so edits need a rebuild.
`mise run scratch -- --no-open` starts an isolated test board.

Layout: `src/` is the Lisette source (`commands/` has one file per noun),
`pb/` the PocketBase schema and migrations, `gopb/` the Go module embedding
PocketBase, and `web/` the templates and CSS.

More in docs/: [api.md](docs/api.md) (the board API),
[claim-transactions.md](docs/claim-transactions.md) (claim operations),
[ci-deployment.md](docs/ci-deployment.md) (CI and deployment),
[hosted-recovery.md](docs/hosted-recovery.md) (database recovery) and
[export-mirror.md](docs/export-mirror.md) (`lll export`).

## Architecture

```
lll CLI ── REST ──> PocketBase (embedded; sqlite + migrations)
                        │ realtime SSE (JSON records)
browser <── HTML/SSE ── lll up web board (Datastar fragment morphing)
```

The CLI calls PocketBase's REST API with no SDK. The board holds one
PocketBase realtime subscription and pushes re-rendered fragments to each
page over SSE; [Datastar](https://data-star.dev) morphs them into the DOM.

## License

MIT. See [LICENSE](LICENSE).
