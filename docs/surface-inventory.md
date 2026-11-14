# Historical CLI surface audit: 0.6.1

This records the inventory and recommendations for step 1 of LLL-509, measured
at commit `5d54528` (22 September 2026). Counts, source locations, issue status
and planned changes below describe that historical revision. They are not
current operating instructions. See the [CLI guide](cli-guide.md) and
[CLI contract](cli-contract.md) for the current documented interface.

Measured against `lll 0.6.1` at `5d54528`, from `lll --help` and each noun's
own `--help` - the contract users actually read - cross-checked against
`src/commands/`.

The supporting finding was `2026-09-07-fleet-graph-first-four-tasks`,
“What 300 first-time agents taught about the CLI.” The audit used its recorded
observations and design rule when assessing aliases.

## Audit conclusion

**The audit recommended retaining the examined aliases.** Its rationale
combined direct TASK-309 observations, consistency across nouns, and the
long-form flag rule recorded in `CHANGELOG.md:385`.

The audit also found missing source comments explaining why aliases existed.
It recommended recording that rationale beside their definitions.

At that revision, LLL-505 planned to hide `finding view` and `doc link`/`unlink`
from help and completion while retaining them as working aliases.

For further review, the audit identified singleton flags (Bucket D) and the
28 `issue` subcommands as candidates for checking against actual callers.

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

**Some duplicate spellings have recorded usage evidence.** `issue view` / `show` / `read` have
byte-identical help signatures, and so do `issue create` / `new`. They look
exactly like the duplicate-spelling problem step 2 is meant to remove.

`src/commands/issue.lis:421-436` recorded the evidence:

> `read` is `view`. Seven of thirty first-time agents typed it in one fleet run
> (TASK-309), and the count went UP as other noise was removed - it is the word
> people reach for. [...] `show` is `view` too. Two of thirty first-time agents
> typed it on the first clean fleet run.

These aliases address observed command guesses. The audit recommended
retaining them and their supporting source comments.

This is the calibration for the whole exercise: a duplicate spelling backed by
observed usage is a feature; one backed by nothing is a question.

## Bucket A: aliases with direct recorded evidence

| Noun | Alias | Canonical | Evidence |
|---|---|---|---|
| issue | `read` | `view` | TASK-309, 7/30 agents |
| issue | `show` | `view` | TASK-309, 2/30 agents |
| issue | `new` | `create` | same table, same pattern |

## Bucket B: aliases assessed by consistency

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

Note the shape: `doc read`/`show` and `finding read` are the same three
spellings TASK-309 measured on `issue`, and `doc create`/`finding create`/
`member create` are the same `create`-vs-`new` pairing. That similarity supports
a consistency rationale; it does not establish
who added the aliases or whether each alias was independently measured.

The remaining question was whether the TASK-309 result should inform aliases
on other nouns. The audit applied the broader rule recorded on the board.

The finding doc `2026-09-07-fleet-graph-first-four-tasks` ("What 300 first-time
agents taught about the CLI") states the general rule it derived from ten runs
of thirty agents:

> The same holds for verb names. `read` and `show` for `view` were guessed by
> 7 and 2 of 30 respectively once the environment was clean [...] The rule that
> emerged: **a guess by more than one agent in thirty, on a clean run, is a
> design signal, not a typo.**

The recorded rule concerns verb guesses. Applying it to `doc` and `finding`
is a consistency recommendation, rather than direct measurement of each noun.

**Recommendation for step 2: keep all of Bucket B, and give each entry the
one-line comment that `issue.lis` already has.** Source comments should
distinguish directly measured aliases from those
retained for consistency and link the supporting finding.

The audit recommended using the existing evidence for this retention decision.
It did not establish a minimum sample size or independently test every alias.

## Bucket C: flag aliases - same treatment

| Alias | Canonical | Source |
|---|---|---|
| `--path` | `-p` / `--paths` | `doc.lis:290`, `finding.lis:148` |
| `--local` | `--scratch` | `lll up` |
| `--assign` | `--assignee` | `issue_filters.lis:20` |

`--local` was documented in the help text itself (`--local is an alias`).

**`--assign` has recorded usage evidence.** The same finding doc records it: guessed
for `--assignee` by 2 of 30 agents on the task where it was the main flag -
over the design-signal threshold. Keep it, and comment it.

**`--path` follows the documented long-form rule.** It is the long form of `-p`, not a stray
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

## Bucket D: singleton flags

Fifteen flags appear exactly once in the whole CLI:

`--version --slug --secret --prefix --pb-dir --paths --path --out --name
--message --local --kind --for --demo --assign`

A single occurrence does not establish that a flag is unused. `--version` and
`--pb-dir` serve specific functions. This list is here so step 2 can check each against "is
there still a caller?" rather than rediscovering the set.

Spot-checked each against `scripts/`: every one has an e2e or script caller
except `--secret`. It has implementation and unit-test coverage: `webhook.lis:67` declares it,
line 94 consumes it to set the `X-LLL-Secret` delivery header, and
`webhook.test.lis:109` covers it. Zero e2e references means webhooks are not
exercised end to end, which is a test-coverage observation rather than a
surface one, and worth its own issue rather than a removal.

## Bucket E: shared vocabulary

The most-repeated flags showed a consistent grammar:

`--team` (75), `--json` (33), `--url` (17), `--force` (13), `--raw` (12),
`--project` (11), `--state` (10), `--search` (8), `--assignee` (8).

The audit recommended preserving that shared vocabulary.

## Related decisions at the audited revision

The TASK-309 finding doc lists what the fleet asked for that was not built.
The audit checked each against the measured binary:

- **`issue start` does more than its name** (four agents). **Resolved.** LLL-262
  made the Git side opt-in behind `--branch`, and the decision doc
  `keep-issue-start-independent-of-git-mutations` records why. The help text at that revision matched. No surface action.
- A creator field on issues (five agents) - shipped per TASK-169.
- Validate `me` at config time (four agents) - outside this issue's scope; it is
  a behaviour question, not a surface one.

## Work in progress at the audited revision

**LLL-505** was recorded as `in-review` (branch `lll-505-remove-duplicate-verbs`) and proposed hiding
cross-noun duplicate verbs: `finding view`/`read`, and `doc link`/`unlink`
would keep working but leave help and completions. The audit recommended
basing step 2 on that branch's result to avoid proposing the same changes again.

## Limits and remaining questions

- The audit recommended retention for Buckets A, B and C. It did not
  independently measure usage of every alias across every noun.
- Whether `lll doctor` should exist (step 4). Note the overlap with LLL-510: if
  gate roles become resolvable and runnable, part of what a doctor would check
  may belong there instead.
- Anything about flags' internal behaviour. This inventory reads the contract,
  not the implementations.
