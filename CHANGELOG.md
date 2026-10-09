# Changelog

All notable changes to lll. The format follows Keep a Changelog; versions
follow SemVer, with 0.x meaning the CLI surface can still move between
minors. Issue keys are on the project's own board (`lll issue view KEY`).

## [Unreleased]

### Added

- `read` is a permanent hidden alias of `view` on `issue`, `doc` and
  `finding`: it dispatches, but has no help row and no completion. Five of
  twenty agents in the 1.0 fleet typed `lll issue read KEY`. This reverses
  the 1.0 retirement of `read`.
- `lll help contract` prints the CLI contract (docs/cli-contract.md),
  carried in the binary. `lll --help` points at it.
- `--json` on the write verbs that lacked it: `issue attach`, `detach`,
  `release`, `ref`, `block`, `unblock` (the issue), `issue link` and
  `unlink`, `doc edit`, `finding confirm` and `refute` (the doc),
  `project create`, `edit` and `move`, `label edit` and `move`, `team
  rename`, `set-accent`, `set-emoji`, `archive` and `unarchive` (the
  record). A test lists every verb that still has none, with the reason.
- `doc create -k finding` takes `--confidence suspected|confirmed`, as
  `finding create` does (LLL-641). On another kind it exits 2.
- `--assignee ''` means `none` on `issue update`. It exited 2.
- `doc edit --confidence suspected|confirmed` on a finding, the write
  `finding confirm` makes (the note is cleared). `--confidence refuted` is
  refused with the verb that refutes, `finding refute SLUG -b WHY`; on a
  doc that is not a finding, `--confidence` exits 2.
- Issue `--json` names its members and catalogues beside the ids:
  `creator_name`, `assignee_name`, `project_name`, `label_names`. Doc and
  finding `--json` add `author_name` and `last_editor_name`. A member you
  cannot see is `"hidden member"`. The ids and `expand` are unchanged.
- `issue view` (and `--raw`, which now lists labels) prints a label's team
  beside a name another team you can see also uses: `Labels: bug (OPS)`.
- `issue update --keep-claim`, with `--state done|cancelled`, keeps your
  claim (see Changed).
- `config show` is a permanent hidden alias of `config list`.
- Every noun's `--help` ends with the exit-code legend `lll --help` has.
  The `issue next` row says the key is alone on stdout, notices go to
  stderr, and exit 5 means nothing is ready.
- `--admin-password -` reads stdin, as the other password flags do. Only
  one password flag per command can read stdin.
- `issue next --ready` is accepted, hidden: next only offers ready issues.
- `lll issue next --help` states its output contract: stdout is the key (or
  one JSON object), stderr the notices, exit 5 when nothing is ready.
- The contract covers which stream carries what: data on stdout, notices on
  stderr, and with `--json` exactly one JSON value on stdout.

### Changed

- `issue next` says why it has nothing to offer when the reason is not an
  empty board (LLL-685): ready issues all claimed by someone else are named
  as claimed, and open issues all waiting on blockers are named as blocked,
  pointing at `lll issue list --blocked` ("no other ready issues" when
  you hold a ready one yourself). Both used to read "the agenda is
  empty". The all-assigned and own-claims wordings are unchanged.
- Breaking, toward less surprise: one rule for finishing a claimed issue.
  When the holder moves it to done or cancelled by any path (`issue close`,
  `issue update --state done|cancelled`, the board's state picker, a native
  PATCH or `/assignment`), the server releases the claim in the same
  transaction and keeps the assignee, as close already did. `--keep-claim`
  (`keep_claim` on the routes, `?keep_claim=true` on a PATCH) opts out.
  Before, only close released, so workers followed `update --state done`
  with `issue release`, which also cleared the assignee. Text output says
  so: `Updated FLEET-4: state=done; released your claim (assignee kept)`.
  A move by anyone else (another member, or another agent label on your
  token) leaves the claim as before, and update's output now names who
  still holds it. The board signs in as its operator's member, so a drag to
  Done there releases a claim that member holds under any agent label.
- `issue release` on a done or cancelled issue that clears the assignee
  names the repair on the same line, `issue update KEY --assignee NAME`,
  and the finish that would have kept it (`issue close KEY` on a done
  issue).
- Exit 5 (nothing to do) prints `Nothing to do: ` on stderr, not
  `Error: `. The exit code is unchanged.
- A password flag given `-` on a terminal prompts with echo off; it read a
  plain line and echoed the secret. Piped empty stdin is a usage error (exit
  2), `--password -: stdin was empty`, for `login` and `member set-password`
  alike.
- `lll version`, `--version` and `-v`: `--help` prints help, and any other
  argument exits 2. They printed the version and exited 0.
- `bot create|rotate --env --team KEY` exits 2: `--env` prints no prompt, so
  `--team` had been ignored unchecked.
- An unsupported `--url` names what sets the url: LLL_URL or a repo
  `.lll.toml` outranks `lll config set url`, so it is only suggested when it
  would take effect. The server-wide `--team` refusal names `lll api`, not
  `lll api METHOD`.
- `lll --help` shows `lll issue claim KEY` in its examples.
- `issue update KEY --assignee <yourself>` adds one line to its text
  output: assigned is not claimed, and `lll issue claim KEY` holds the
  issue. `--json` output is unchanged.
- `doc view` and `finding view` print `Confidence: <word>` for every
  finding, confirmed included; `finding list` and `finding near` tag every
  line with its confidence, `[confirmed]` included.
- A rename names the old and new names: `Renamed label regresion ->
  regression`, `Renamed project A -> B`, `Renamed team ENG -> PLAT`.
- `finding create --help` describes `-k` as defaulting to finding.
- `issue next --claim --json` prints no "Claimed" notice, and `issue start
  --branch --json` no Git lines: the JSON carries both.
- `bot create --env` and `bot rotate --env` print nothing on stderr, so a
  `2>&1` capture sources cleanly. Four of ten fleet agents captured that
  way; the expiry line broke `source` and the next command ran as the owner.
- `issue next` with nothing to offer names the ready issues it skipped for
  being assigned, and how to offer one (`--assignee none`). `issue release`
  of an assigned, unclaimed issue says the same.
- An expired or rejected token's message adds `lll login --token -` for a
  caller who holds a valid token, then `lll config check`. `whoami` with an
  expired token also reports a server that does not answer.
- A refused connection names where the url came from and the fix for that
  source: `lll config set url URL` or `lll login --url URL` for the machine
  file, the url line for a repo `.lll.toml`, the variable for LLL_URL. A
  token from LLL_TOKEN is told to fix the variable, since a login would not
  outrank it.
- `lll config --help` names `lll login --token -` for saving a token, and
  `lll config set token` refuses with that pointer (exit 2).
- `lll bot WORD`, where WORD is another noun's verb (`list`, `read`), is an
  unknown command (exit 2) that names create, rotate and `lll member list`.
  It suggested creating a bot named after the verb.
- An unknown verb that is a top-level command names it: `lll member whoami`
  says "did you mean 'lll whoami'?".
- `issue view` always prints the claim row, `Claimed:   none` when nothing
  is held, and `--raw` prints `- **Claimed:** none`. Two fleet agents read
  a missing row as claimed.
- A refused `--if-unchanged-since` update prints the same command with the
  issue's current stamp, ready to rerun. `--description-append` help says it
  applies at write time and needs no stamp beside concurrent appends.
- `lll issue priority` (or `state`, `assignee`, `label`, `project`) names
  `lll issue update KEY --priority <name>`.
- `lll login --password -`, `member set-password --password -` and
  `--old-password -` read the password from stdin. `-` was taken as the
  password itself.
- `--help` answers on every verb before a required flag is checked: `lll
  invite create --help` exited 2. A test drives `--help` on every noun and
  verb from the command table and checks no page lists a flag twice.
- `lll member view` names `lll member access NAME`.
- `--team` on a server-wide command (`member`, `team`, `token`, ...) says the
  command is server-wide; it offered an LLL_TEAM override that filters
  nothing. `member list` adds that its last column shows each member's teams.
- A rejected `--old-password` says only an administrator can reset a
  password you do not know.
- Usage lines list enum values, generated from the enums: `--state
  backlog|todo|...`, `--priority none|urgent|...|0-4`, `--sort`, project
  `--status` and doc `-k`.
- `lll issue --help` lists `--reason` once; its help says `issue release`
  also takes it as `-b`.
