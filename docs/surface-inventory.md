# CLI surface inventory

Step 1 of LLL-509. This is the **measurement**, not the verdict: it says what
exists and sorts it into buckets. Deciding what goes is step 2, and it is a
judgement call about what users depend on, which is why LLL-509 marks it as not
agent-safe.

Measured against `lll 0.6.1` at `5d54528`, from `lll --help` and each noun's
own `--help` - the contract users actually read - cross-checked against
`src/commands/`.

**Read `2026-09-07-fleet-graph-first-four-tasks` before acting on any of this.**
That finding doc - "What 300 first-time agents taught about the CLI" - is the
evidence base for most of what follows, and it already answers the question
this inventory was expected to defer to a new fleet run.

## The answer, up front

**Nothing in the alias surface should be cut.** Every command alias and every
flag alias this audit examined is either measured by the TASK-309 fleet runs or
covered by the stated long-form rule in `CHANGELOG.md:385`. The audit found no
cruft in the place it most expected to.

What it DID find is that the evidence was not written down where a future
auditor would look, so the same question was going to be re-opened
indefinitely. That is what this change fixes.

Two things genuinely are being removed, and neither needed this audit to find:
`finding view` and `doc link`/`unlink`, already in review as LLL-505.

If step 2 wants real cruft, this inventory says to look somewhere other than
aliases - the singleton flags (Bucket D) and the 28 subcommands on `issue` are
where an unexamined surface would more plausibly hide, and neither has been
checked against "is there still a caller?".

## The size of it

| Surface | Count |
|---|---|
| Top-level nouns | 24 |
| Subcommands across all nouns | 84 |
| Distinct long flags | 71 |
| Documented command aliases | 10 |
| Flag aliases | 3 |
| Flags appearing exactly once | 15 |

Per noun: `issue` 28, `doc` 10, `team` 9, `member` 8, `finding` 8, `project` 6,
`label` 5, `config` 3, `webhook` 3, `skill` 3, `token` 1, `api` 0 (passthrough).

`issue` carries a third of the subcommands. That is where the surface question
lives.

## The most important finding

**The obvious cruft is not cruft.** `issue view` / `show` / `read` have
byte-identical help signatures, and so do `issue create` / `new`. They look
exactly like the duplicate-spelling problem step 2 is meant to remove.

They are the opposite. `src/commands/issue.lis:421-436` records why:

> `read` is `view`. Seven of thirty first-time agents typed it in one fleet run
> (TASK-309), and the count went UP as other noise was removed - it is the word
> people reach for. [...] `show` is `view` too. Two of thirty first-time agents
> typed it on the first clean fleet run.

These are measured affordances. An audit that removed them would delete the
repo's best piece of UX evidence and re-introduce a failure that was already
observed. **Do not remove them, and keep the comment that explains why**, because
the next audit will reach for them again.

This is the calibration for the whole exercise: a duplicate spelling backed by
observed usage is a feature; one backed by nothing is a question.

## Bucket A: aliases WITH recorded evidence - keep

| Noun | Alias | Canonical | Evidence |
|---|---|---|---|
| issue | `read` | `view` | TASK-309, 7/30 agents |
| issue | `show` | `view` | TASK-309, 2/30 agents |
| issue | `new` | `create` | same table, same pattern |

## Bucket B: aliases WITHOUT recorded evidence - the real question for step 2

Seven aliases in three nouns carry no comment, no task reference, and no
recorded fleet data. They may be the same good instinct applied without
measurement, or symmetry copied from `issue`.

| Noun | Alias | Canonical | Source |
|---|---|---|---|
| doc | `create` | `new` | `doc.lis:38` |
| doc | `show` | `view` | `doc.lis:62` |
| doc | `read` | `view` | `doc.lis:70` |
| finding | `read` | `view` | `finding.lis:45` |
| finding | `create` | `new` | `finding.lis:61` |
| member | `create` | `add` | `member.lis:60` |
| member | `delete` | `remove` | `member.lis:92` |

Note the shape: `doc read`/`show` and `finding read` are the SAME three
spellings TASK-309 measured on `issue`, and `doc create`/`finding create`/
`member create` are the same `create`-vs-`new` pairing. That is evidence the
aliases were applied on purpose, by someone who had read the issue result -
which makes "remove them" the less likely correct answer, and makes recording
the reasoning the more likely one.

**The question is not "remove these".** It is whether the TASK-309 result
generalises from `issue` to the other nouns. **It already does, and the board
says so.**

