# Setting up lll

Start a board, join one, or share yours. Server settings and administrator
procedures are in [server operations](server-operations.md).

## Start your own board

Install lll ([other platforms](https://github.com/escherize/lll/releases/latest)):

<!-- example-check: skip: installs lll; checks use the binary under test -->
```sh
brew install escherize/lll/lll
```

Run in a project directory:

```sh
mkdir my-project && cd my-project
lll new "Payments rewrite"
```

Open the sign-in link it prints. Keep this terminal running; in a second
terminal in the same directory, add a task:

```sh
lll issue create -t "First issue"
```

Stop the server with Ctrl-C; its data stays. The directory remembers its board.
Run the same `lll new` command to reopen
it after stopping the server. The title chooses the team key (`PAY` here);
`--key` chooses another. [Server operations](server-operations.md#start-the-server)
explains data locations, existing logins and explicit settings.

### Hosting with explicit server settings

Use `lll up` for direct control over the address, data directory and startup
identity. Follow [server startup](server-operations.md#start-the-server), or
[deployment](ci-deployment.md) for a hosted board.

## Join an existing board

1. Open your invitation and join. If already signed in, you keep that account.
2. Run the setup page’s exact CLI login command; it uses the token shown
   there, so you do not need a password.
3. In your repository, [attach the team](#choose-a-team-for-a-repository) only
   if it is not already configured for the correct board and team.

An existing email-and-password member can use
`lll login --url https://your-host --email you@example.com`; the command asks
for the password privately. A superuser is an administrator, not a member.
See [account administration](server-operations.md#give-people-access) for that role.

## Choose a team for a repository

If your invitation names team `PAY`, run:

```sh
lll attach --key PAY
```

This writes the attachment to `.lll.toml` at the repository root; commit it
so clones and worktrees use the same board. Outside Git, it attaches the
working directory and its subdirectories. Use your board’s team key; it creates that team if missing;
without `--key`, a server with one team selects that team.

Separate teams keep separate backlogs. `lll team archive KEY` hides a finished
team while retaining its work and links; `lll team unarchive KEY` restores it.

## Invite someone

The board must be reachable by your teammate. If it is local-only,
[share it first](#share-a-board-on-a-lan-or-tailscale). Then:

```sh
lll invite create --team PAY --for Alice --for Bob
```

Send each person their own single-use link. Their setup page explains CLI
login and creating their agent. Keep their private token out of shared
messages. [Inviting people and agents](inviting.md) covers access choices.


## Share a board on a LAN or Tailscale

Stop the running server, then reopen the same board with sharing enabled:

<!-- example-check: skip: needs a LAN or Tailscale address -->
```sh
lll new "Payments rewrite" --share
```

This prints sign-in links for the machine’s LAN and connected Tailscale
addresses. It does not bind every interface; without Tailscale it shares on
the LAN only. The board keeps its token across restarts. To choose an address or create private
handoffs, see [server operations](server-operations.md).

## Database administration

The optional database console is for operators. See
[administration](server-operations.md#database-administration) for enabling it
and the credentials it requires.

## Try an isolated board

`lll up --scratch` starts a throwaway board without your existing settings.
Its banner names the temporary directory; stop the server and delete that
directory when finished.

## Upgrades

Run `lll upgrade`. Server operators should read
[upgrading and recovery](server-operations.md#upgrade-and-recover), including
backups and the client auto-update settings.