- `issue update --claim` exits 2 with "to claim, run: lll issue claim KEY"
  instead of the update usage.
- Every secret flag reads `-` the same way (LLL-686): `--password`,
  `--old-password`, `--admin-password`, `--token` and `webhook add
  --secret`. On a terminal it prompts with echo off; otherwise it reads one
  line from stdin, and an empty one exits 2 naming the flag. `member create
  --password -` and `webhook add --secret -` took `-` as the value.
  `login --token -` printed `Token: ` into a pipe and, on empty stdin, said
  the token was missing.
- Ctrl-C at a hidden password or token prompt restores terminal echo and
  exits 130; it left the shell with echo off. `member create --password -`
  on a terminal asks twice and refuses a mismatch. `--admin-password -`
  followed by a prompt (`member set-password` without `--password`, `login
  --create` without `--password`) reads the prompt's answer from the same
  stdin; the answer was lost and the command said there was no password.

### Fixed

- Every bad command line exits 2, as the contract says. These exited 1: an
  unknown argument to `whoami` or `logout`; an unknown `skill` verb,
  `completions` shell, `help` topic or `config get` key; `doc link` and
  `doc unlink`; a `bot` name without the `bot-` prefix; `config set`
  without its two arguments; an `issue` verb with no ID and no branch to
  infer one from; `issue create` with no title; a malformed value: `doc
  create -k` or `--confidence`, `project --status`, a `team set-accent`
  colour, a `webhook add` URL, `login --url`, `--web-url` and `config set`
  URLs, `issue comment` numbers, `up --bind 0.0.0.0`, `member create
  --password ""`, and `member access --read-only --read-write`; `config set`
  of an unknown key; two `member access` team selectors at once; `login
  --token` with `--email`, or with an empty token; a malformed team key on
  `team create` or `team rename`; a malformed doc slug; a label or project
  name with a comma; `lll api METHOD` without a PATH (it printed help and
  exited 0).
- `lll skill get NAME` for an unknown skill exits 3 (not found). It exited 1.
- An expired or rejected token from a repo `.lll.toml`, and the notice
  after a password change, say to remove that file's token line. They said
  to run `lll login`, which saves to the home config the repo file
  outranks (LLL-687).
- A refused superuser login names where the url came from (`LLL_URL`, the
  config file, or `--url`). It said `--url` whatever set the url (LLL-687).
- `lll config list` and the hints attribute a key to the repo `.lll.toml`
  whenever it names that key. When it repeated the home config's value,
  the key was attributed to the home config, whose edits the repo file
  overrides (LLL-687).

## [1.0.0] - 2026-10-08

1.0 promises SemVer for the surface in `docs/cli-contract.md`: exit codes,
the `--json` fields it names, the list envelope, and command, verb and flag
spellings with their permanent aliases. A change that breaks a script built
on them needs 2.0. Message wording and help text are not covered.

The surface is the 0.9 surface with the changes listed below. The internals
have been restructured: PocketBase's rules are the one owner of access, one
write layer makes every record write, values are parsed into types where
they arrive, and no credential or scope travels through the environment.

### Upgrading from 0.9

Read this list before you upgrade a server, a script or an agent prompt.
Details are in the sections below.

**Deploy the server before the clients.** The server runs five migrations
on its first boot: per-team issue counters, the board's link viewers,
identity-field rules, self-only member rename, and the doc `last_editor`
field. Back up the server's data directory first. A 1.0 CLI against a 0.9
server reports a bot-owner refusal as an administrator-credentials refusal,
and refuses a description edit combined with `--assignee` ("invalid
assignment update fields").

Exit codes.

- `lll issue update KEY --assignee NAME` (or `--assignee none`) on an issue
  that another session's claim holds, refused for needing `--force`, exits 4
  (refused). It exited 1.
- `lll member access` recognizes the bot-owner refusal (a bot wider than
  its owner) by its stable code `bot_exceeds_owner` and relays the server's
  message (exit 1), as before. A 0.9 server sends no code, so against it a
  1.0 CLI reports that refusal as needing administrator credentials (exit 4).

Command line.

- An issue key with a signed number (`ENG-+3`) is refused as not an issue ID
  (exit 2). The CLI used to read it as `ENG-3`.
- `--team` given twice on one command is refused (exit 2). It used to keep
  the last value.
- `lll login` without `--url` refuses when `LLL_URL` or a repo file names a
  server other than the one in the home config. Pass `--url` to switch the
  home config.

Issue numbers.

- An issue key is never reused. Deleting a team's highest-numbered issue no
  longer hands its number to the next issue, so after such a delete the next
  key is one higher than it would have been in 0.9.
- **Breaking for member restores:** `lll import dir` keeps a mirror's issue
  numbers only with a superuser token. Run as a member, it imports under new
  numbers and prints which keys changed (`ENG-5 -> ENG-9`).
- A member cannot choose or change an issue's number. Moving an issue to
  another team gives it a fresh number there.

Who may change what.

- Only a superuser or the member itself renames a member. A bot is renamed
  by a superuser only.
- An issue's `creator` and `origin`, a member's owner, and a favorite's or
  saved view's member are set when the record is created and cannot be
  changed by a member. A comment's issue cannot be changed by anyone.

Output and the board.

- `lll doc view` and `lll finding view` print `Edited by:` when the last
  editor is not the author; `doc view --json` has `last_editor`.
- Board form posts refuse an unknown or out-of-team label, project or member
  id by name, instead of passing the raw id to the server.

### Added

- Docs record who last edited them. `last_editor` is set by the server from
  the caller: the author on create, then the member whose update changes the
  doc's content (slug, title, kind, body, area or paths). Linking an issue
  and confirming or refuting a finding do not count. A member cannot send
  it. When it is not the author, `lll doc view` and `lll finding view` print
  `Edited by:`, and the board's doc page and docs index show it, with a
  bot's owner and "hidden member" as for the author. `doc view --json` has a
  `last_editor` field. Existing docs get their author as last editor. The
  docs index's `?raw` author column reads `alice, edited by bob` for such a
  doc. (LLL-682)
- A per-team issue counter that only increases (`issue_counters`, in
  `lll api --schema`). A superuser repairs one with
  `POST /api/lll/teams/{team}/issue-counter` (`{"last": N, "reason": "..."}`);
  the server logs who changed it, from what, and why, and refuses a value
  below the team's highest live issue. Issue numbers are capped at
  999,999,999; a team that reaches the cap is told which issue holds the
  highest number. (LLL-678)

### Changed

- Issue numbers are never reused. Deleting a team's highest-numbered issue
  used to hand its number, and so its key, to the next issue created; a key
  in a commit message or PR then named a different issue. An upgrade starts
  each team's counter at its highest existing number, so a number deleted
  before the upgrade can still come back once. (LLL-678)
- The server chooses issue numbers. A member's create that names a
  `number` gets the next number instead, and a member cannot change an
  issue's number. Moving an issue to another team gives it a fresh number
  there. A superuser may still name a number. (LLL-678)
- **Breaking for member restores:** `lll import dir` keeps a mirror's issue
  numbers only when it runs with a superuser token (`LLL_TOKEN` from
  `lll token create` is a member's; use the administrator's). Run as a
  member, it imports the issues in mirror order under new numbers, links
  blockers and docs to the right issues anyway, and prints which keys
  changed (`Numbered by the server, ...: ENG-5 -> ENG-9`). Before this, any
  member could create an issue under any number, including a deleted one.
  (LLL-678)
- Only a superuser or the member itself renames a member. A full member can
  no longer rename another member, which let it rename someone and take the
  freed name. A bot is renamed by a superuser only, not by its owner or with
  its own token. The board's Members settings row refuses with that reason.
  (LLL-682)
- `--team` given twice on one command is refused with exit 2 (usage).
  It used to keep the last value silently. (LLL-486)
- An unknown team key is attributed to `--team` only when `--team` was
  typed. An inherited `LLL_TEAM` is now reported as `LLL_TEAM`. (LLL-486)
- `lll login` without `--url` refuses when `LLL_URL` or a repo file points
  it at a server other than the one the home config's url names. It used to
  save that server's token, and the board endpoint it discovered, beside the
  other server's url. Pass `--url` to switch the home config. (LLL-680)
- `lll up` saves its board address as `web_url` only into a home config
  whose url names that board's server, or names no server (`localhost`,
  `127.0.0.1` and `[::1]` count as one host). A boot run beside a hosted
  login replaced that login's `web_url` with the local board's address. Such
  a boot now leaves `web_url` alone and says so. `lll up --scratch` also
  refuses to start if its config path is outside its own directory.
  (LLL-680)