The finding doc `2026-09-07-fleet-graph-first-four-tasks` ("What 300 first-time
agents taught about the CLI") states the general rule it derived from ten runs
of thirty agents:

> The same holds for verb names. `read` and `show` for `view` were guessed by
> 7 and 2 of 30 respectively once the environment was clean [...] The rule that
> emerged: **a guess by more than one agent in thirty, on a clean run, is a
> design signal, not a typo.**

That rule is about how agents guess VERBS. It is not scoped to `issue`, and
nothing about `doc` or `finding` makes a reader of those nouns guess
differently. Bucket B is the same rule applied consistently.

**Recommendation for step 2: keep all of Bucket B, and give each entry the
one-line comment that `issue.lis` already has.** The defect is not the aliases;
it is that six of them carry no trace of why they exist, so every future audit
re-opens the same question. A comment naming the finding doc closes it
permanently.

No fleet run is needed. The measurement was already taken, at ten times the
sample this question needs.

## Bucket C: flag aliases - same treatment

| Alias | Canonical | Source |
|---|---|---|
| `--path` | `-p` / `--paths` | `doc.lis:290`, `finding.lis:148` |
| `--local` | `--scratch` | `lll up` |
| `--assign` | `--assignee` | `issue_filters.lis:20` |

`--local` is documented in the help text itself (`--local is an alias`), so it
is at least honest.

**`--assign` is measured, not cruft.** The same finding doc records it: guessed
for `--assignee` by 2 of 30 agents on the task where it was the main flag -
over the design-signal threshold. Keep it, and comment it.

**`--path` is not cruft either, and an earlier draft of this document was wrong
to list it as the one open question.** It is the long form of `-p`, not a stray
duplicate of `--paths`, and it belongs to a stated design rule. CHANGELOG.md:385
says it outright:

> A flag takes any number of aliases. Added across the fleet runs: `read` and
> `show` for `view`, `--assign`, `-t`/`--title` and `-d` both ways,
> `--body`/`-m`/`--message`, `--query`, `--path`.

It is in the same sentence as the aliases TASK-309 measured, for the same
reason. `scripts/e2e.sh:2141` pins it with an assertion that says so:
"doc new takes the long form of every flag, --path included".

Every short flag in `doc.lis` has a long form on the same pattern: `-s`/`--slug`,
`-t`/`--title`, `-k`/`--kind`, `-b`/`--body`, `-a`/`--area`, `-p`/`--paths --path`.
Removing one would break the consistency that makes the rest guessable.

## Bucket D: singleton flags - probably fine, listed for completeness

Fifteen flags appear exactly once in the whole CLI:

`--version --slug --secret --prefix --pb-dir --paths --path --out --name
--message --local --kind --for --demo --assign`

A flag used once is not automatically cruft - `--version` and `--pb-dir` are
obviously load-bearing. This list is here so step 2 can check each against "is
there still a caller?" rather than rediscovering the set.

Spot-checked each against `scripts/`: every one has an e2e or script caller
except `--secret`. That one is NOT cruft either - `webhook.lis:67` declares it,
line 94 consumes it to set the `X-LLL-Secret` delivery header, and
`webhook.test.lis:109` covers it. Zero e2e references means webhooks are not
exercised end to end, which is a test-coverage observation rather than a
surface one, and worth its own issue rather than a removal.

## Bucket E: shared vocabulary - the part that is working

The most-repeated flags show a consistent grammar, which is the opposite of
cruft and worth protecting during any removal:

`--team` (75), `--json` (33), `--url` (17), `--force` (13), `--raw` (12),
`--project` (11), `--state` (10), `--search` (8), `--assignee` (8).

Any removal that breaks this consistency costs more than the surface it saves.

## Already answered elsewhere - do not re-open

The TASK-309 finding doc lists what the fleet asked for that was not built.
Checked each against the current binary:

- **`issue start` does more than its name** (four agents). **Resolved.** LLL-262
  made the Git side opt-in behind `--branch`, and the decision doc
  `keep-issue-start-independent-of-git-mutations` records why. The current help
  text matches. No surface action.
- A creator field on issues (five agents) - shipped per TASK-169.
- Validate `me` at config time (four agents) - outside this issue's scope; it is
  a behaviour question, not a surface one.

## Already in flight - do not double-count

**LLL-505** (`in-review`, branch `lll-505-remove-duplicate-verbs`) already
removes cross-noun duplicate verbs: `finding view`, and `doc link`/`unlink`.
Step 2 should start from that branch's result, not from `main`, or it will
re-propose removals that are already done.

## What this does NOT answer

- Nothing in Buckets A, B or C. Every alias is either measured by TASK-309 or
  covered by the stated long-form rule in CHANGELOG.md:385, and both are now
  cited at the source.
- Whether `lll doctor` should exist (step 4). Note the overlap with LLL-510: if
  gate roles become resolvable and runnable, part of what a doctor would check
  may belong there instead.
- Anything about flags' internal behaviour. This inventory reads the contract,
  not the implementations.
