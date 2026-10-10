# Upgrading to lll 1.0: what can break a consumer

> **Question this answers:** I have scripts, agent prompts or wrappers that call `lll` 0.9. Which 1.0 changes can break them, and how do I check?

1.0 promises SemVer for the surface in [`docs/cli-contract.md`](https://github.com/escherize/lll/blob/main/docs/cli-contract.md): exit codes, the `--json` fields it names, the list envelope, and command, verb and flag spellings with their permanent aliases. From 1.0 on, a change that breaks a script built on those needs 2.0. Message wording and help text are not covered.

This page lists every 0.9 -> 1.0 change a consumer can observe. The full history is in [`CHANGELOG.md`](https://github.com/escherize/lll/blob/main/CHANGELOG.md).

## 1. Credentials and which server a token reaches (security, LLL-688)

| Change | Breaks you if | Check |
|---|---|---|
| The token in your home config is sent only to the url saved beside it. If a repo `.lll.toml`, `LLL_URL` or `--url` names another server, commands that need the token exit **6** and name where that url came from. | A repo's `.lll.toml` or `LLL_URL` points at a different server than `~/.config/lll/lll.toml`, and you relied on the home token being sent there. | `lll config list`: the `url` and `token` rows should name the same file, or the token should come from `LLL_TOKEN`. |
| `lll login` without `--url` exits **2** when the url came only from a repo file or `LLL_URL`. | Your setup runs a bare `lll login` inside a repo or with `LLL_URL` set. | Pass `--url` explicitly. |
| Requests no longer follow HTTP redirects. A 3xx is an error naming its target. | Your server sits behind a redirect, such as http->https or a trailing-slash redirect. | Configure the final url. A trailing `/` on the url is now trimmed. |
| `lll up` refuses (exit **4**) to adopt an already-running server at a url chosen by a repo `.lll.toml`, unless your home config names the same url. | You start `lll up` in a repo whose `.lll.toml` names your own running server. | Run `LLL_URL=<url> lll up`. |
| `lll board` won't put the board token into a link to a repo file's `web_url`. | You relied on a repo-file `web_url`. | Set `web_url` in the home config or with `LLL_WEB_URL`. |
| `LLL_URL` + `LLL_TOKEN` pairs keep working unchanged. | n/a | n/a |

## 2. Exit codes

| Change | Was | Now |
|---|---|---|
| Every bad command line is a usage error. This covers: unknown arguments; unknown `skill`/`completions`/`help`/`config get` keys; `issue create` with no title; malformed values (slugs, team keys, URLs, colours, enum flags); a `bot` name without `bot-`; and `lll api METHOD` with no PATH. | 1, or 0 for `api METHOD` | **2** |
| `--help` on any verb, even when required flags are missing | sometimes 2 | **0** |
| `lll version`, `--version` or `-v` with an extra argument | 0 | **2** |
| `lll skill get NAME` for an unknown skill | 1 | **3** |
| `issue update --assignee` on an issue another session holds (needs `--force`) | 1 | **4** |
| `--team` given twice | last one won | **2** |
| An issue key with a signed number (`ENG-+3`) | read as `ENG-3` | **2** |
| A secret flag given `-` with empty stdin: `--password`, `--old-password`, `--admin-password`, `--token`, `webhook add --secret` | varied | **2**, naming the flag |
| `bot create/rotate --env --team KEY` | 0, `--team` ignored | **2** |
| A failed write of a command's output (full disk, read-only stdout), including `--json` and `--env` | 0 (silent truncation) | **1**, with `Error: writing output: …` on stderr |
| Ctrl-C at a hidden password prompt | left the terminal with echo off | **130**, echo restored |

Exit 5 ("nothing to do") is unchanged, but its stderr line now starts with `Nothing to do:`, not `Error:`.

## 3. Which stream carries what

The contract now states it: data on stdout, notices on stderr, and with `--json`, exactly one JSON value on stdout. These notices moved from **stdout to stderr**:
- the `config set` note that LLL_URL or a repo file overrides the value;
- `issue update --assignee <you>`: "assigned, not claimed …";
- `issue comment KEY` (listing): the "waiting for the next one?" pointer;
- `finding near PATH` with no match: "No findings for PATH.";
- the `config list` / `config check` committed-token warning;
- the `login` note that `LLL_TOKEN` is set in this shell.

Also changed:
- `issue next --claim --json` prints no "Claimed" notice, and `issue start --branch --json` prints no Git lines. The JSON carries both.
- `bot create --env` and `bot rotate --env` print nothing on stderr.
- A piped `login --token -` no longer prints `Token: ` into the pipe.
- When a command fails, output it had already produced is printed first, then the error.

**Check:** grep your scripts for `2>&1` on lll calls that parse the output, and for text matched against any of the lines above.

## 4. Text output your scripts may parse

| Change | Before | After |
|---|---|---|
| `issue update --priority` confirmation | `priority=2` | `priority=high` (the name) |
| `issue view` claim row | omitted when unclaimed | always printed, as `Claimed:   none`; `--raw` prints `- **Claimed:** none` |
| `doc view` / `finding view` | `Confidence:` shown only when not confirmed | `Confidence: <word>` always; list lines tagged `[confirmed]` too |
| Renames | short confirmation | `Renamed label A -> B` (and the same for project and team) |
| Finishing a claimed issue by any path (`close`, `update --state done/cancelled`, board, PATCH) | only `close` released the claim | releases the holder's claim and keeps the assignee. `--keep-claim` opts out. The text says `released your claim (assignee kept)` |
| `issue next` with nothing to offer | "the agenda is empty" | names the reason: all claimed, all assigned, or all blocked (`no other ready issues` when you hold one) |

If you parse text, switch to `--json`. That is the covered surface.

## 5. `--json` additions (additive)

- Issue JSON adds `creator_name`, `assignee_name`, `project_name` and `label_names`. Doc and finding JSON add `author_name` and `last_editor_name`. A member you cannot see appears as `"hidden member"`. Ids and `expand` are unchanged.
- `doc view --json` has `last_editor`.
- Verbs that gained `--json` include `issue attach`, `detach`, `release`, `ref`, `block`, `unblock`, `link`, `unlink`, `doc edit`, `finding confirm`, `finding refute`, `project create`, `edit`, `move`, `label edit`, `move`, and `team rename`, `set-accent`, `set-emoji`, `archive`, `unarchive`.

## 6. Flags and values

- `-` on `member create --password` and `webhook add --secret` now reads stdin. It was taken as the literal value.
- `-` on any secret flag on a terminal prompts with echo off. `member create --password -` asks twice.
- `--assignee ''` means `none` on `issue update`. It was exit 2.
- `issue update --claim` exits 2 and points at `lll issue claim KEY`.
- New: `doc create -k finding --confidence`, `doc edit --confidence`, `issue update --keep-claim`, and `member list --team KEY`.
- New hidden aliases: `issue read`, `doc read` and `finding read` for `view`; `config show` for `config list`; `issue comments` for `issue comment`.

## 7. Server and data (deploy the server first)

- The server runs five migrations on first boot. Back up `pb_data` first. Upgrade the server before the clients.
- Issue keys are never reused. After deleting the highest-numbered issue, the next key is one higher than 0.9 would give.
- The server chooses issue numbers. **`lll import dir` keeps a mirror's numbers only with a superuser token.** Run as a member, it renumbers and prints `ENG-5 -> ENG-9`.
- Only a superuser or the member itself renames a member, and only a superuser renames a bot.
- An issue's `creator` and `origin`, a member's owner, and a favorite's or saved view's member are fixed at creation. A PATCH naming `creator` or `origin` answers 404. A comment cannot move to another issue (400).
- A 1.0 CLI against a 0.9 server reports a bot-owner refusal as an admin-credentials refusal (exit 4), and refuses a description edit combined with `--assignee`.

## Quick self-check for a consumer

```sh
# 1. Token and url from the same place (or LLL_TOKEN)?
lll config list
# 2. Scripts that parse text or merge stderr into stdout
grep -rnE 'lll [a-z].*2>&1|priority=[0-9]|agenda is empty|^Error: ' your-scripts/
# 3. Exit-code branches written for 0.9's 1 that now get 2, 3 or 4
grep -rnE 'lll .*; *(if|\[\[).*(\$\?|-eq) *1' your-scripts/
# 4. Literal '-' passed as a password or secret value
grep -rnE -- '--(password|secret|admin-password|old-password) +-( |$)' your-scripts/
```