### Security

- lll no longer writes its environment. `--team`, tokens, the board
  token and the administrator pair used to be set as environment variables
  for the rest of the process, so child processes (`gh` for
  `issue pr`, `git`, the browser opener) inherited values that their
  parent shell never had. Configuration is now built once from flags, the
  environment and the config files, and passed down as a value. A child
  process sees only what lll's own parent gave it. (LLL-486)
- The web board reads as its viewer. Pages, raw views, search, docs and live
  updates used to be read as the board's own member and then filtered by
  hand for a team-scoped viewer, so one missed filter showed another team's
  data. They are now fetched with the viewer's own credential: a member's
  token, or for a view-only team link a read-only server-side identity for
  that one team (the new `link_viewers` collection; only the server mints
  its tokens, and they never leave it). PocketBase's collection rules are
  the only thing deciding what a scoped viewer sees, and the hand-written
  filters are gone. A page load asks the server for the viewer's access once
  instead of about five times. Nothing a viewer sees changes, with one
  exception: a member with access to every team now gets the redirect the
  board token gets for an issue under another team's address, instead of a
  404. (LLL-658)
- Fields that say who made or owns a record can no longer be forged by a
  member. Superusers still set them, to repair attribution and to import.
  (LLL-681)
  - An issue's `creator` and `origin` cannot be changed after it is
    created. Any read-write member could re-attribute an issue to another
    member or rewrite where it came from. A PATCH naming either field now
    answers 404.
  - A member a member creates is a bot it owns or a person with no owner. A
    full member could create a bot owned by another member, an ownerless
    bot, or a person with an owner, which signs in with a password and
    shows as that owner's.
  - A favorite or saved view is created for its own member or for the
    workspace (no member). Its member cannot be changed, and only its own
    member edits one that has a member. A full member could star an issue
    or save a view in another member's name, move one between members, or
    rewrite another member's. A full member still deletes anyone's.
- A comment's issue cannot be changed after it is created. A PATCH that
  moves a comment to another issue answers 400, for every caller including a
  superuser. (LLL-678)
- The e2e suites, the doc-examples check and the agent-dx fleet wrapper
  refuse to run when the environment they give lll reaches the developer's
  real config. The real home comes from the password database, not from
  `HOME`. (LLL-680)

### Fixed

- `lll issue update KEY --assignee NAME` (or `--assignee none`) on an issue
  another session's claim holds, refused for needing force, exits 4
  (refused) like every other claim refusal. It exited 1: the refusal's kind
  was lost when the message was reworded. (LLL-675)
- The server's refusal of a bot wider than its owner carries the stable
  code `bot_exceeds_owner`, and `lll member access` relays it by that code;
  a wrong `--old-password` is read from PocketBase's `oldPassword` field.
  Both used to be found by matching the message text. Upgrade the server
  with the CLI: an older server's bot-owner refusal has no code, and the
  new CLI reports it as an administrator-credentials refusal. (LLL-675)
- An issue key with a signed number (`lll issue view ENG-+3`, the board's
  `/issue/ENG-+3`) is refused as not an issue ID (exit 2; 404 on the board).
  The CLI used to read it as ENG-3 while the board's gate said it belonged
  to no team: the two now share one parser. (LLL-659)
- `lll issue update --description-append` and `--description-replace` no
  longer lose a concurrent edit. Both derive the new description from the
  issue they read, and the write now lands only if the issue is still that
  version; when it changed in between, the update reads it again and
  re-applies the edit. Two agents appending at once both keep their text.
  With `--assignee` as well, the edit goes through the claim route, which now
  checks the same condition; a server older than this release refuses that
  combination ("invalid assignment update fields") instead of risking a lost
  edit. (LLL-665)
- Board forms refuse a label, project or member id outside what the viewer
  may pick for the issue's team (create, and the settings rows' label and
  project updates, included), naming it, instead of handing the raw id to
  the server. (LLL-675)
- The board's live stream ignores an event on a topic it did not subscribe
  to by name. It used to read any unknown topic as an issue. (LLL-675)
- `lll project view` and `lll webhook list` read every page; they stopped
  at the first 200 items. The board's saved-view name check reads every page
  too. (LLL-659)
- `pb/pb_migrations/lib/rules.js` read a collection's rule as one opaque
  clause, because PocketBase hands a rule to a migration as a Go string
  pointer. Removing a clause failed, and adding one skipped the duplicate
  and top-level `||` checks. No shipped migration was affected: this is the
  first to call it. (LLL-681)

### Internal

No command, flag, page or output changed by these, except as listed above.

- One write layer, `src/writes/`, makes every create, update and delete of a
  lll record, for the CLI and the board alike. Bodies are typed values
  encoded with encoding/json. An issue edit is an `IssuePatch`, where "not
  given" is `None` or `Keep` and the contradictory combinations have no
  constructor. `scripts/test_write_layer.py` holds it. (LLL-659)
- The web board is its own module, `src/serve`, and never imports
  `commands`; shared helpers moved to the modules that own them.
  `scripts/test_module_deps.py` holds it. (LLL-659)
- Typed internals: errors are `pb.CliError` values with a kind, status and
  server code; record ids are one type per collection; "every team" is
  `query.TeamScope.Every`; issue state and priority, member access and kind,
  and realtime events are enums parsed once where text arrives.
  `scripts/test_typed_boundaries.py` holds it. (LLL-675)
- Migrations: `scripts/fixtures/collection_rules.json` pins every
  collection's final rules, and the gate fails when the migrations build
  anything else. `pb/pb_migrations/lib/rules.js` adds or removes one rule
  clause. `scripts/test_migration_names.py` refuses a new shared timestamp
  and a renamed shipped migration. (LLL-657)

## [0.9.0] - 2026-10-08

0.9 is the release candidate for the 1.0 surface. `docs/cli-contract.md` now
lists what 1.0 will promise: exit codes, the `--json` fields it names, the
list envelope, and command, verb and flag spellings with their permanent
aliases. Scripts can build against it now. 1.0 follows once the internals
are restructured; until then this surface can still change, but only with
a CHANGELOG entry that says so. Message wording and help text are never
covered.

### Upgrading from 0.8

Read this list before you upgrade a server, a script or an agent prompt.
Details are in the sections below.

**Deploy the server before the clients.** The 1.0 CLI calls a new route
(`POST /api/lll/issues/{issue}/close`), and the server runs three migrations
on its first boot: comment authorship, webhook creators, and a one-time log
of team keys that break the new key rule. A 1.0 `lll issue close` against a
0.8 server is refused with "update the server". Back up the server's data
directory first.

Flags and commands. A removed spelling fails with exit 2 and names its
replacement.

- `-t` is the title everywhere. For a team on `invite create` and
  `member invite`, use `--team`.
- `-k` is the doc kind. For a team key on `team create`, `team rename` and
  `lll attach`, use `--key` (or the bare argument on `team create`).
- `-p` is the priority. For a password on `lll login` and
  `member set-password`, use `--password`. For paths, use `--paths` on
  `doc create`, `doc edit` and `finding create`, and `--path` on
  `finding list`.
- `--yes` skips a delete confirmation; `--force` on `issue delete` and
  `doc delete` no longer does. `--force` now only overrides ownership or
  references, and `issue delete --force` releases a claim first. `team`,
  `label`, `project`, `member` and comment deletes now ask on a terminal.
- `issue update -b` is the new description, as on `issue create`. The reason
  for a forced action is `--reason`, on `issue release --force`,
  `issue update --assignee none --force` and `issue close --force`.
  `issue update --force -b "why"` is refused and names `--reason`.
  `issue release -b` still works.
- `--description-replace-old` and `--description-replace-new` are now one
  flag: `--description-replace old=new`.
- `lll doc link` and `lll doc unlink` are now `lll issue link KEY SLUG` and
  `lll issue unlink KEY SLUG`. `lll finding read` is now `lll doc view SLUG`.

Exit codes. Every failure exited 1. Now: 0 ok, 1 error, 2 usage, 3 not
found, 4 refused or conflict, 5 nothing to do, 6 not authenticated.

