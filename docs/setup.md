# Setting up lll

Start with [the README](../README.md#quickstart) for a local board. This guide
covers joining an existing board, sharing your own, and choosing where work
is tracked. For available commands and configuration, see [the CLI guide](cli-guide.md).

## First startup

A team groups issues under a short key: `APP` gives you `APP-1`, `APP-2`,
and so on. A local board runs while this command is open:

```sh
mkdir my-project && cd my-project
LLL_TEAM=APP lll up           # lll server (:8090) + web board (:8100)
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
| `agent` | a prompt to paste into a coding agent on this machine (only when it logged your CLI in), then how to give an agent its own member with `lll bot create` |

With `LLL_ADMIN_EMAIL` and `LLL_ADMIN_PASSWORD` unset, the first boot
generates a password for `admin@local.dev`. Read it with
`jq -r .password pb/pb_data/.lll-admin.json`. `lll up` logs the CLI in only
when your home config holds no token and names no other server; it never
replaces a login.


## Join an existing board

| Actor | Once | Writes |
|---|---|---|
| Server | `lll up` with server settings in env (on a host: secrets) | the database |
| Your machine | `lll login --url https://your-host --email you@example.com` | `url`, `token`, `team` in the home config |
| Each repo or directory | `lll attach` | `team` in `.lll.toml` |
| Each agent | a member runs `lll bot create bot-NAME` | a private prompt with the agent's identity and token |

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

## Choose a team for a repository

`lll attach --key KEY` writes `team = "KEY"` to `.lll.toml`, creating team
KEY if it is missing. In a git repository the file goes at the repo root;
commit it, and every clone and worktree is attached. Outside a repository it
goes in the working directory, and subdirectories inherit it. Without
`--key`, a server with one team picks that team.

Use a separate team when you want a separate backlog. A directory does not
need to be a Git repository to have one. When a team's work is finished,
`lll team archive KEY` hides it from the active list while retaining its
issues and links. `lll team unarchive KEY` makes it writable again.

## Invite someone

Invite a colleague with a single-use link, or with an email and a temporary
password:

```sh
lll invite create --team APP    # prints <board>/join/<code>
lll member invite kim --email kim@example.com
```

The link leads to `/me`, which shows a CLI token for
`lll login --url <board> --token -`. A loopback board works only on this
machine; see [Share a board](#share-a-board-on-a-lan-or-tailscale).


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


## Database administration

The lll web board is the interface for everyday work. The separate database
administration console can change records, collection rules and the schema,
so lll does not expose it through the board unless you enable it deliberately.
Start with `lll up --admin-ui` to make it available at the board's `/_/` path.
It requires the server's administrator credentials, not a regular board login.
The option controls the board's proxy; the separate API listener retains its
own administration routes.

## Try an isolated board

`lll up --scratch` starts a throwaway board that ignores your home config and
inherited `LLL_*` settings. Its banner names the temporary data directory;
stop the server and delete that directory when finished.

## Upgrades

Run `lll upgrade`. On Homebrew it runs `brew upgrade lll`; other installs
print the appropriate command. If you run a server, stop it and back up its
data before upgrading. See [the upgrade guide](upgrading.md) for server-first
rollout, migration checks and restoring a backup.
