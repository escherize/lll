# Documentation style

Use factual, straightforward and consistent prose. Lead with what the reader
needs to know or do, then explain the mechanism, evidence and limits.

lll began as an issue tracker and now provides shared coordination for people
and agent workers. Describe that evolution through its capabilities: work,
claims, findings, decisions, attribution and bounded delegation. External tools
launch workers; lll records their work and enforces access to the board.

## Organize around the reader's task

| Page type | Lead with | Follow with |
| --- | --- | --- |
| Conceptual guide or post | The main conclusion and why it matters | Supporting reasons, examples, then technical detail |
| Procedure or runbook | Outcome, scope and prerequisites | Ordered actions, expected results and relevant recovery steps |
| Reference | The interface and its scope | Independent sections for commands, fields or contracts |
| Historical report | Date, revision, result and coverage | Evidence, limitations and links to current procedures |

For explanatory posts, use these structures together:

- **BLUF:** state the main conclusion in the opening paragraph.
- **Pyramid Principle:** place supporting reasons below that conclusion and
  evidence below the reasons. Readers should understand the argument before
  reaching its implementation details.
- **SCQA:** explain the situation, the complication, the resulting question
  and the answer. The question can be implicit. Use this sequence when a
  change or decision needs context.
- **MECE:** give each section a distinct purpose and cover the reader's main
  questions. Put a rule in one primary section and link to it elsewhere.

Apply the structure that fits the page. A command reference needs clear
categories; a recovery runbook needs steps in execution order.

## Keep terminology precise

| Term | Meaning |
| --- | --- |
| Member | An lll identity, either a person or a bot |
| Person | A human account |
| Bot | A member identity used for automated work, with its own credential |
| Worker | The agent or process doing the work |
| Agent label | A coordination label for a session; it grants no authority |
| Workspace Admin | Responsibility for people, team grants and team lifecycle |
| Infrastructure operator / superuser | The server's bootstrap and recovery authority |
| Team role | None, Viewer or Editor content access |
| Human owner / creating bot | The relationships that bound a delegated bot's access |
| Claim | The recorded coordination hold on an issue |
| Project | A grouping inside a team that inherits the team's access |

Use **issue** for the record and **card** for its visible board representation.
Use **run owner** for the coordinator of a test run, so it is distinct from a
bot's human owner. Keep exact CLI spellings, API fields and UI labels when
describing an interface. See [the permissions contract](permissions.md) for
the authority model.

## Separate facts, history and proposals

Describe current behavior in the present tense and identify the version when
compatibility matters. Verify a behavioral claim against its source or a
recorded check before changing it. Keep uncertain findings labeled as needing
verification.

Label proposals explicitly. Explain the current workflow before describing
an improvement that has not shipped. Avoid presenting a desired capability
as an existing one.

Date historical observations and name their revision or run. Preserve original
measurements, denominators, failed attempts, hashes and case identifiers. Add
context or a mapping when names change; keep the original evidence intact.
Released changelog entries remain historical records.

## Bound claims to their evidence

Name the mechanism and its scope. Claims coordinate who takes work; they do
not guarantee that every worker follows the workflow. Live updates apply to
subscribing surfaces. A passing gate covers its tested cases and revision.

Prefer concrete verbs such as **records**, **checks**, **refuses**, **retains**
and **reopens**. Avoid hype, universal promises, invented labels and slogans.
Use normal sentence case rather than capitals for emphasis. Keep one main
claim per paragraph and use tables when readers need to compare parallel
concepts.

Preserve command syntax, fixture strings, credential handling, refusal
conditions and recovery loss windows during an editorial edit. Describe an
expected negative check separately from an unexpected tool failure. Report
an actual runner permission refusal as a harness blocker.

## Review before publishing

- The opening gives the reader the main conclusion or required action.
- Sections have distinct purposes and a clear reading order.
- Current behavior, proposals and historical evidence are distinguishable.
- Role names and technical terms match the maintained contract.
- Claims stay within the mechanism or evidence that supports them.
- Examples retain their exact syntax and operational meaning.