- A declined delete confirmation exits 4. It printed `Aborted.` and exited 0.
- An empty `lll issue next` exits 5.
- A command that needs a team and has none exits 2.
- A missing, expired or revoked token exits 6.
- `lll api` still exits 0 on any HTTP answer; add `--fail` to map the status.

JSON and output.

- Every `list --json` prints `{items, page, perPage, totalItems,
  totalPages}`. `finding list` and `search` printed a bare array, several
  lists printed `{items}`, and `items` is now `[]` when empty, never `null`.
- Every `--json` timestamp is RFC3339 with milliseconds
  (`2026-10-08T03:02:11.982Z`), not `2026-10-08 03:02:11.982Z`.
- Every issue object carries `key` (`ENG-12`) and `claim`. `claim` is
  `{id, member, holder, agent, claimed, renewed}` or `null`, not the raw
  claim record with `expand.member`. `issue next --json` prints the
  `issue view --json` object.
- Errors print the server's message, not the method, URL and JSON body.
- An empty list prints `no labels` (or similar) on stderr and nothing on
  stdout.
- Messages no longer contain em-dashes. A script that matches message text
  may need updating: for example `issue view` prints
  `Blocked by: ENG-1 (todo); 1 open, not ready`. Message text was never
  covered and is not covered by 1.0 either.

Behavior.

- `lll issue close` releases your claim. `--keep-claim` keeps it. Closing an
  issue that someone else holds needs `--force`. Agents no longer need
  `lll issue release` after a close.
- `lll bot create bot-NAME` refuses a bot that already exists (exit 4). To
  re-mint a bot's token, use `lll bot rotate bot-NAME`. `lll bot bot-NAME` is
  an alias of `create`, so a script that used it to rotate must switch.
- A configured token always outranks `LLL_ADMIN_EMAIL` and
  `LLL_ADMIN_PASSWORD`. Only the `--admin-email` and `--admin-password` flags
  act as the administrator when a token is configured.
- With no team configured, `label edit`, `label delete`, `project edit`,
  `project delete`, `project view`, `bot create` and `bot rotate` refuse
  (exit 2). Pass `--team KEY` or run `lll attach`.
- An archived team is read-only for every writer, superusers included. Its
  issues are never ready. Run `lll team unarchive KEY` to write to it.
- The web board refuses every non-GET request whose `Origin` is not the
  board's own address. A `curl` POST to a board page must send
  `-H "Origin: <board url>"`. `POST /create` needs a `team` field, and the
  settings writes live under `/t/KEY/settings/...`.
- The API no longer answers `Access-Control-Allow-Origin: *`. A browser app
  that reads the API from another origin must be listed in
  `LLL_ALLOWED_ORIGINS` (exact `scheme://host[:port]`, comma-separated). On a
  loopback bind, the server answers only loopback host names.
- `lll up` no longer uses the well-known password `admin-local-123`. With
  `LLL_ADMIN_EMAIL` and `LLL_ADMIN_PASSWORD` unset, the first boot generates
  a password for `admin@local.dev` and keeps it in the data directory's
  `.lll-admin.json` (0600). An existing local board that still has
  `admin-local-123` loses it on the next boot; read the new password from
  that file. Setting only one of the two variables is refused.
- Permissions are tighter. Only a member with read-write access to every
  team can create an invite. Only a comment's author can edit or delete it.
  A webhook's secret is never returned, and webhooks cannot be edited
  through the API (remove and add them). See Security.

### Added

- `docs/cli-contract.md`: exit codes, covered JSON fields, the list
  envelope, permanent aliases, and what `lll api` does and does not cover.
  `lll --help` and the README link it (LLL-645).
- `lll --help` opens with a "Start here" block (`lll up`, `lll login`,
  `lll attach`, `lll issue create`) and defines a team in one line (LLL-649).
- The board has a docs index at `/t/KEY/docs`: a team's docs newest first,
  filtered by `?kind=` and `?q=`, with a Docs row in the rail, the jump
  palette and `g d`. Bare `/docs` redirects to it (LLL-643).
- `/me` on the board: a member's boards and a "Show my CLI login" button.
  The token shows only after that same-origin POST, never on a GET. An
  invite link lands there after joining. The rail links to `/me` on every
  page (LLL-648, LLL-649).
- A loopback `lll up` logs the CLI in as its member when the home config
  holds no token and no other server's url, so `lll issue list` works
  straight after the first boot. It never replaces an existing token. A
  `--pb-dir` boot leaves the CLI's login alone (LLL-648).
- `lll login --token TOKEN` (or `--token -` to be prompted) logs in with a
  member token (LLL-648).
- `lll member set-password NAME --old-password CURRENT` lets a member change
  its own password. It logs in again and saves the new token, because the
  change revokes the old one. `lll member invite` prints this line with the
  temporary password (LLL-648).
- `--json` on `whoami`, `team view`, `team create`, `project view`,
  `finding near`, `config list`, `doc create`, `label create`,
  `invite create`, `issue update`, `issue close`, `issue start`,
  `issue claim`, and `issue comment KEY` (LLL-645).
- `lll api --fail`: an HTTP answer of 400 or above exits with the code its
  status maps to (LLL-645).
- `issue list` shows the claim: the text list names the holder, agent label
  and claim age, and `--json` carries `claim` on every item (LLL-651).
- `issue view --raw` prints a `Claimed:` line with the holder, agent label,
  and when the claim was taken and last renewed (LLL-638).
- Claim refusals carry a stable code in the error's `data.code`:
  `claim_held`, `needs_force`, `claim_changed` or `not_claimed`.
- `--agent NAME` on `issue create` (recorded as the origin tool), `issue
  close` and `issue start` (labels the moved-work-site comment).
- Comments carry `author_kind`: `"system"` on the claim-expiry note that the
  server writes on its own, omitted otherwise. The CLI, the board and
  exports show a system comment's author as `system`. Existing comments are
  not relabelled (LLL-654).
- `lll config list` and `lll config get KEY` (url, web_url, team or sort).
  `lll config --list` still works.
- `lll team create KEY -n "Name"` takes the key as the bare argument, like
  `project create` and `label create`.
- Long forms: `--key` and `--name` on `team create` and `team rename`,
  `--name` on `project edit` and `label edit`, `--color` on `label edit`,
  `--web` for `-w` on `issue view` and `lll board`, `-b` for `--body` on
  `lll api`.
- `edit` and `update` are aliases of each other on `issue`, `doc`, `project`
  and `label`.
- `lll doc list --limit N`.
- `lll watch --label` may be repeated, matching any of the labels.
- The invite page warns when the browser is already signed in, because
  joining replaces that login in this browser (LLL-632).
- `lll member create --help` names `lll bot create` for agents (LLL-636).

### Changed

- Every short flag has one meaning, and help, messages and docs use one
  canonical spelling: `-b`/`--body` is the long text everywhere (with
  `-d`/`--description` as aliases on `issue`, `project create` and
  `project edit`), and `--read-only` is canonical on `invite create`, with
  `--ro` as an alias that `member invite` and `member access` accept too.
  See Upgrading for the removed meanings (LLL-644).
- `lll issue close` releases the closer's claim under the release rule and
  keeps the assignee. Before, close kept every claim, and agents that forgot
  `issue release` left finished work held (LLL-640, LLL-646).
- `lll bot create` refuses an existing bot and `lll bot rotate` is the only
  way to rotate a bot's token (D7).
- Administrator credentials never outrank a configured token. Before,
  inherited admin variables made `lll bot` authenticate as the superuser,
  and the bot came out with no owner (D7).
- Exit codes, the list envelope, RFC3339 timestamps, the issue `key` and
  `claim` fields, error text and empty-list lines follow
  `docs/cli-contract.md`; see Upgrading. `doc view --json` and
  `lll watch --json` use RFC3339 too. An HTTP error body counts as the API's
  error only when it names its own `status`; a gateway's
  `{"message": ...}` keeps the request and exits 1 (LLL-645).
- `issue list --since` and `issue update --if-unchanged-since` accept
  RFC3339 in any offset and the space form, and compare instants (LLL-645).
- `lll issue delete` refuses a claimed issue (exit 4). `--force` releases the
  claim first; on an unclaimed issue the delete goes ahead without it
  (LLL-662, LLL-679).
- The board's Release button forces only with a reason typed into the form,
  and its assignee picker never forces. Before, both always forced, so a
  team-scoped member could take any claim without a reason (LLL-662).
