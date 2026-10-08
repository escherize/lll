# lll

A Linear-style issue tracker in one binary: CLI-first, with a realtime web
board. Self-hosted: PocketBase runs embedded in-process, no SaaS.
Written in [Lisette](https://github.com/ivov/lisette), which compiles to Go.

- Teams, `ENG-123` identifiers, states, priorities, projects, labels,
  markdown comments.
- `--json` on reads and NDJSON event streams, built for scripts and coding
  agents as much as for humans.
- `lll up` starts everything: embedded PocketBase and the web board.

![The lll board: six state columns with issue cards, a left rail, and a search
field](docs/board.png)

The board above is `mise run seed`, which boots a throwaway instance with demo
issues on free ports. Nothing there is a mockup.

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

Binaries are attached to [GitHub releases](https://github.com/escherize/lll/releases)
on every `v*` tag; `lll --version` names the release. The binary includes
PocketBase, migrations and web assets: `lll up` runs from any directory
without a checkout or a toolchain.

## Quickstart

This sequence runs as written on a machine with lll installed and nothing
else set up. It starts a board on this machine, works one issue, attaches a
repository and invites a colleague.

A **team** is one tracker on the server: its key (`DEMO`) prefixes every issue
id (`DEMO-1`), and each repo or directory attaches to one team.

```sh
mkdir my-board && cd my-board
LLL_TEAM=DEMO lll up           # lll server (:8090) + web board (:8100)
```

The first boot creates the team, writes `.lll.toml` in this directory, and
creates a member named after `$USER`. Taken ports auto-increment; Ctrl-C stops
everything. The banner lines:

- `api` and `board`: the actual endpoints.
- `admin`: the administrator pair. With `LLL_ADMIN_EMAIL` and
  `LLL_ADMIN_PASSWORD` unset, a loopback boot uses `admin@local.dev` /
  `admin-local-123` and prints that pair. A pair from the environment is
  never printed.
- `cli`: when your home config holds no token and no other server's url,
  `lll up` logs the CLI in as your member. It never replaces an existing
  login; when one is in the way, the line says how to switch.
- `board  login`: a link that signs your browser in to the board. On this
  machine, `lll board` prints it again.

Keep that shell running. In a second shell, in `my-board`, the CLI is ready:

```sh
lll whoami          # your member, server and team
lll issue create -t "First issue" --priority 2 --emoji 🧪   # DEMO-1
lll issue claim DEMO-1
lll issue comment DEMO-1 -b "Started on it"
lll issue close DEMO-1   # done; closing also releases your claim
lll board -w        # opens the board, signed in
```

To track a repository on the same board, attach it to the team. Here a new
one stands in for yours:

```sh
git init -q ../my-repo && cd ../my-repo
lll attach --key DEMO     # writes team = "DEMO" to .lll.toml; commit that file
lll issue list            # DEMO-1, from inside the repo
```

`lll attach --key KEY` creates team KEY when it is missing. Plain `lll attach`
picks the board's only team when there is one.

To bring in another person, mint a single-use invite link:

```sh
lll invite create --team DEMO    # prints <board>/join/<code>
```

They open the link, pick a name, and land on their own page at `/me` (the
board's rail links to it as "Your login"). It links their boards and has a
"Show my CLI login" button. The token it shows logs a CLI in with
`lll login --url <board> --token -`. A link to a loopback board works only on
this machine; to reach teammates on other machines, use `--bind` (below). For
an email and password login instead:

```sh
lll member invite kim --email kim@example.com
```

It prints a temporary password and the `lll login --url <board> --email ...`
line to send. Logging in at the board's address saves both the board and its
API. The member replaces the password with
`lll member set-password kim --old-password <temporary>`.

From here:

- `lll --help` starts with the same sequence; every command takes `--help`.
- Each team's docs (wiki pages, findings, decisions) are listed on the board
  at `/t/KEY/docs`.
- Scripts can rely on the exit codes and `--json` fields in the
  [CLI contract](docs/cli-contract.md).
- `lll skill list` prints the agent instructions shipped in the binary;
  `lll bot create bot-NAME` gives an agent its own member and token.

For a throwaway board that ignores your existing hosted config and all inherited
`LLL_*` values, run `lll up --scratch` (`--local` is an alias). Its banner gives
the temporary data directory and the exact command for using its CLI. Delete
that directory when finished.

## Upgrade

Run `lll upgrade`. It runs `brew upgrade lll` for a Homebrew install and
prints the command for any other install. For a release download that command
downloads to a new file and then moves it into place: writing over a running
binary can kill the `lll up` and `lll watch` processes using it.

Before you upgrade a machine that runs `lll up`, stop it and back up its data
directory (`pb/pb_data`, or the `--pb-dir` you gave). The new version migrates
the database on its first start, and the backup is the way back. Upgrade the
server and its clients together. [CHANGELOG.md](CHANGELOG.md) lists what
changed, with a note on what to read before upgrading scripts.

## Share a board

To share a local board with hackathon teammates over a LAN or Tailscale, use
the address they can reach:

<!-- example-check: skip: needs a LAN or Tailscale address -->
```sh
mkdir hack-board && cd hack-board
LLL_TEAM=HACK lll up --bind <your-LAN-or-Tailscale-IP>
# in a second terminal, in hack-board:
lll member passes --count 10 --prefix hack
```

The second command prints the path to a private `0600` handoff file. It holds
ten distinct human member tokens, the team's API address, and a working board
login link. Send each teammate only their own block and the board link. Their
token authenticates CLI/API calls from another machine; the browser link admits
them to the board. Browser edits currently use the board process identity. The
board login token and random administrator credentials are stored privately
with the local board and survive a restart with the same data directory and
`--bind` address. Do not publish the handoff file or local data directory.

The administration UI at the board's `/_/` path returns 404 by default.
Start with `lll up --admin-ui` to enable it and print its address; sign in with
the server administrator credentials. This controls the board proxy; the
separate API listener retains its own administration routes.

## Build from source

Install the Lisette toolchain and let mise provision Go and jq, then build and
start the board from a checkout:

```sh
curl -LsSf https://github.com/ivov/lisette/releases/latest/download/lisette-installer.sh | sh
mise install && mise run dev
```

With mise activated, `lll` under the checkout is the binary you just built.
Markup/CSS edits need a rebuild (`mise run dev` does it). For an isolated test
board alongside other servers, use `mise run scratch -- --no-open`.

## Setup, exactly

Four actors, each configured once, none written twice:

| Actor | Once | Writes |
|---|---|---|
| Server | `lll up` with `LLL_ADMIN_*`, `LLL_TEAM`, `LLL_BIND`, `LLL_BOARD_TOKEN` in env (Fly: secrets) | nothing on disk but the database |
| Your machine (human path) | `lll login --url https://your-host --email you@example.com`, which prompts for the password unless you pass `--password` | `url`, `token` and `team` (each when unset) in the home config |
| Each repo or directory | `lll attach`, commit the file if it is a repo | `team = "KEY"` in `.lll.toml`, at the repo root or in the working directory |
| Each agent (agent path) | superuser mints `lll token create <name>` | nothing; `LLL_TOKEN` and `LLL_URL` in its env |

Humans log in with email + password; agents ride minted tokens. A member has
to exist before plain `lll login` will work; `lll login --create` creates one
using administrator credentials. The superuser is not a member, so its
credentials alone do not establish a member session.

**If you hold the server's admin credentials, setting up your own machine is
one command:**

<!-- example-check: skip: needs a hosted server and its administrator credentials -->
```sh
lll login --url https://your-host --email you@example.com \
  --create --password <pick one> \
  --admin-email <admin> --admin-password <admin pw>
```

`--create` makes the member and logs into it in the same call. The admin
credentials can ride `LLL_ADMIN_EMAIL`/`LLL_ADMIN_PASSWORD` instead of the
flags, but only when no token is configured: a configured token always
outranks them, and only the flags act as the administrator over it. The member is named after the part of your email before `@`, unless `--name`
says otherwise. If the server has exactly one team, `login` settles that too, so
`lll issue create "a title"` works immediately.

**If somebody else deployed it**, they run one command and send you what it
prints:

<!-- example-check: skip: needs a hosted server -->
```sh
lll member invite NAME --email their@email --url https://your-host
```

That creates the member, generates a temporary password, and prints the exact
lines they run. Their `lll login --url` names the board's address when the
inviting machine knows it (`web_url`, which `lll up` and `lll login` save), so
their login finds both the board and its API; `--url` names another. The password is shown once and stored nowhere, so send it
before you close the terminal. A member who has lost their password gets a new
one from `lll member set-password NAME --password <pw>` (superuser only:
pass `--admin-email` and `--admin-password`, or set them in the environment).

To give someone one team and nothing else, add `--team KEY` (repeat it for more
teams). Their token then sees only those teams' issues, comments, docs and
claims, and they cannot widen their own scope or create members. Add
`--read-only` for someone who should look but not change anything. A
read-write member can still run `lll bot create bot-NAME` for its own agents: the bot
starts with the member's teams and mode and never gets more than its owner
has, so narrowing the member narrows its bots too. Run on the
machine serving the board, the invite also prints a view-only web board link
per team. They make changes through the CLI, as themselves.

`lll member access NAME` shows what a member can see; the same command changes
it: `--team KEY`, `--add-team KEY`, `--remove-team KEY`, `--all-teams`,
`--no-teams` (revoke, keeping what they wrote), `--read-only`, `--read-write`.

On a local `lll up`, plain `lll login` (the url default is
`http://127.0.0.1:8090`) is enough.

Clones and git worktrees of an attached repo need no step at all; env beats
files, repo file beats home file, and each key resolves independently
(`lll config list` shows every winner and its origin).

## Attaching a repo, or any directory

`lll attach --key KEY` writes one line, `team = "KEY"`, to `.lll.toml`, and
creates team KEY on the server when it is missing. Inside a git repository
that file goes at the repo root; commit it. Outside one it goes in the working
directory, and every subdirectory inherits it. A scratch project needs no
`git init` to be tracked. Without `--key`, the server decides: one team means
that team, several means you say which.

That is the whole attachment. The two halves of the config live in different
places:

| Half | Where | Keys |
|---|---|---|
| Which tracker | the directory's `.lll.toml`, committed when it is a repo | `team` |
| How to reach it | `~/.config/lll/lll.toml`, once per machine | `url`, `token` |

So attaching a new repo on a machine already set up is `lll attach`, and an
already-attached repo on a new machine is `git clone`, with no lll step at all.
Every worktree of that checkout is attached the moment it exists.

### The side-project loop

A team is cheap, so give every side project its own and archive it when the
work is done. A repo is not required. A plain directory of notes attaches the
same way, and its subdirectories inherit the team:

```sh
mkdir ../notes && cd ../notes
lll attach --key NOTES        # once: creates team NOTES, writes .lll.toml here
lll issue create -t "Outline the talk"   # NOTES-1
lll team archive NOTES        # done: leaves team lists and the board rail
lll team list --archived      # every team, the archived ones marked
lll team unarchive NOTES      # back, whole
```

Archiving hides, never deletes: `/t/KEY/` still renders (with an "archived"
banner) and every issue and comment stays readable. New writes refuse: `lll issue create`, `lll attach`, and the archived board's
editors all answer with the fix. `lll team unarchive KEY` brings the team back
whole.

## Configuration

Scoped commands (`issue`, `project`, `label`, `doc`, `finding`, and `watch`)
accept `--team KEY` for a single invocation, for example
`lll issue list --team OPS`. This overrides `LLL_TEAM` without rewriting any
configuration. An explicit issue identifier still targets its own team.

Precedence: env vars > the repo's `.lll.toml` > `~/.config/lll/lll.toml`. The
files **layer**: each supplies the keys it names, so a repo file carrying
`team` alone still gets `url` and `token` from the machine's. `.lll.toml` is
found by walking up from the working directory. Inside a repo the walk stops
at the repo root and no higher, so a stray file above a checkout cannot
capture it. Outside any repo it stops at the first of: the file, a directory
holding `.git` (someone's checkout is not this directory's tracker), or your
home directory **exclusive**. A `.lll.toml` sitting directly in `$HOME` is
never read, because `~/.config/lll/lll.toml` is how you set machine-wide
defaults on purpose.

`lll config list` prints every effective value and the file it came from,
after `git config --list --show-origin`:

```
file:/Users/you/.config/lll/lll.toml	url=http://127.0.0.1:8090
file:.lll.toml	team=ENG
unset	sort=
unset	web_url=
```

A hosted instance serves the board and the API at **one address**: point `url`
at `https://your-host` and both work. The board proxies `/api/` to the
PocketBase it runs in-process, so there is no port to know.

An instance deployed before that change answers the API on `:8091` only. There,
`url = "https://your-host"` returns a bare `404 page not found` from a host that
otherwise responds. Run `lll config check`: it asks the configured url whether it
is a PocketBase API and answers in one line. If it says no against a bare host,
use `:8091`.

Client settings, read by every `lll` command:

| Env | TOML key | Meaning |
|---|---|---|
| `LLL_URL` | `url` | PocketBase **API** base URL (default `http://127.0.0.1:8090`; hosted, `https://your-host`, the board's address, which serves the API too). Persist it without logging in using `lll config set url URL`. |
| `LLL_TEAM` | `team` | Default team key; scopes `issue list`, required by `issue create` |
| `LLL_SORT` | `sort` | Default sort: `created`, `updated`, `priority`, `number`, `title`; `-` prefix descends |
| `LLL_WEB_URL` | `web_url` | Web board base URL for `board`, `issue url`, `view -w`. Set it with `lll config set web_url URL` or `lll login --web-url URL`. Login discovers the board from `/.well-known/lll` when advertised; a separate API listener advertises the operator’s `LLL_WEB_URL`. Explicit settings take precedence. `lll up` saves its actual local board endpoint. |
| `LLL_TOKEN` | `token` | PocketBase auth token sent as `Authorization: Bearer` on every request. A secret: `lll login` writes it to the home config, `lll token create` mints agent tokens; never the repo's .lll.toml |

Server settings, read only by `lll up` (env only, no TOML key; on a host,
set them as secrets):

| Env | Meaning |
|---|---|
| `LLL_ADMIN_EMAIL` / `LLL_ADMIN_PASSWORD` | Server administrator, upserted at boot (a local fallback is used when unset; credentials are never printed) |
| `LLL_BIND` | Bind address for both ports (default `127.0.0.1`; `0.0.0.0` when hosting) |
| `LLL_BOARD_TOKEN` | Pins the web board's access token; unset, each boot mints and prints a fresh one |

`lll config init` writes a commented template. `lll up` uses a supplied member
token or bootstraps a member from `$USER`, then runs the board with a member
token. Token identity determines authorship and claims. Use `lll whoami` to
check your CLI login, and `lll login` to change it. Legacy `me` settings are ignored.

## CLI tour

Attach artifacts to an issue with `lll issue attach ENG-1 ./shot.png`.
`lll issue view ENG-1` lists their stored filenames; use
`lll issue download ENG-1 FILENAME > artifact` to retrieve exact bytes, or
`lll issue detach ENG-1 FILENAME` to remove one. These commands also accept
an issue's board URL. Use `lll issue attach ENG-1 -- -filename` for a
filename that starts with a dash. After `--`, values are positional even
when they look like flags; place options such as `--team` before it.

The issue page supports upload, image preview, download and removal. Cards
show a paperclip count without fetching images. Files use PocketBase's
protected storage; the board access gate is required for browser downloads.
HTML and other non-raster artifacts download as files. The attachment
migration permits 20 files per issue, at most 20 MiB each. A server upgrade
is required before an older deployment can accept attachments.

Use `--help` for command syntax. Issue lists and views support `--json`;
scalar reads such as `branch-name` print a single value for shell composition.
Scripts can rely on the exit codes and the `--json` fields listed in the
[CLI contract](docs/cli-contract.md): 2 usage, 3 not found, 4 refused,
5 nothing to do, 6 not authenticated.

The tour runs in `my-repo` from the quickstart, a git repository attached to
team DEMO:

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

The other nouns (`team`, `member`, `project`, `label`) list, create and view
the same way:

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
lll login --url https://your-host --email you@example.com --create --password <pw>
                              # one command: make the member, log in, settle the team
lll login                     # as a member, against the configured url
lll member passes --count 10 --prefix hack  # private LAN/Tailscale teammate handoffs
lll member set-password NAME --password <pw>  # superuser gives a member credentials
lll member delete NAME        # delete a member with nothing assigned (superuser only)
lll token create NAME         # a one-year agent token (superuser only), printed once
lll logout                    # clear the stored token
```

Each flag and verb has one canonical spelling, and help, messages and docs use
only that one. A few others are accepted permanently as aliases: `new` for
`create`, `show` for `view`, `add` and `remove` for member `create` and
`delete`, `edit` and `update` for each other, `-d`/`--description` for `-b`
where the text is a description, `--ro` for `--read-only`, and `--list` for
`config list`. A removed spelling fails and names its replacement.

Scripts that read `lll watch` should start from `lll watch --help`. It lists
the exact status lines (all on stderr), what a label-only update prints, and
which claim operations produce an event. `lll bot rotate --help` says who may
rotate a bot's token and which tokens a rotation strands.
`scripts/test_watch_contracts.py` pins all four answers.

Issue IDs resolve: explicit arg, else the current git branch
(`eng-12-fix-login` -> `ENG-12`).

`issue start` changes state without touching Git or the recorded work location.
`issue start --branch` explicitly creates or switches to the suggested branch
and records its branch, host, and checkout/worktree path. Running it from another
worktree replaces the current location and leaves the previous one in a comment.
Use `issue branch-name` when composing your own Git commands.

## Web board

Server-rendered board at `/`, one team's board at `/t/KEY/`, issue pages at
`/issue/KEY-123`, the team's docs at `/t/KEY/docs`, search at `/search?q=…`,
and your own login at `/me`.

- Realtime: changes from the CLI, other browsers, or the board itself appear
  everywhere without reload, over one SSE connection per page.
- Drag-and-drop between state columns and reorder within them.
- Live search, filter chips (assignee/label/priority/state), hideable columns.
- `/search?q=…` searches the database, not the rendered board, so the query is
  a shareable URL and `curl` gets the same answer the browser does.
- `lll search TEXT` is full text over issues, comments and docs, ranked, with the
  lines around each match; the board's `/search` runs the same engine.
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
itself (no external binary), plus `jq` and `python3`. It never touches your
data.
See [browser failure probes](scripts/README.browser-failures.md) to exercise
rejected creates and state changes through the real browser handlers.

`scripts/import_sidecar.py` imported this project's former `.private` sidecar
tracker (Backlog.md tasks + wiki/decisions/findings) into an lll instance as
team `LLL`. It is idempotent. Every record carries an `Origin: sidecar ...` body line, and
a re-run creates nothing that is already there. Re-running it is safe, and is
how new sidecar records get picked up:

```sh
LLL_TOKEN=<token> python3 scripts/import_sidecar.py --url <instance-url>
```

`--url` is required (it never guesses an instance) and the token comes from
`lll token create` (superuser-gated). Worklogs are not imported; the sidecar
stays their archive.

Layout:

- `src/`: Lisette source, `main.lis` dispatch, `commands/` one file per
  noun, `records/` shared record lookups, `pb/` REST client, `realtime/` SSE client, `query/` filter builder,
  `config/`, `display/`, `gitctx/`, `models/`.
- `pb/`: PocketBase schema as code, `pb_migrations/`, applied on start.
- `gopb/`: a tiny Go module embedding PocketBase behind one `Serve` function.
- `web/`: `templates/` (html/template) and `static/` (plain CSS), compiled
  into the binary via a `//go:embed` in `web/embed.go`: edits need a rebuild.
  Mermaid stays embedded for offline, single-file delivery and loads in the
  browser only when a diagram appears.

## Architecture

```
lll CLI ── REST ──> PocketBase (embedded; sqlite + migrations)
                        │ realtime SSE (JSON records)
browser <── HTML/SSE ── lll up web board (Datastar fragment morphing)
```

One Lisette codebase compiled to Go. The CLI talks to PocketBase's REST API
directly, with no SDK. The board renders html/templates, holds one subscription
to PocketBase realtime, and pushes re-rendered fragments to every open page
over SSE; [Datastar](https://data-star.dev) morphs them into the DOM by
element id. `lll up` runs PocketBase in-process (see `gopb/`) and the board
in one process; it reuses an already-running PocketBase at `LLL_URL` instead
of starting its own.

The board uses the same PocketBase REST client for application reads and writes
even when the server is embedded. This preserves one local/remote data contract;
the public API proxy hides the internal listener without removing that HTTP hop.
The board acts as its process identity, not each browser visitor's identity.

A one-way, greppable Markdown projection is available with `lll export`.
See [export mirrors](docs/export-mirror.md) for managed destinations, pagination
and failure recovery. It does not replace a database backup.

## License

MIT. See [LICENSE](LICENSE).
