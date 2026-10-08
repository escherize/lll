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

## The loop

```sh
lll issue list --state todo            # what is open
lll issue view KEY-12                  # read it FULLY before you touch anything
lll issue claim KEY-12                 # exits non-zero if someone got there first
lll issue update KEY-12 --state in-progress
# ... work ...
lll issue comment KEY-12 -b "what changed and why"
lll issue close KEY-12                 # when the change is on main; releases your claim too
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
`lll issue close KEY-12` releases your claim in the same step and keeps the
assignee, so the done issue still says who did it; `--keep-claim` keeps the
claim. Releasing or closing over another member's claim, or a hold under a
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

## Record it

The commands an agent reaches for most, in the 0.8 spellings. Each has
`--help` with the full flag list.

```sh
lll issue next --claim             # take the next ready, unclaimed issue (prints its key)
lll search "claim expiry"          # issues, comments and docs, ranked
lll finding near src/api           # traps already recorded for these paths

# a trap, the moment it costs you time; 'suspected' until you have proof
printf '%s' "$what_happened" | lll finding create port-probe-races \
  -t "Port probe races a sibling server" -a ci -p scripts/e2e.sh \
  --confidence suspected -b -
lll finding confirm port-probe-races   # once you have proved it

# a choice that constrains future work, written when you make it
printf '%s' "$options_and_why" | lll doc create -k decision \
  -s cache-in-process -t "Cache widgets in process, not in Redis" -b -

lll bot create bot-myrepo          # a member for an agent: prints a paste-ready prompt with its token, once
```

`-a` (area) is conventionally a label's name, so issues carrying that label
surface the doc. `-p` takes comma-separated paths; `lll finding near` matches
by them in both directions.

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

**`lll watch` is live-only; reconcile on start.** It streams from the moment
the subscription is accepted, and a reconnect does not replay what it missed,
so a gap looks exactly like a quiet board. A long-running agent keeps the time
of the last event it handled and, on every start and reconnect, runs
`lll issue list --since <that time>` before trusting the stream. A fleet
coordinator missed three cards reaching done by relying on watch alone.

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

## Always document friction and feature requests

**This is not optional and it is not a nicety.** Every agent hits the same walls,
and the ones that go unrecorded get hit again by the next agent, at full cost.
Real examples from lll's own development: a shell-working-directory trap was
recorded after two occurrences and happened twice more; a byte-offset versus
rune-index bug was in a finding before it panicked in five places.

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

**Write the decision when you make it, not when you ship it.** A decision
recorded after the fact is a rationalisation: it remembers what you did and
forgets what you rejected. The rejected options are the valuable half, because
the next person will think of them too.

Good decisions name what was NOT chosen and why. "Used X" is worthless. "Used X
because Y needs a reconciler and two writable copies" is worth the file.

## Side projects: attach, work, archive

A team is cheap — give every side project its own instead of piling issues
into a shared one. It does not have to be a repo: `lll attach --key KEY` in a plain
directory writes `.lll.toml` there and every subdirectory inherits it, so a
folder of notes gets tracked without a `git init`.

```sh
lll attach --key KEY        # once, repo or plain dir: creates team KEY if missing, writes .lll.toml
lll issue create -t "..."  # work, tracked as KEY-1, KEY-2, ...
lll team archive KEY       # done: leaves team lists and the board rail
```

Pass `-k`: without it, `attach` picks the one team you can already see (or
asks which), so a side project's issues land in your main team.

Archiving hides, never deletes: `/t/KEY/` still renders with an "archived"
banner and everything stays readable, but new writes refuse and name the fix
(`lll team unarchive KEY`). `lll team list --archived` lists every team and
marks the archived ones.
Archive rather than abandon — a board that lists only live teams is one you
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