- The board's bare write paths no longer fall back to the team the server
  started with (LLL-664).
- `lll board` prints the board's login link (`?board_token=...`) for a
  loopback board on the same machine, because the bare URL answers 401. Do
  not log its output. Every boot saves that link privately beside the home
  config, so `lll member invite --team` prints a board link on a loopback
  boot too (LLL-648).
- `lll member invite` prints the board's address in the colleague's
  `lll login --url` line when the board proves it serves the same server
  (LLL-649).
- `lll login` names a read in its ready line for a read-only member (LLL-648).
- `lll upgrade` installs the download as a new file moved into place, which
  leaves running `lll up` and `lll watch` processes alive. It says to back up
  a server's data directory first and to upgrade the server and its clients
  together (LLL-655).
- A team key is a letter followed by up to 15 letters, digits, `_` or `-`
  (`^[A-Z][A-Z0-9_-]{0,15}$` after uppercasing), on create and rename.
  Existing keys are not rewritten; the server logs each non-conforming key
  once. A key derived from a directory name keeps only ASCII letters and
  digits and starts with a letter (LLL-628).
- Help, messages, the board, the shipped skills and the landing page no
  longer use em-dashes or cite internal ticket keys. The board shows `-` in
  an empty cell (LLL-649, LLL-650).
- The skills shipped in the binary read correctly for any team in any repo:
  no references to lll's own team, board, gate or repo-only skills, and the
  `lll` skill gains a "Record it" block (LLL-647).
- Help fixes: `lll --help` lists `lll bot rotate` and every noun that takes
  `--team`; `lll bot --help` shows the rotate usage; `lll login --help` shows
  every flag; `lll import dir` shows `--team`; `lll skill --help` prints its
  page once; `lll up --help` no longer mentions `--local`;
  `lll finding --help` teaches `lll finding create`.
- `lll issue comment list KEY` and similar guesses name the real forms.
- README: Homebrew first, a quickstart that runs as written on a fresh
  machine, and separate Upgrade and Share sections. README and landing page
  examples are run against a scratch board in CI (LLL-649).

### Removed

- `-t` for a team, `-k` for a team key, `-p` for a password or paths.
- `--force` as the confirmation skip on `issue delete` and `doc delete`.
- `--description-replace-old` and `--description-replace-new`.
- `lll doc link`, `lll doc unlink` and `lll finding read`.

Upgrading names the replacement for each.

### Security

- The API no longer answers `Access-Control-Allow-Origin: *`, and `lll up`
  no longer uses the well-known administrator pair `admin@local.dev` /
  `admin-local-123`. Together they let any web page that the user visited
  log in to a local board as the superuser and read the token (LLL-676).
  - Cross-origin browser reads of the API, direct or through the board's
    `/api/`, are refused unless `LLL_ALLOWED_ORIGINS` lists the origin. The
    board, `/join`, `/me` and the CLI need none.
  - On a loopback bind, the board and the API answer only `localhost`,
    `127.0.0.1` and `[::1]`, so a DNS-rebinding page gets 403.
  - The first boot generates the administrator password into
    `.lll-admin.json`, and the banner names the file, not the password. A
    boot that sets `LLL_ADMIN_PASSWORD=admin-local-123` explicitly keeps it
    and is warned on every boot. A server that `lll up` reuses rather than
    starts keeps its old password until `lll up` starts it. Rotation does not
    undo what a page may already have done with the old password: review the
    superusers, members and tokens of a board that ran on it.
- The web board refuses every request other than GET or HEAD unless its
  `Origin` is the board's own address. Before, a page on another port of the
  same host counted as the same site and could change issues, settings and
  bots with the viewer's board cookie. A request with no `Origin`,
  `Origin: null`, or `Sec-Fetch-Site` other than `same-origin` is refused.
  The API under `/api/` is unchanged. The invite name form and the sign-in
  confirm page send `Referrer-Policy: same-origin`, which also fixes the
  confirm page's "Sign in" button (LLL-630).
- An archived team is read-only on the server for every writer. Writes to
  its issues, comments, claims, docs, labels, projects and webhooks, and
  moves into or out of it, answer 403 naming `lll team unarchive KEY`. A
  claim held when the team is archived cannot be released or renewed until
  it is unarchived; the hourly sweep still frees it (LLL-660).
- An issue can be assigned only to a member who can see its team, by every
  route. A member narrowed later keeps the issues already assigned (LLL-670).
- The board renders an issue only under its own team's route; other paths
  redirect, and a scoped viewer who cannot see the team gets 404. Favorites
  and saved views are written only by the board login, as itself (LLL-664).
- Only a person with read-write access to every team, or a superuser, can
  create an invite. Invites that a narrower member made earlier and nobody
  has used no longer redeem, and narrowing a full member voids its unused
  invites (LLL-629).
- A reference stays inside one team for every writer: an issue's labels,
  project and blockers, a doc's issues and a webhook's project. Moving a
  record to another team is refused while it would reference across teams.
  Older references remain; `scripts/audit_cross_team_refs.py` lists them
  (LLL-631).
- A team-scoped member can no longer read another team's label names or
  issue titles through a relation filter. Through a multi-valued relation, a
  back-relation or `@collection`, a filter needs an any-match operator
  (`labels.name ?~ 'x'`); a stored relation id may only be matched exactly;
  neither can be sorted on. A filter through favorites or saved views is
  refused for team-scoped and read-only members. This covers record lists
  and realtime subscriptions (LLL-634).
- Team keys can no longer carry quotes, `$( )`, spaces or control
  characters into URLs, filenames and shell-pasted bot prompts (LLL-628).
- A webhook's secret is write-only: the API, realtime and the CLI never
  return it. `lll webhook add` prints a generated secret once, or takes
  yours with `--secret`. Upgrading hides existing secrets but does not
  rotate them, so remove and add any webhook whose secret a guest could read
  (LLL-661).
- A webhook records its creator and delivers only while that member can read
  the webhook's team. Webhooks created before this change deliver while their
  team exists. Deliveries are not queued (LLL-661).
- A member's comment is authored by that member, and only its author may
  edit or delete it; a superuser still moderates.
  `lll issue comment edit/delete --force` works only with a superuser token.
- Comments the server writes (the forced-release record and the expiry note)
  are locked: no request may edit one, and no member may delete one
  (LLL-512). `author_kind` cannot be set by any request (LLL-654).
- A forced-release or expiry comment names a member only when everyone who
  sees the issue's team may see that member (LLL-633).
- An API delete of a claimed issue is refused for every caller (LLL-662).
- `--admin-password` and `--admin-email` are no longer copied into the
  process environment, where child processes inherited them (LLL-646).

### Fixed

- With no team configured, `label edit`, `label delete`, `project edit`,
  `project delete` and `project view` acted on the first team's record with
  that name, so `lll label delete bug` could delete another team's label.
  The list verbs' name filters (`issue list --label`, `--project`,
  `watch --label`, `issue next --exclude-label`) now match in every team
  (LLL-671).
- `issue list --ready`, `--blocked`, `issue next` and `watch --ready` use one
  readiness rule. A blocker that the reader cannot see counts as open, and
  `issue view` shows it as "a hidden issue" (LLL-672). Issues in archived
  teams are never ready (LLL-679).
- `issue list --ready` and `--blocked` read every page before filtering,
  instead of only the first 200 issues (LLL-673).
- `issue view` prints each blocker under its own team's key (LLL-674).
- `lll issue next` skips a claimed issue even when its assignee was moved or
  cleared (LLL-662).
- Live board updates no longer go stale after the board's realtime stream
  reconnects, and one slow refresh no longer holds up every viewer
  (LLL-666).
- The hourly claim-expiry sweep re-checks each claim inside its transaction,
  so a renewal that lands mid-sweep keeps the claim (LLL-663).
- A doc stored with no kind renders on the board instead of failing
  (LLL-635).
- The API port's `/.well-known/lll` always answers `service` and `version`,
  so a CLI pointed at the API port warns about version skew too (LLL-652).
- Login token renewal runs when `LLL_URL` names exactly the home config's
  url (LLL-653).
- `lll up` names the repo's `.lll.toml` token first when that is the one
  refused, instead of only `lll logout` (LLL-649).
- The expiry line under a bot token names `lll bot rotate bot-NAME`, not the
  superuser-only `lll token create` (LLL-625).
