# Using the lll CLI

The CLI and [web board](#web-board) work on the same issues. Start with
[the README quickstart](../README.md#quickstart) or [join an existing board](setup.md).
Every command has `--help`; `lll --help` lists the available commands.

## A day-to-day workflow

The examples below continue from the local `APP` board in the README.
The branch helpers need a Git repository; run `git init` in `my-project`
first if it is a new directory.

```sh
lll label create bug
lll issue create -t "Fix login" --priority 1 --assignee "$USER" --label bug   # APP-2
lll issue list --state todo --sort -updated
lll issue branch-name APP-2  # print app-2-fix-login; changes nothing
lll issue start APP-2        # state -> in-progress; leaves Git untouched
lll issue start APP-2 --branch  # also create or switch to that branch, and record the work site
lll issue claim APP-2        # take it exclusively; non-zero if someone holds it
lll issue view                # APP-2, inferred from the git branch
lll issue comment -b "done in abc123"   # markdown; renders on the web board
lll issue ref APP-2 gh#42    # append once; also retries a failed PR-reference save
lll issue release APP-2      # give it back
lll issue close               # APP-2 again, from the branch
```

These need a GitHub remote, or stream until Ctrl-C:

<!-- example-check: skip: needs a GitHub remote, or streams until Ctrl-C -->
```sh
lll issue pr                  # gh pr create titled "APP-2: Fix login"; records gh#N
lll watch --state in-review   # live NDJSON-able event stream for a query
lll issue watch APP-2        # one issue + its comments, until Ctrl-C
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

`lll issue attach APP-1 ./shot.png` attaches a file (at most 20 per issue,
20 MiB each); `issue download` and `issue detach` take the filename.

Scripts rely on [the CLI contract](cli-contract.md)
(`lll help contract`): exit codes, `--json` fields and permanent spellings.
Data goes to stdout and notices to stderr. Exit codes: 1 error, 2 usage, 3
not found, 4 refused, 5 nothing to do, 6 not authenticated. For `lll watch`
output, start from `lll watch --help`.

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

## Web board

The board is server-rendered: all teams at `/`, one team at `/t/KEY/`, issues
at `/issue/KEY-123`, docs at `/t/KEY/docs`, search at `/search?q=TEXT`, and
your login at `/me`. Changes appear in every open page without a reload.
Cards drag between state columns. `/search` queries the database, so a search
is a shareable URL; `lll search TEXT` runs the same engine.

## Coding agents

Run `lll bot create bot-my-project` as a logged-in member to create a bot you
own. The command prints a prompt containing the server, identity and token
for your agent. Treat that prompt as a credential. Creating a bot with an
existing name is refused; `lll bot rotate NAME` replaces a token.

An agent can read the working conventions with `lll skill get lll`. They
cover claiming an issue before work, leaving findings and decisions, and
closing with evidence. The [CLI contract](cli-contract.md) describes the
stable command names, exit codes and JSON fields for automation.
