# Operate an lll server

Use this reference when you run the server. To start a first board or accept
an invitation, use [setup](setup.md). For a public deployment, follow
[deployment](ci-deployment.md).

## Start the server

### Named boards

`lll new "Payments rewrite"` chooses key `PAY`; `--key` chooses another.
Its data lives in `~/.config/lll/boards/pay`. Run the same command to reopen
a local or shared board. A shared attachment is recognized by verifying its
privately saved member login against the cached database, without contacting
the network address. If that proof is missing or retired, the command keeps the
attachment unchanged: remove its URL as the refusal explains, or use an
unattached directory to reopen the saved data, then attach deliberately. A key used by a different title, or a directory attached to another board,
is refused rather than silently replaced. Ctrl-C stops the server.

### Explicit server settings

Use `lll up` when you want to choose the server settings yourself:

```sh
LLL_TEAM=APP lll up
```

On a fresh setup it creates the team, writes `.lll.toml` here, and creates a
member named after `$USER`. A taken port moves to the next free one. If an lll
server already answers at the API URL, `lll up` uses it, unless only a repo
`.lll.toml` chose that URL: then it stops with exit 4. A named board started by
`lll new` keeps its own data directory and does not adopt an existing server.

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
`jq -r .password pb/pb_data/.lll-admin.json` (for `lll new`, in
`~/.config/lll/boards/<key>/`). `lll up` logs the CLI in only
when your home config holds no token and names no other server; it never
replaces a login. `lll new` also logs in the directory it ran in, even when
you are logged in to another server: `.lll.toml` names the board's url, and
its token goes to `~/.config/lll/logins.toml` (0600), never to `.lll.toml`.
Commands in that directory reach the new board; everywhere else keeps your
other login, and `lll logout` there removes only the board's. A `.lll.toml`
that already attaches the directory to another team or server is refused
(exit 4) rather than rewritten.

To choose a network address directly, run `LLL_TEAM=APP lll up --bind YOUR_IP`,
replacing `YOUR_IP` with this machine’s LAN or Tailscale address. For automatic
address discovery on a named board, use [network sharing](setup.md#share-a-board-on-a-lan-or-tailscale).

## Give people access

Prefer a [single-use invitation](inviting.md) for someone joining through a
browser. They keep their existing identity when already signed in, and the
setup page gives the exact token-based CLI login.

For an email-and-password account, an administrator can use:

<!-- example-check: skip: needs a hosted server and administrator access -->
```sh
lll member invite NAME --email their@email --url https://your-host
```

It prints a temporary password once and the login line to send privately.
`--team KEY` (repeatable) limits access; `--read-only` forbids writes. A member’s
bots cannot exceed their owner’s grants. `lll member access NAME` shows access.
An email-and-password member later runs `lll login --url https://your-host
--email you@example.com`; it prompts privately for the password. Use
`lll login --help` for account creation and non-interactive password input.

### Private member passes

<!-- example-check: skip: requires a shared board and creates private member handoffs -->
```sh
lll member passes --count 10 --prefix hack
```

This writes a mode-0600 handoff file containing member tokens, the API address
and a board login link. Send each person only their own block. The shared
browser link uses the board process’s identity; each CLI token names its own
member. Do not publish the file or data directory. Use normal invitations
when people should have their own browser identity.

## Database administration

The lll web board is the interface for everyday work. The separate database
administration console can change records, collection rules and the schema,
so lll does not expose it through the board unless you enable it deliberately.
Start with `lll up --admin-ui` to make it available at the board's `/_/` path.
It requires the server's administrator credentials, not a regular board login.
The option controls the board's proxy; the separate API listener retains its
own administration routes.

## Upgrade and recover

Run `lll upgrade`. On Homebrew it runs `brew upgrade lll`; other installs
print the appropriate command. If you run a server, stop it and back up its
data before upgrading. See [the upgrade guide](upgrading.md) for server-first
rollout, migration checks and restoring a backup.

A Homebrew install updates itself. Once a day per server, lll checks the
server's version. When the server is newer, lll starts `brew upgrade lll` in
the background, prints one line on stderr and finishes your command
unchanged:

    lll: updating 1.2.0 -> 1.3.0 in the background (log: ~/.config/lll/auto-update.log). Disable: LLL_AUTO_UPDATE=0

To switch this off, set `LLL_AUTO_UPDATE=0` or put `auto_update = false` in
`~/.config/lll/lll.toml`. It is off when `CI` is set. It is also off on a
machine that runs the server: where `lll up` has run (it leaves
`board-login-url` beside the config) or where a Homebrew `lll up` is running.
There, and on every install that is not Homebrew, lll prints the warning
`... Upgrade: lll upgrade` instead. A machine that starts `lll up` with
another config directory should set `auto_update = false`.