- `member set-password --old-password` with a revoked or expired token exits
  6 with the not-authenticated message (LLL-679).

## [0.8.0] - 2026-10-07

Scoped access is complete for teams: a single-use link invites a person to
chosen teams, the web board signs them in as themselves and shows only those
teams, they can add their own agents from the board, and they see only the
members they share a team with.

### Added

- `lll invite create --team KEY [--ro]` prints a single-use `/join/<code>`
  link that expires after 7 days. Opening it creates a person member with
  exactly the invite's teams and mode and signs the browser in. Only a
  read-write member can mint one, and never for more than it can see itself
  (LLL-544).
- The web board accepts a member's own token as its cookie. A scoped member
  sees only its teams in the rail, pages, search and live updates; another
  team answers like a missing one. A read-only member cannot write. Removing
  or narrowing a member closes its open live stream within seconds (LLL-545).
- "Add a bot" on the board creates `bot-NAME` owned by the signed-in member,
  with the member's teams and mode, and shows a copyable agent prompt once
  (LLL-546).
- `lll member --help` has a "Who sees whom" section.

### Changed

- A team-scoped member now sees only itself, members who share a team with
  it, and people with access to every team. Bots appear only when they share
  a team, and the only email it sees is its own. Anyone else prints as
  `hidden member` in the CLI and on the board. Full-access members see what
  they saw before (LLL-551).
- `lll bot` prints the token inside a paste-ready agent prompt. Use
  `lll bot bot-NAME --env` for only the two `export` lines, for example
  `lll bot bot-x --env > agent.env`. Scripts that parsed the old
  `LLL_TOKEN=` line must switch to `--env` (LLL-546).
- `lll member add bot-x` refuses before any server call and names
  `lll bot bot-x` (LLL-546).
- Board sign-in from a link is a confirm page and a POST with an origin check,
  so another site cannot sign your browser in to someone else's board
  (LLL-545).

### Known issues

- Comments the server writes on a forced release or claim expiry contain the
  holder's name, so a scoped member can read a hidden holder's name there
  (LLL-633).

## [0.7.0] - 2026-10-07

Members can be scoped to teams, one member can run a fleet of labelled agents,
and a `lll login` token now renews itself instead of dying after five days.
Several retired flag spellings are gone; see Removed before upgrading scripts.

### Added

- `lll upgrade` upgrades lll the way it was installed: a Homebrew install runs
  `brew upgrade lll`; a release download or a checkout build prints the
  command to run. lll never replaces its own binary. `--dry-run` prints only.
  The version-skew warning now points at it (LLL-608).
- The CLI warns when the server is newer than it, so a missing command reads
  as version skew rather than a typo (LLL-607).
- A `lll login` token is renewed and saved when a command runs in its last
  24 hours, so an agent session no longer stops mid-work five days after
  login. Tokens from `LLL_TOKEN` or `lll token create` are left alone
  (LLL-441).
- Members can be scoped to teams: `lll member invite NAME --email E --team KEY`
  gives a person one team, read-write or read-only, and a scoped board link.
  Existing members keep access to every team. Bots inherit their owner's
  scope (LLL-522, LLL-542, LLL-543).
- `--agent NAME` labels claims and comments, so one member can run a fleet of
  agents and still tell them apart (LLL-521).
- Comments and docs record an author kind (person or bot) and the bot's owner,
  shown in the CLI and on the board (LLL-610, LLL-618).
- `lll issue claim --renew` extends a claim you hold. Only the holder releases
  a claim; `--force` takes someone else's and comments on the issue
  (LLL-512, LLL-535).
- `lll issue next` takes `--project`, `--label` and exclusion filters, and
  `--json` returns the claimed card in one packet (LLL-611).
- The board: a Project filter, keyboard shortcuts (`?` for the sheet, `/` for
  search, `g` chords), and settings, search and create dialogs that fit a
  phone (LLL-523, LLL-531, LLL-532).
- Unknown flags name the nearest real flag, and `issue view` prints
  `Comments: none` (LLL-553).

### Changed

- `issue update --description-replace "old=new"` replaces exactly one match
  and composes with `--description-append`. The legacy old/new pair remains
  accepted for one release, hidden from help, with a deprecation hint (LLL-506).
- `finding view`/`finding read` and `doc link`/`doc unlink` are hidden
  aliases: they still run, but no longer appear in help, completions or docs.
  The documented spellings are `doc view SLUG` and
  `issue link/unlink KEY-123 SLUG`. `finding read` runs again after LLL-503
  retired it (LLL-505).
- Creation and deletion read `create` and `delete` on every noun. `new`, `add`
  and `remove` still run as aliases (LLL-504).
- `lll up` refuses a non-loopback bind when no `LLL_BOARD_TOKEN` is set.
  `lll up --bind` is unaffected because it sets one (LLL-450).
- `lll export` reads the team's comments once instead of once per issue
  (LLL-540).
- `lll watch` on a revoked token now fails loudly instead of reporting itself
  reconnected (LLL-617).
- `issue update --assignee none` no longer releases another member's claim
  without `--force` (LLL-516).
- The board label picker adds and removes single labels, so it no longer
  drops a label added concurrently from the CLI (LLL-519).
- The home config (`~/.config/lll/lll.toml`) is written to a temp file and
  renamed into place, so a concurrent reader never sees it empty; a symlinked
  config is written through its link (LLL-441).

### Removed

- Retired alternate spellings (LLL-503). Use the canonical form:
  `--assign` -> `--assignee`; `-m`/`--message` -> `-b`; `--query` ->
  `--search`; `--for` -> `--until`; `read` -> `view`; `lll up --local` ->
  `lll up --scratch`.

### Security

- Only a superuser can create claim records directly; members claim through
  `lll issue claim` (LLL-515).
- A bot's `owner` cannot be changed after creation. Before, any read-write
  member could make itself a bot's owner and rotate the bot's token (LLL-616).

## [0.6.1] - 2026-09-19

Local boards can now be disposable or shared with a small team without
inheriting a hosted connection or assembling credentials by hand.

### Added

- `lll up --scratch` (`--local`) creates an isolated throwaway board with fresh
  ports, data, and config. It ignores inherited `LLL_*` values, home config,
  and the caller's `.lll.toml`, and prints the temporary CLI connection
  (LLL-487).
- `lll up --bind LAN_OR_TAILSCALE_IP` starts a shareable board on that address,
  advertises a reachable board/login URL, and keeps random administrator and
  browser-gate secrets private across restarts. An inherited hosted URL or
  token cannot redirect this explicit local boot (LLL-497).
- `lll member passes --count 10` creates distinct human members and one-year
  API tokens, then writes a private `0600` handoff file with each person's
  credential and the shared board login link. Browser edits still use the
  board process identity (LLL-497).

## [0.6.0] - 2026-09-19

The CLI now uses one authenticated member identity, and retries of issue
creation can be made safe with a caller-supplied key.

### Removed

- The separate `me` / `LLL_ME` identity setting, its setter, and mismatch
  warnings. Old config keys are ignored; `whoami` reports the member in the
  token and its source (LLL-445). Scripts that set `me` should drop it.

### Added

- `lll issue create --idempotency-key KEY` reuses an issue when the same team,
  key and creation body are retried, and refuses a changed body with 409. A
  keyed create checks server support before writing; unkeyed creates keep their
  existing behavior (LLL-438).
- `lll issue list --since` catches up on recently changed issues, document
  lists can filter with `--kind`, and search accepts a one-command `--team`
  override (LLL-439, LLL-440, LLL-483).
- Label creation accepts `--color`; GitHub issue import can set a default
  emoji for imported issues (LLL-470, LLL-469).
- `lll up --admin-ui` explicitly exposes the local administration UI. The
  default board no longer serves that UI or prints administrator credentials
  in its startup banner (LLL-372).

### Changed

- A locally started board authenticates as a member and renews that member's
  identity after token revocation, including its realtime subscription.
  Supplied member tokens remain authoritative (LLL-445).
- Saved member-token config files are private to their owner, including
  existing files rewritten by the CLI (LLL-475).
- `issue view` fetches independent records concurrently while preserving
  output and errors. Member, team, project and label lists read every page
  instead of silently stopping after 200 records (LLL-436, LLL-476).
- `issue next` stays within its selected team; project and label moves check
  all referencing issues before proceeding (LLL-477, LLL-479).
