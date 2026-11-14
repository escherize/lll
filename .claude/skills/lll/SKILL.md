---
name: lll
description: Use lll as the tracker and record for software work - claim a task before writing code, keep the board honest while you work, and leave a trail others can read. Covers the CLI (issues, comments, search, --raw, stdin bodies), the board, and the conventions that make a multi-agent backlog survive contact with parallel work. Use in any repo whose work is tracked on an lll board, and for the claim-before-code / record-what-you-learned conventions. Triggers on "lll issue", "claim a task", "file an issue", "what's on the board", "why did we", "record this decision", "log friction", "audit trail".
---

# Working through lll

> One stage of the loop in `lll skill get software-factory`, which maps all
> six and says what hands to what.

lll is the tracker AND the record. The point is not project management: it is
that six months from now, someone (probably an agent) can ask *why is this like
this* and get an answer instead of a guess.

## Your team and your board

Every command works against one team on one server. `.lll.toml` (written by
`lll attach`, inherited by every subdirectory) names the team; `lll whoami`
shows who you are, which server you reach and what you can do. `--team KEY`
overrides the team for one command without rewriting configuration.

`lll issue list` from a directory with `.lll.toml` is the project's real work list. Findings
are `lll finding list` / `lll finding near PATH`, decisions are `lll doc list`
(kind decision), the backlog is the issue list.

Your repository's own instructions (AGENTS.md, CLAUDE.md, a repo skill) may
add specifics: the gate command, local skills, a scratch board. Where they are
more specific than this skill, they win.

## Before nontrivial edits

Read the issue and its comments, then consult findings for the paths you plan
to touch (`lll finding near PATH`) and decisions relevant to the change
(`lll doc list -k decision --search TOPIC`, then `lll doc view SLUG`). Record
the applicable constraints briefly on the issue before editing. Select context
for this task rather than loading the whole board. If there are no relevant
records, proceed without inventing one.

## The loop

```sh
lll issue list --state todo            # what is open
lll issue view KEY-12                  # read it FULLY before you touch anything
lll issue claim KEY-12 --agent YOUR-SESSION  # refuses another session
lll issue start KEY-12 --agent YOUR-SESSION
# ... work ...
lll issue comment KEY-12 --agent YOUR-SESSION -b "what changed and why"
lll issue close KEY-12 --agent YOUR-SESSION  # after delivery; releases your claim
```

`claim` atomically acquires an issue for the member authenticated by your token.
A successful claim is immediately visible on the server; no Git push is needed.
If another member holds it, the command exits nonzero without taking over.
Claiming your own issue again succeeds and says it is already yours.

**The claim is exclusive per member, not per agent, unless agents label
themselves.** Agents that share one member token share every claim: each
one's `claim` succeeds with "already yours" and exits 0, so the claim does not
stop two of them working the same issue. Give each session a label with
`--agent NAME` or `LLL_AGENT` (on `issue claim`, `issue next --claim`, `issue
comment`, `issue close`, `issue start` and `issue create`): a claim by the
same member under a different label exits nonzero and names the holder's
label, and so do `--renew`, `issue release` and `issue close` without
`--force`. An unlabelled claim or
hold still matches any label, so every sharing session must set one. The label
is self-asserted coordination, not auth, and is at most 64 characters from
A-Z, a-z, 0-9, `.`, `_` and `-`. For a fleet, you can instead give each
long-lived worker its own member (`lll member create <name>`, then
`lll token create <name>` with admin credentials). If workers share a token
without labels, each one reads `lll issue view KEY-12` (claim holder, comments,
recorded work site) before it starts, and skips any issue another session is
already on.

