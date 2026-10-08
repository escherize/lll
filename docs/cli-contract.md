# The lll CLI contract

From 1.0.0, lll follows SemVer for the parts of the CLI listed here. Changing
one of them in a way that breaks a script needs a new major version. Anything
not listed here can change in a minor release.

Covered:

- exit codes;
- the JSON that `--json` prints, for the fields this page names;
- the list envelope;
- command, verb and flag spellings, including the permanent aliases below.

Not covered:

- the wording of any message, error or help page;
- `collectionId`, `collectionName`, `expand` and any JSON field this page does
  not name;
- the PocketBase collections that `lll api` reaches (see below).

## Exit codes

Every failing command exits with exactly one of these codes. Branch on the
code, not on the error text.

| Code | Meaning | Examples |
|---|---|---|
| 0 | Success | |
| 1 | Error | server failure (5xx), server unreachable, a rejected value |
| 2 | Usage: the command line, or a setting that stands in for a flag (`LLL_SORT`, `LLL_AGENT`) | unknown noun, verb or flag; a missing or malformed argument (`'nope' is not an issue ID`) |
| 3 | Not found | no such issue, doc, team, label, project, member or webhook; an issue outside your teams |
| 4 | Refused or conflict | the claim is held by someone else; release or renew without the claim; closing or deleting a claimed issue without `--force`; creating a bot that exists; a read-only member writing; an `--if-unchanged-since` mismatch; a declined delete confirmation |
| 5 | Nothing to do | `lll issue next` with an empty agenda |
| 6 | Not authenticated | no token, or an expired, revoked or corrupted token |

`--help` and `-h` exit 0 and print to stdout.

`lll api` exits 0 on any HTTP answer, so a script can read the status line on
stderr and the body on stdout. With `--fail`, an answer of 400 or above exits
with the code its status maps to when the body is the API's own error (it
names its `status`): 401 is 6, 403, 409 and 412 are 4, 404 is 3, anything
else is 1. Any other error body, such as a proxy's or gateway's, exits 1. The
body still prints.

Errors print on stderr as `Error: ` and a message. The message is for people:
it names the cause and the fix, and it can change in any release.

## JSON output

`--json` prints one JSON value on stdout and nothing else. Messages that a
command prints next to its result go to stderr when `--json` is given.

### Timestamps

Every timestamp is RFC3339 in UTC with milliseconds:
`2026-10-08T03:02:11.982Z`. This covers `created`, `updated`, `expires` and
`redeemed` at any depth, and the claim's `claimed` and `renewed`.

Time flags (`issue list --since`, `issue update --if-unchanged-since`) accept
RFC3339 in any offset and the space form PocketBase stores
(`2026-10-08 03:02:11.982Z`). They compare instants, so
`2026-10-08T05:02:11.982+02:00` and `2026-10-08 03:02:11.982Z` name the same
`updated`.

### The list envelope

Every `list --json` prints one envelope, whatever its flags:

```json
{"items": [], "page": 1, "perPage": 200, "totalItems": 0, "totalPages": 0}
```

- `items` is always an array, never `null`.
- `totalItems` counts every match, not only this page.
- Lists that are read whole (labels, projects, docs, teams, members, webhooks,
  findings, search hits, comments) are one page: `page` 1, `perPage` equal to
  `totalItems`, `totalPages` 1, or 0 when empty.
- `issue list --ready`, `--blocked` and `--sort priority` read every page
  before they filter or order, then apply `--page` and `--limit`.

The envelope is printed by `issue list`, `issue comment KEY` (without a body),
`doc list`, `finding list`, `finding near`, `label list`, `project list`,
`team list`, `member list`, `webhook list` and `search`.

### The issue object

Every issue `--json` prints the same object: `issue list` per item,
`issue create`, `issue update`, `issue close`, `issue start` and `issue claim`
(the issue after the write). `issue view` and `issue next` add `comments`,
`docs` and `findings`.