- HTTP reads reject incomplete response bodies. A failed saved-view refresh
  retains the previous rail content instead of clearing it (LLL-478, LLL-480).
- The landing page downloads the latest published release, and its demo board
  screenshot shows the current interface (LLL-459, LLL-425).

## [0.5.0] - 2026-09-17

A Markdown mirror of the board, and quicker ways to reach what is on it.

### Added

- `lll export [DIR]` exports a team's issues, documents and attachment bytes
  as Markdown. `lll import dir DIR` imports that mirror into an empty team;
  `--replace` explicitly deletes the team's existing issues first. Comments
  export but do not import, preserving their original authorship (LLL-454).
- Cmd+K opens a command palette from any board page to jump to an issue,
  document, section or team (LLL-447).
- `software-factory` and `codebase-skills` ship as built-in skills: the map
  of the development workflow and the interview for adapting it to a repo.

### Changed

- Settings are grouped into six sections by the scope of the change (LLL-446).
- Claim expiry leaves a comment on the issue explaining the automatic release
  (LLL-452). Raw issue output uses absolute comment timestamps (LLL-453).
- Filter menus scroll, and dimensions with many options offer search
  (LLL-451, LLL-455).
- Issue view fetches eight requests instead of eleven (LLL-436).
- `lll up` can use its local superuser credentials when the configured member
  token belongs to another server. It opens the board's login URL, including
  on loopback (LLL-443, LLL-444).
- A configured `me` is advisory when a member token supplies the authenticated
  identity (LLL-445).

## [0.4.0] - 2026-09-17

Optimistic edits that hold at the server, and a first run that has something
on it.

### Added

- `If-Unmodified-Since` on `PATCH /api/collections/issues/records/{id}`: pass
  the `updated` stamp your read returned and the server answers 412 — without
  applying the write — when the record has changed since, naming the stamp to
  retry with. `lll issue update --if-unchanged-since` sends it, so an edit
  can no longer land on a record someone changed between the CLI's read and
  its write; the check used to run on the client, and the round trip was the
  race. The header applies to the `issues` collection; without it a PATCH
  behaves exactly as before (LLL-399).
- `lll up --demo`: a first run with something on it — a seeded board that
  teaches the tool and doubles as a rubric (LLL-433).
- The board's /search reaches docs: findings and decisions get result rows
  linking to their doc page, so the board answers "have we hit this before"
  the way the CLI does (LLL-398).
- A team can carry an emoji beside its key: `lll team set-emoji GLYPH` (or
  the settings field), shown in the rail next to the accent, so a multi-team
  board says which team you are reading at a glance (LLL-427).
- The gate verifies `lll api --schema` against the migrations: a reference
  that no longer matches what the server enforces fails CI naming the drifted
  lines — it had described a schema nobody has through two releases, with
  every gate green (LLL-435).