`--assignee` cannot move a claimed issue to anyone but the holder: the holder
releases it first, or you force-release a dead hold (below). `--assignee none`
releases the claim, so it follows the release rule: only the holder clears it
without `--force`, and `lll issue update KEY-12 --assignee none --force --reason "why"`
leaves the same comment a forced release does.
`lll whoami` shows the authenticated identity. `lll issue release KEY-12`
gives your claim back and clears the assignee when it still matches the holder.
Moving your claimed issue to done or cancelled releases your claim in the
same step and keeps the assignee, so the finished issue still says who did
it. One rule covers `lll issue close KEY-12`, `lll issue update KEY-12 --state
done|cancelled` and the board; `--keep-claim` keeps the claim on either verb.
Do not follow a finish with `lll issue release`: it also clears the assignee.
Releasing or closing over another member's claim, or a hold under a
different agent label on your own token, is refused unless you add `--force`;
a forced release leaves a comment on the issue naming both members and labels,
with the reason from `--reason "why"` if you give one; it is the releaser's
comment, and the server keeps it: nobody can edit it and no member can
delete it. The note the server leaves when a claim expires carries author kind
`system`. Only a comment's author edits or deletes it. Force
only a hold you know is dead: its holder may still be editing. A claimed issue
cannot be deleted until its claim is released: `lll issue delete KEY-12
--force` releases it first.

**A claim not renewed for 24 hours is released for you**: the
server sweeps hourly and frees holds that outlived the agent that took them,
leaving the issue exactly as a deliberate release would. On an issue that is
not done or cancelled, the sweep leaves a comment naming the holder and how
long they held it; read the comments if a claim you were relying on
has vanished. The 24 hours is fixed on the server, not configurable. To hold
an issue longer, renew before it lapses: `lll issue claim KEY-12 --renew`
restarts the clock on a claim you hold. Plain `claim` on your own
issue does not renew it.

`lll issue start KEY-12` sets in-progress without changing Git. To create a
branch and record its host/path on the issue, use `lll issue start KEY-12 --branch`.
For separate Git commands, `lll issue branch-name KEY-12` only prints a suggested
name; it changes nothing. Once you
are on an issue branch, commands can infer the issue from it:
`lll issue view` with no argument is the issue you are on.

If an orchestrator already claimed the issue for this member and session label,
read the full issue and verify that hold; do not claim it again. Keep the same
label on comments and other work (`--agent YOUR-SESSION` or `LLL_AGENT`). Renew
before the 24-hour limit when continuing a long run. A different label is a
different session: do not take its hold.

## Record it

The commands an agent reaches for most. Each has
`--help` with the full flag list.

```sh
lll issue next --claim             # take the next ready, unclaimed issue (prints its key);
                                   # with none left, resumes your own held one (same --agent)
lll search "claim expiry"          # issues, comments and docs, ranked
lll finding near src/api           # traps already recorded for these paths

# a trap, the moment it costs you time; 'suspected' until you have proof
printf '%s' "$what_happened" | lll finding create port-probe-races \
  -t "Port probe races a sibling server" -a ci --paths scripts/e2e.sh \
  --confidence suspected -b -
lll finding confirm port-probe-races   # once you have proved it

# a choice that constrains future work, written when you make it
printf '%s' "$options_and_why" | lll doc create -k decision \
  -s cache-in-process -t "Cache widgets in process, not in Redis" -b -

lll bot create bot-myrepo          # a member for an agent: prints a paste-ready prompt with its token, once
```

`-a` (area) is conventionally a label's name, so issues carrying that label
surface the doc. `--paths` takes comma-separated paths; `lll finding near` matches
by them in both directions.

## Invite people and their agents

`lll invite create --team KEY --for Alice --for Bob` prints one message to send,
with a separate single-use link for each person. Keep its output; if it fails
partway, preserve completed links and retry only the pending names. `--json`
returns `invites`, `pending` and `complete` for a named group; without `--for`,
the single-invite format stays the same. A lost response can still leave an
unused invite: do not claim that a retry recovers the same link.

Opening a join page does not redeem or validate a link. A signed-in person
accepts into their existing account; an anonymous visitor creates a person.
Their setup page shows the token-based CLI login when
asked, then a command for creating their own bot. They do not need a password.
Skip attachment when the repo already names the correct team and server.
Do not create their bots with the inviter's broader token or copy their personal
tokens into a shared message. No message is sent by the CLI.

## Bots, owners and worker credentials

A bot with a human owner may create a worker with `lll bot create bot-NAME`.
The human remains the owner; `created_by` records the creating bot. A worker
cannot exceed its creator or human owner's access. Narrowing the creator
narrows its workers; losing the shared owner detaches them and strands tokens
the creator minted. A bot without a human owner cannot provision this way.
Bots and owned identities cannot create person accounts to escape that bound.