| Field | Type | Notes |
|---|---|---|
| `id` | string | record id |
| `key` | string | `ENG-12` |
| `number` | number | the 12 in `ENG-12` |
| `team` | string | team record id |
| `title` | string | |
| `description` | string | Markdown |
| `state` | string | `backlog`, `todo`, `in-progress`, `in-review`, `done` or `cancelled` |
| `priority` | number | 0 none, 1 urgent, 2 high, 3 medium, 4 low |
| `assignee` | string | member record id, `""` when unassigned |
| `project` | string | project record id, `""` when none |
| `labels` | array of string | label record ids |
| `blocked_by` | array of string | issue record ids |
| `emoji` | string | |
| `refs` | string | external references |
| `attachments` | array of string | stored file names |
| `creator` | string | member record id |
| `created`, `updated` | string | RFC3339 |
| `claim` | object or null | see below |

`claim` is `null` when nobody holds the issue, and otherwise:

| Field | Type | Notes |
|---|---|---|
| `id` | string | claim record id |
| `member` | string | the holder's member record id |
| `holder` | string | the holder's name, `""` when you cannot see the member |
| `agent` | string | the session label, `""` when none |
| `claimed` | string | RFC3339, when the hold was taken |
| `renewed` | string | RFC3339, when the holder last renewed it |

`issue view --json` and `issue next --json` add `comments` (each a comment
record, below), `docs` and `findings` (each a doc record, below).

### Other records

| Record | Covered fields |
|---|---|
| comment | `id`, `issue`, `author`, `author_kind`, `agent`, `body`, `created`, `updated` |
| doc, finding | `id`, `team`, `slug`, `title`, `kind`, `body`, `area`, `paths`, `issues`, `confidence`, `created`, `updated` |
| team | `id`, `key`, `name`, `accent`, `emoji`, `archived` |
| member | `id`, `name`, `email`, `kind`, `owner`, `scope`, `teams`, `mode`, `team_keys` |
| label | `id`, `name`, `color`, `team` |
| project | `id`, `name`, `description`, `status`, `team` |
| webhook | `id`, `url`, `secret_set`, `team`, `project` |
| search hit | `group`, `kind`, `title`, `state`, `score`, `snippets` (each `label`, `lines`) |

A member's `owner`, `scope`, `teams`, `mode` and `team_keys` are absent when
empty. A comment's `author_kind` is `"system"` on a comment the server wrote on
its own (today only the claim-expiry note, which has no `author`), and absent
otherwise. `project view --json` lists its `issues` as records without `key` or
`claim`; use `issue list --project NAME --json` for the issue object.

`lll watch --json` prints one event per line. Its timestamps are RFC3339;
the event shape (`topic`, `action`, `record`) is not covered yet.

## Empty lists

A list with nothing to show prints one line on stderr, such as `no issues` or
`no labels`, and nothing on stdout. Its exit code is 0. `--json` prints the
envelope with an empty `items` array.

## Spellings

Each noun, verb and flag has one canonical spelling, the one help prints.
These aliases are permanent:

| Alias | Canonical | Where |
|---|---|---|
| `new` | `create` | `issue`, `doc`, `finding` |
| `show` | `view` | `issue`, `doc` |
| `add` | `create` | `member` |
| `remove` | `delete` | `member` |
| `edit`, `update` | each other | `issue`, `doc`, `project`, `label` |

A removed spelling fails with exit 2 and names its replacement.

## `lll api`

`lll api METHOD PATH` is a passthrough to the server's PocketBase API. The
passthrough is covered: its flags, its exit codes, and stdout for the body and
stderr for the status line. What the API answers is not: collection names,
fields, filters and rules follow the server's migrations and can change in a
minor release. `lll api --schema` prints the current reference. For a bulk
read the CLI covers, prefer its `--json`: `lll issue list --json` carries
each issue's claim, so reading claims through
`lll api GET /api/collections/claims/records` is no longer needed for that.