- `lll skill get merge-gate`: a skill for the half after the pull request —
  what to verify once CI is green, and how to land without eating anyone's
  state (#100).

### Changed

- `issue update --if-unchanged-since` cannot be combined with `--assignee`:
  assignment writes go through the claim route, which arbitrates with its own
  claim stamp, and a precondition that silently stopped guarding would be
  worse than none. Run them as two updates (LLL-399).

## [0.3.2] - 2026-09-16

What a team is on a server that has more than one, and what happens to a
hold when the agent that took it is gone.

### Breaking

- **Team keys are uppercase.** They were stored as typed, so `eng` and `ENG`
  were two teams the unique index was happy with and prose could not tell
  apart, while the derived issue key, the rail and the docs all assumed
  uppercase. Normalised on write in the server, so the raw API obeys it too,
  and on lookup, so `LLL_TEAM=eng` and `/t/eng/` resolve rather than fail. A
  migration uppercases existing rows; a key whose uppercase form is already
  taken is left alone rather than merged, because the two teams own separate
  issues (LLL-235).
- **A claim older than 24 hours releases itself.** The server sweeps hourly
  and frees holds that outlived the agent that took them, clearing the
  assignee exactly when a deliberate `issue release` would - only when it is
  still the holder. Nothing announces it; if you mean to hold an issue for
  longer than a day, say so on the issue (LLL-183).

### Added

- Documents have an address: `/t/KEY/doc/SLUG` renders a decision, finding,
  PRD or wiki page with its markdown, kind, slug, retrieval coordinates and
  linked issues, and answers `?raw` with the source. Decisions and findings
  were the one record kind reachable only from a terminal, which is where
  "why is this like this" is usually asked. An issue's related findings now
  link to it (LLL-405).
- `lll label move NAME --to KEY` and `lll project move NAME --to KEY`, with
  a team select on each settings row. The scope was write-once, so a label
  created in the wrong team could only be deleted and remade - losing every
  issue that referenced it. The move is refused while issues outside the
  destination still reference the record, and names them (LLL-100).
- Findings carry a confidence: a suspected or refuted finding says so
  wherever it renders (LLL-396).

### Changed

- `issue list --sort priority` leads with the most urgent work, and
  unprioritised issues sort last in either direction - absent is not a
  priority below low. It also fetched the wrong page before: the first
  `--limit` rows of PocketBase's numeric order, so on a board with more
  unprioritised issues than the limit the urgent ones were never read at
  all (LLL-382).
- The issues table, the projects list and settings answer for the team in
  the URL rather than the one the server booted with. On a multi-team server
  every other team's name, accent, labels and projects were uneditable on the
  web, and the rail moved the current-team marker under the reader (LLL-426).
- Moving one card reads one column instead of the whole team (LLL-428).

### Fixed

- Related findings and comments no longer draw on top of each other on the
  issue page (LLL-424).
- `mise run seed` and `mise run api-schema` isolate their config root, not
  just `HOME`: `XDG_CONFIG_HOME` outranks it, so on a machine exporting one
  they read the developer's own config and died against a throwaway database
  (LLL-423, LLL-430).
- `lll api --schema` describes the schema the server actually has: bot
  member fields and the webhooks collection had been missing since they
  landed (LLL-430).

## [0.3.1] - 2026-09-16

### Fixed

- `lll --version` reports lll's version. It ran `git describe` at startup
  and answered with whatever repository the caller stood in, so the 0.3.0
  binary said `lll 0.2.0` outside a checkout, and `lll 9.9.9` inside a
  project tagged `v9.9.9`. The version is a literal now. The gate asserts
  it matches `[project] version` in lisette.toml, and that the answer is
  the same inside the checkout and outside it.

## [0.3.0] - 2026-09-15

The release shaped by several agents working one board at once: a command
that says what to work on next, identities that are not people, events that
leave the process, and the operating instructions carried in the binary.

### Breaking

- **Repeated `--state` and `--label` mean the union.** `--state todo
  --state in-progress` returns both. It used to keep the last one silently
  and drop the rest. A flag repeated where repetition means nothing is now
  refused instead of ignored.
- **`me` no longer mints members.** A `me` naming nobody used to create
  that member on the spot, which is how a board fills with identities
  nobody chose. It is now an error that names the fix.
- **Deleting a member requires admin authority.** Migration
  `1789200000_member_delete_admin.js` sets `members.deleteRule = null`.
  Deletion is refused for ordinary tokens, and checked against assignments
  and comment authorship first.
- **Claims, releases and assignment edits are one server transaction.**
  Deploy the server before you distribute the client. An older server
  refuses these writes and names the upgrade. It does not fall back to an
  unsafe two-request write. The endpoints commit the claim and every
  accompanying issue field together, against an observed claim id.
- **`lll up` serves one address.** The separate `:8091` API service is
  retired. The board proxies `/api/` and `/_/` on its own port.

### Added

- `lll issue next` prints the one issue to work now: ready and unclaimed,
  then priority, then oldest, then most-unblocking. `--claim` takes it, so
  an agent starts work in one command. `lll watch --ready` streams the same
  agenda as it changes.
- `lll webhook add|list|remove`: the server POSTs issue events to your
  URLs, with bounded retries and backoff for deliveries that fail.
- `lll api METHOD PATH`: authenticated passthrough to the board's
  PocketBase API. `--schema` prints the collection and field reference. It
  reaches what the CLI does not wrap, without the admin UI.
- `lll bot NAME`: an agent identity in one command, member and token,
  printed once. A bot member cannot log in, is owned by a person, is badged
  on the board, and is rotatable.
- `lll import github OWNER/REPO` brings a GitHub backlog in through `gh`:
  title, body, labels and state, each issue carrying its `gh#N` ref.
  Re-importing skips what it already brought.
- `lll skill list` and `lll skill get NAME`. The agent operating
  instructions ship inside the binary. An agent working from another repo
  reads them without this checkout.
- Attachments: `issue attach KEY FILE`, `issue unattach`, `issue cat`, and
  upload from the board. Files are protected, appended rather than
  replaced, and refused to anonymous readers.
- Surgical description edits: `issue update --description-replace-old/-new`
  and `--description-append`. `--if-unchanged-since STAMP` refuses a write
  when someone edited the issue first.
- Homebrew distribution: `brew install escherize/lll/lll`. The release
  workflow renders the tap formula and pushes it.
- Provenance: an issue records its creator, and the host, path, branch and
  commit it was created from. Both show on the board and in exports.
- `lll issue pr` records `gh#N` on the issue once `gh` confirms the pull
  request, and adopts the existing one when the branch already has it.
- Smaller additions:
  - `doc list --search`
  - `doc link` and `doc unlink`
  - `finding list --limit`, and a positional finding slug
  - `-l` for `--label`
  - `issue list --page N`, and sorting by title
- `lll login --url` discovers and persists the board's advertised endpoint
  through `/.well-known/lll`. An older server falls back to manual
  configuration.
- `LLL_CONFIG_HOME` chooses the config root, for harnesses that cannot set
  `HOME`.
- The board shows live claims, and can claim and release.
- Docs have an address. `/t/TEAM/doc/SLUG` renders a decision, finding, PRD
  or wiki page through the renderer that issue descriptions use, with the
  properties `doc view` prints beside it. A decision can now be linked to
  from an issue or a review. Read-only for now.

### Changed

- The board renders every issue in the team. Past roughly 200 it used to
  truncate silently. Pagination, ordering and live updates now hold across
  a full board.
- The saved column view rides a cookie the server reads on first paint, so
  the board no longer shows the wrong columns before correcting itself. The
  webfont is cached rather than refetched, for the same reason.
- The 401 board gate takes the token in a field, instead of only explaining
  where the token lives.
- Issue table columns are measured in grapheme display cells, so emoji and
  wide characters line up.
- Errors say what to do. Rejected edits restore the authoritative values,
  board write failures name themselves instead of vanishing, and creation
  errors appear inside the dialog that raised them.
- `cmd+enter` sends a comment, and a successful send clears the box.
- The e2e suites run from outside the checkout. A gate no longer writes to
  the tree another agent is reading, including the tracked `.lll.toml`.

### Fixed

- **An issue description could kill the board.** The hover preview capped
  on byte length and sliced on rune indices. A description of about 100
  accented characters, or 60 emoji, panicked a goroutine outside any HTTP
  handler, and the server process died.
- **`watch --json` panicked on any multi-byte record.** One emoji in the
  payload ended the stream, for the same reason: byte length fed to a rune
  index.
- Related findings and comments no longer draw on top of each other on the
  issue page. Both claimed one named grid area, so a single cell held two
  sections. The markup was correct; only the geometry was wrong.
- The last hidden column can be shown again. Unhiding it no longer restores
  the hide from the saved view.
- An expired boot token is re-minted, as a rejected one already was.
- `mise run scratch` and `mise run seed` read their own isolated config.
  Moving `HOME` stopped being enough once `LLL_CONFIG_HOME` and
  `XDG_CONFIG_HOME` outranked it. On a machine that exports the XDG one,
  both read the developer's real token.
- `issue list --sort priority` leads with urgent and leaves the
  unprioritised last. PocketBase sorts on the stored number, where `none`
  is 0, so the ascending fetch led with untriaged issues and buried the
  urgent ones. The order also decided which page you got: urgent work past
  `--limit` left the list entirely.
- `issue update --project ""` clears the project, `--` ends options in
  every verb, and search results supersede stale in-flight queries.

### Removed

- The `:8091` API service, the retired generated-typedef patch script, and
  the `private-sync` skill.

## [0.2.0] - 2026-09-08

The release shaped by running lll against thirty agents at a time, ten
tasks over, and fixing what they tripped on; then by moving the project's
own tracker onto lll.

### Breaking

- **Identity comes from the token.** The author of every write is the
  member the token names; a `me` that names someone else is refused with
  both names. A superuser token names nobody, so `me` attributes there as
  before. Fleets mint one token per member (`lll token create NAME`).
- **Anonymous record requests get a 401.** PocketBase applied rules as
  filters, so a request with no token read as an empty board. Rules are
  unchanged; the refusal comes before the lookup and leaks nothing.
- **`issue start` sets the state and nothing else.** The git branch switch
  and the work-site stamp are behind `--branch`. It used to switch whatever
  checkout it was run from.
- **A claim owns the assignee.** `issue update --assignee NAME` on an issue
  someone else holds is refused naming the holder; `--assignee none`
  releases the claim as well. Claiming what you already hold succeeds.
- **The silent re-mint is the board's alone.** A CLI holding the admin pair
  no longer upgrades a dead member token to the superuser under the covers;
  it gets the honest refusal.

### Added

- `lll search TEXT`: full-text search over issues, comments and docs, ranked
  (BM25 with a title weight, phrase and all-terms bonuses, a key pins its
  record), grouped by what you would open, each hit with the matching line
  and its neighbours under the source it came from. A local corpus cache
  under `~/.cache/lll/` with delta sync keeps warm queries under a second;
  `--refresh` refills. The board's `/search` runs the same engine.
- Dependencies: `issue block KEY BLOCKER`, `issue unblock`, "Blocked by" and
  "Blocks" in `issue view`, `issue list --ready` (open, every blocker done)
  and `--blocked`. Self-blocks and cycles are refused.
- `issue watch KEY --until TEXT` blocks until a comment containing TEXT
  arrives, at once if it is already there; `--timeout N` gives up.
- Comments are numbered; `issue comment edit KEY N -b` and `issue comment
  delete KEY N` change your own, `--force` anyone's.
- `issue update --assignee none` clears an assignee.
- `finding view SLUG`, `finding read`, `finding new`, `finding list --search`
  and `-p PATH`; `doc read`, `doc show`, `doc create`; `issue new`.
- `--help` on every verb, and it never runs the verb.
- Every verb dispatches through one command table per noun; help,
  completions and parsing come from the same declaration.
- A flag takes any number of aliases. Added across the fleet runs: `read`
  and `show` for `view`, `--assign`, `-t`/`--title` and `-d` both ways,
  `--body`/`-m`/`--message`, `--query`, `--path`.
- Bare arguments: `issue create "title"`, `member add name`,
  `issue comment KEY "body"`.
- `lll token create --duration`; an expired token is named as expired from
  its own payload, with the re-mint.
- `whoami` works for agent tokens and names a `me` mismatch.
- The board proxies `/api/` and `/_/` on its own port: one address.
- A landing page at `docs/`; a DX review harness; `scripts/import_sidecar.py`.

### Changed

- Error messages name the fix: an unknown flag prints the verb's flag
  table; a plural noun (`lll issues list`) names the singular with the verb
  kept; a flat verb (`lll comment`) names its noun; a sub-verb where the ID
  goes (`comment add KEY`) is told the ID comes first; `--project TEAM` is
  told the team scopes the command; guessed verbs (`assign`, `move`,
  `edit`, `find`) are pointed at the verb.
- Writes say what they did: `Commented on KEY as NAME`, `Updated KEY:
  state=todo, priority=3`, `Claimed KEY for NAME (already yours since …)`.
- The unknown-team error names the file or env var the key came from.
- `issue view` caps the area-matched related findings at five, linked ones
  first and always shown; `--raw` keeps the whole list.
- The board heals its own stale token instead of announcing its team is
  missing.
- The gate never deletes the tracked `.lll.toml`.

### Removed

- The `.private` sidecar tracker. The project's tasks, findings and
  decisions live on its own lll board; the sidecar is archived read-only.

## [0.1.0] - 2026-09-03

First release: issues, teams, members, projects, labels, docs, findings,
claims, the web board over embedded PocketBase, `lll up`, realtime
`watch`, Fly deployment.

[0.6.0]: https://github.com/escherize/lll/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/escherize/lll/compare/v0.4.0...v0.5.0
[0.2.0]: https://github.com/escherize/lll/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/escherize/lll/releases/tag/v0.1.0