Use `lll bot rotate NAME` to replace a leaked token, not another create call.
For setup scripts, use `lll bot create bot-NAME --json` or
`lll bot rotate NAME --json`. Each returns one credential object with
`name`, `url`, `token` and `team`.
`team` is empty unless explicitly supplied as handoff context; it changes no
grants. JSON needs no configured team and excludes `--env`.
Only the authorized owner, creator or administrator can rotate; a revoked or
read-only creator cannot mint tokens. Treat token output as a credential, not
a report artifact. Existing API names and covered fields are separate from
these authorization rules: client/server version equality grants no access.

To stop a bot, its current human owner or an administrator uses
`lll bot disable bot-NAME`: existing tokens are retired, access becomes
read-only with no teams, and identity, attribution and written work remain.
Workers it created cannot retain wider access. An administrator can grant
access again; rotating a token alone preserves the disabled access.

`lll bot remove bot-NAME` refuses an identity with references. Prefer disable
when attribution matters. Explicit `--force` permits clearing references,
including assignments and claims; written bodies remain. Workers keep their
human owner and cannot gain access by losing a creator. Their credentials
may need rotation after their owner reviews access. Creator status alone
cannot disable or remove a worker. `--yes` skips only terminal confirmation;
it grants no authority. `--json` returns a receipt, never a credential.
Older servers must refuse these operations before writes.

## What agents specifically need

**Read a URL, not a scrape.** Any command taking `KEY-12` also takes a pasted
board URL. `lll issue view KEY-12 --raw` prints the issue as plain markdown,
which is what you want in a prompt or a pipe. `--json` gives the raw record with
relations expanded.

**Pipe bodies in.** `-b -` reads from stdin, so generated text never
needs a temp file:

```sh
printf '%s' "$analysis" | lll issue create -t "Title" -b -
git log --oneline -20 | lll issue comment KEY-12 -b -
```

**Set an emoji on every issue you create.** The board is scanned, not read, and an emoji
is the only thing legible at card size. This is not decoration: it is how a human sees at
a glance what a column is full of.

```sh
lll issue create -t "e2e flakes on a random port" --emoji 🐛
```

Use the kind of work, not your mood. A small vocabulary beats a large one, because the
value is in the pattern being recognisable:

| emoji | kind |
|---|---|
| 🐛 | bug |
| ✨ | feature |
| ♻ | refactor |
| 📝 | docs |
| 🔧 | tooling, build, CI |
| 🧪 | tests |
| ⚡ | performance |
| 🔒 | security |

**Filter server-side.** `lll issue list` supports `--state`, `--assignee`,
`--label`, `--project`, `--search`, `--sort`, `--limit`, and `--json`. Other
read commands expose their supported filters in `--help`.

**Keep containment separate from blockers.** Create a slice with
`lll issue create -t "Slice" --parent KEY-12`, or reparent one with
`lll issue update KEY-13 --parent KEY-12` (`--parent none` detaches it).
`lll issue list --parent KEY-12` lists direct children; `--under KEY-12`
includes the parent and every descendant. A parent link does not block work.
Progress counts direct children in done or cancelled. Closing with open descendants needs
explicit force and leaves those children open; progress is not verification.

**Choose the events you need.** Plain `lll watch --json` reports issue
changes. `lll watch --activity --json` also reports comment and claim changes
for issues matching the selected team, project and filters. Comment edits and
claim renewal need not advance the issue's `updated` timestamp. For a receiver, use
`lll webhook add URL --activity`; existing registrations remain issue-only.
Webhooks retain their shared-secret header and bounded retries, not a durable
queue. Consumers should ignore unknown topics, actions and additional fields.

Issue-list JSON includes `claim` and `last_activity` for checks without one
read per issue. `last_activity` includes comment and claim writes, renewal and
expiry; it does not change what `issue list --since` catches. Older versions
may omit it: missing means unknown, not quiet.

**Read actor and holder separately.** Activity gives the issue `key` and
`author`, `author_name`, `author_kind`, `agent`. A forced claim release credits
the releaser; the raw claim's `member` is the holder. Expiry is system-authored.
An older server or an indirect operation may have no actor: leave it unknown,
never infer it from the holder. Hidden member names stay hidden.

