# Invite people and their agents

Create a separate link for each person and print one message you can paste
into Slack or email:

```sh
lll invite create --team ENG --for Sloan --for Maksym --for Timothy
```

Each link works once, grants access only to the named teams, and expires
after seven days. Add `--read-only` for readers. Repeat `--team` for more
teams. The `--for` labels help you send the right link to each person; they
do not reserve an account name or bind the link to an email address.

Send the message as printed. The recipient opens their link, chooses a name,
and lands on their own setup page. Merely opening a link does not spend it:
submitting the join form does. A GET showing the form is not a validity
check; expiry and prior use are checked when the form is submitted.

## What each person does

The setup page guides them through installing lll and signing the CLI in
with the token shown after they explicitly ask for it. Link-based members
do not need an email/password login. The command is:

```sh
lll login --url https://your-board --token -
```

They paste the token at the prompt. If their repository already contains
`.lll.toml` for this board and team, they can skip `lll attach`.

A read-write member then runs the bot command shown on their setup page.
It creates a bot owned by that person, within their access, and prints the
prompt to paste into their agent. The inviter never needs to collect their
personal token or create broadly privileged bots on their behalf. Read-only
members cannot create bots. Existing bot names are refused rather than
silently rotated; choose another name, or deliberately use `lll bot rotate`
when replacing a token you own.

## Keep links when a group stops partway

`--for` creates one invite at a time. If a request fails, the command exits
nonzero but still prints the links it has already received, plus the pending
names. Keep those links and retry only the pending names. An interrupted
request may have committed without returning a usable link; a retry is not
idempotent. Do not rerun the entire group and discard the successful output.

`--json` with `--for` returns `invites` (each with `name`, `url`, `code`,
`expires`), `teams`, `mode`, `pending`, and `complete`. Even on partial failure,
stdout remains one JSON document and stderr carries the error. Without
`--for`, the existing single-link text and JSON formats are unchanged.

## Board addresses

Unless you explicitly set `LLL_WEB_URL`, invite creation uses the board address
advertised by the server you are contacting. This avoids printing an old
local board address for a hosted server. On an older server without discovery,
lll falls back to the configured board address only when it belongs to the
contacted server; a loopback fallback for a remote API is also refused before
creating an invite. Set `LLL_WEB_URL` to the
shared board address if your server does not advertise one.

Only a full read-write person member without an owner, or a superuser, can
create invites. The command does not send messages or create the recipients'
bots. Invite links and the tokens on the setup page are credentials; send
each person only their link, and keep tokens out of shared drafts.