**Read comments and claims in bulk.** `lll comment list --json` and
`lll claim list --json` read current records across the team's issues;
`--project` narrows the query. Follow the JSON `next_cursor` using `--since`
with the same server, team, project and list until it is empty. Here `--since`
is a continuation, not a date. Totals can change; records added behind a
cursor need a fresh scan. These lists are not a snapshot or change feed;
use `activity` for ordered writes and deletions.

**Watch is live-only; reconcile on start and reconnect.** Subscription readiness
is acknowledged on stderr; JSON events go to stdout. Reconnects do not replay
missed events. Keep the last handled event time and reconcile issue changes
with `lll issue list --since <time>`. That list misses comment/claim-only
activity; `lll activity --since CURSOR` does not. It reads the server's audit
log of every issue, comment and claim write in order, with who made it, and
prints the next cursor on stderr (with `--json`, the last item's `seq`).
Stream silence alone is not proof that the board has not changed.

**Use covered JSON fields.** Issue view and next JSON provide
`blocked_by_refs` (`id`, `key`, `title`, `state`) for visible expanded blockers;
retain raw `blocked_by` ids because an inaccessible blocker may have no ref.
Comments include `author_name`, `author_kind` and boolean `server_record`.
Watch issue events add `key`, `priority_name`, `creator_name` beside `record`.
Use those fields instead of joining names yourself or parsing display text.
Do not assume a new covered field exists in an older client.

**Capabilities are separate from versions.** `GET /.well-known/lll` may list
`issues.idempotency`, `comments.idempotency` and `webhooks.activity`. When an
explicit list omits a required capability, the CLI refuses before writing.
Older servers without a list are checked through feature support endpoints.
Equal version strings do not prove support, and skew warnings are advisory.
An unsupported keyed write or activity webhook must not be retried as an
unkeyed write or an issue-only registration: that changes the requested intent.

**Choose machine-readable failures explicitly.** Put `--json-errors` first:
`lll --json-errors issue view KEY-12 --json`. Stdout keeps its normal format;
a handled failure ends stderr with an `error` object containing typed reason,
exit/status and output-loss metadata. Branch on covered fields or exit codes,
not message text. Earlier streaming/child stderr and partial stdout can exist.
If `output_failed` is true, inspect the result before retrying a mutation.
The fixed recovery code `one_time_output_lost` means a one-time handoff was
not delivered; use the command's recovery procedure instead of duplicating it.
`lll help contract` describes the fields and stream boundaries.

**Preview project teardown.** Ordinary `lll project delete NAME --force`
keeps the issues and detaches the project. To delete the issues too, first
run `lll project delete NAME --cascade --dry-run --json`. Use its complete
opaque `revision` with `--cascade --if-preview REVISION` when executing.
Preview writes nothing. The server rechecks the state atomically and refuses
changes, claims and external references. Handle those explicitly, then preview
again. Do not replace a refused cascade with individual deletes or a force
fallback: those change the requested operation.

**Make retried creates idempotent.** Use `lll issue create --idempotency-key KEY`
when a run might lose the creation response. Derive the key once from the
intent, for example `finding:member-revocation-keeps-realtime-open`, and keep
it for every retry of that create. Do not generate a new random key on retry.
Keys are scoped per team: matching creation payloads return the existing issue
and report `Reused` (`reused: true` with `--json`); changed payloads return a
409 conflict. The fingerprint includes creator and origin, so retain the same
creation fields and context when retrying. A replay returns the current issue
without reverting subsequent edits. The server must support keyed creation;
the CLI checks support before writing. Unkeyed creates remain independent.

**Make retried comments idempotent the same way.** A comment can be saved
while the client gives up waiting, and a plain retry posts it twice. Use
`lll issue comment KEY-12 -b "..." --idempotency-key KEY` with a key derived
from the intent, for example `handoff:2026-10-14`, and keep it for every retry.
Keys are scoped per issue: the same key on another issue makes a separate
comment. A matching retry reports `Reused the comment` (`reused: true` with
`--json`) and exits 0; a changed body is a 409 conflict and exits 4. The
fingerprint includes the agent label, so retry with the same `--agent`. The
CLI checks server support before writing and refuses on an older server.

## Drive an agent from an issue

A person writes a comment on the board; an agent waiting on that issue acts
and answers in a comment. Agree on a marker the person will type, such as
`@agent`.

For one request, wait, act, reply:

```sh
lll issue watch KEY-12 --until @agent --json --timeout 3600 | tail -n 1   # the matching comment
# ... act on .record.body ...
lll issue comment KEY-12 -b "what I did"
```

`--until` exits 0 on the first comment containing the text and nonzero when
`--timeout` runs out. With `--json` it prints every comment event that arrives
while it waits; the match is the last line.

**Do not put `--until` in a loop.** A comment that already matches ends the
wait at once (`action` is `snapshot`), and it is the earliest match, so the
second pass returns the request you just handled. To keep answering, hold one
stream open and filter it:

```sh
lll issue watch KEY-12 --json |
  jq --unbuffered -r 'select(.topic == "comments" and .action == "create"
      and (.record.body | contains("@agent"))) | .record.body' |
  while read -r request; do
    # ... act on "$request" ...
    lll issue comment KEY-12 -b "what I did"
  done
```

Keep the marker out of your replies, or the stream hands them back to you as
requests. The stream is live-only: a comment written while nothing was
watching is not replayed, so read `lll issue view KEY-12 --raw` once on start.

`lll issue watch` covers one issue. For every issue in a team, filter
`lll watch --activity --json` the same way. A hosted receiver gets comments
only from a registration added with `lll webhook add URL --activity`; a plain
registration delivers issue changes alone.

## Always document friction and feature requests

**This is not optional and it is not a nicety.** Every agent hits the same walls,
and the ones that go unrecorded get hit again by the next agent, at full cost.
A shell working-directory trap or an offset bug can cost every later agent the
same investigation unless the first one records it.

File work in your project's team, using the CLI:
`lll issue create -t "Title" --emoji 🐛 -b -`. When a tool you use is tracked
on another board, file its problems in that board's team. Keep scratch and
demo boards separate from your real work records.

File it **when you hit it**, not at the end. Two kinds both count:

- **Friction**: a command that did not behave as documented, an error that did
  not name its fix, a step that needed knowledge nowhere written down, a tool
  that silently did nothing.
- **Feature requests**: the thing you reached for and it was not there.

Do not fix drive-by problems inline. File them and return to your task, so one
change stays one change and the finding survives even if the fix does not happen.

Describe the **symptom, the cause if you found it, and what you tried**. A title
alone is a note to nobody.

## The audit trail

The trail is only worth having if it answers questions later. Three kinds of
record, and they are not interchangeable:

| kind | what it is | when |
|---|---|---|
| **comment on an issue** | what changed and why, on the work item | during the work |
| **decision** | a choice with alternatives and consequences, immutable | when a choice constrains future work |
| **finding** | a trap, learned the hard way, tied to an area | the moment it costs you time |

Keep the record proportional to the work. Ordinary progress belongs in issue
comments; findings preserve reusable learning, and decisions preserve choices
whose alternatives and consequences matter. A change does not need all three.

**Write the decision when you make it, not when you ship it.** A decision
recorded after the fact is a rationalisation: it remembers what you did and
forgets what you rejected. The rejected options are the valuable half, because
the next person will think of them too.

Good decisions name what was NOT chosen and why. "Used X" is worthless. "Used X
because Y needs a reconciler and two writable copies" is worth the file.

## Hand off unfinished work

When stopping or transferring unfinished work, leave one concise issue comment
with the branch and commit, current state, remaining work, checks run and their
results, known failures, and the next useful action. Mark uncommitted work and
unrun checks explicitly. A commit or an open PR does not mean the work landed;
say whether it merged and reached the intended artifact.

Use the issue's existing record rather than creating a duplicate progress file.
Link existing evidence instead of repeating it. This is for interruptions and
transfers, not a ceremony after every small task. Follow the repo's isolation
and claim rules when returning the work to the queue or another worker.

## Reopen a named board

Run `lll new "Title"` again to reopen that title's cached local board. For a
board shared with `--share`, keep the private login saved for its URL: the
command checks it against the local database before accepting a saved network
attachment. A repository or environment token alone is not ownership proof.
If that proof is missing, follow the refusal's explicit recovery instructions;
never replace another board's attachment or create a duplicate identity to
work around it. Changing ports does not require a new board.

## Side projects: attach, work, archive

A team is cheap. Give every side project its own instead of piling issues
into a shared one. It does not have to be a repo: `lll attach --key KEY` in a plain
directory writes `.lll.toml` there and every subdirectory inherits it, so a
folder of notes gets tracked without a `git init`.

```sh
lll attach --key KEY        # once, repo or plain dir: creates team KEY if missing, writes .lll.toml
lll issue create -t "..."  # work, tracked as KEY-1, KEY-2, ...
lll team archive KEY       # done: leaves team lists and the board rail
```

Pass `--key`: without it, `attach` picks the one team you can already see (or
asks which), so a side project's issues land in your main team.

Archiving hides, never deletes: `/t/KEY/` still renders with an "archived"
banner and everything stays readable, but new writes refuse and name the fix
(`lll team unarchive KEY`). `lll team list --archived` lists every team and
marks the archived ones.
Archive rather than abandon: a board that lists only live teams is one you
can actually scan.

## Conventions that keep a parallel backlog honest

- **Claim before editing.** A successful CLI claim is already visible to other agents.
- **Read the task in full before mutating it.** Its notes may carry a decision
  already made; implementing your own instead wastes both.
- **Correct a wrong acceptance criterion, out loud.** Never quietly pass one.
  A criterion that turned out to be unmeasurable is a finding about the task.
- **Check criteria against evidence you actually ran.** Not code presence, not
  grep output, not intent. If it is a UI change, look at it.
- **One task per change.** If you find a second problem, file it.

When dividing work among reviewers or implementers, derive each task's file
list from the current checkout. Search for its target symbols with `rg -n`,
then read the matches to distinguish definitions, callers and unrelated names.
Do not assign paths from memory. Include the search command, its matching
path/line output and the checkout commit in the task brief or rules file so
the recipient can verify the scope. If there are no matches, investigate and
record that uncertainty before assigning a file list.

Recipients should verify that evidence against their checkout before editing.
If a symbol moved, search for it again and record the corrected path on the
issue; an outdated file list does not prove there is no work to do.

## Label the outcome before closing

**Make it countable by labelling the outcome before you close.** A number you
can only get by rereading a transcript is prose; a number the board answers is
a measurement. Every issue closes carrying exactly one outcome label:

- `outcome:clean` - landed, nothing else needed
- `outcome:changed` - landed, but a human had to touch it
- `outcome:blocked` - handed back, and the issue says why

`lll issue close` takes no `--label`, so the label goes on in the update
immediately before it. Create the three once per team with `lll label create`;
run `lll label list` first and reuse rather than minting near-duplicates.

**Use `--add-label`, not `--label`.** `--label` REPLACES the set: `lll issue
update KEY-123 --label outcome:clean` writes that one label and drops every
other label the issue was carrying. `--add-label` adds one label and keeps the
rest:

```sh
lll issue update KEY-123 --add-label outcome:clean
lll issue close KEY-123
```

`--add-label` and `--remove-label` repeat. Each changes only the labels it
names, so a label another agent adds at the same time with `--add-label` is
kept. `--label` and the board's label picker still write the whole
set from an earlier read, so either can drop a concurrent add. The two flags
cannot be combined with `--label`.

## Group work by outcome

Projects name durable destinations, such as Release 1 or multi-project server
mode. A parallel wave is a scheduling record, not automatically a project.
Before closing scoped work, check its project association against the outcome;
leave explicitly deferred or unrelated work outside a release commitment.
Read live counts with `lll project view NAME`. Closed-item counts do not prove
release readiness.

## Verification, before you claim anything works

Run what the user runs, not what you built. Your project's gate (the command
that must pass before a change lands) says you broke nothing; it does not say
you fixed anything. Reproduce the issue's failure, fix it, and reproduce the
fix under the issue's conditions. If you do not know the gate, your repo's
AGENTS.md, CONTRIBUTING or CI workflow names it; ask before guessing.

If a failure looks unrelated to your change, **re-run the same tree two or three
times before concluding you caused it.** A flaky assertion once caused finished
work to be parked as broken.

## The board

The board is the web view of the same server the CLI talks to; `lll board`
prints its URL. (`lll up` runs a server and board locally, for when you host
your own; on someone else's server you never need it.) Changes made anywhere (CLI,
web, another agent) appear in every open browser without a reload, over one
SSE stream, so the CLI and the board are never out of sync. `lll board -w` opens
the current team's board; `lll issue view KEY-12 -w` opens one issue.
