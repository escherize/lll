# Type-driven refactoring notes

*Design notes from an architecture review of `main` at `787c27c` (8 October 2026).*

> **Read this first.** These are proposals, not patches. The Lisette compiler
> (`lis`) was not available during the review, so none of the code blocks below
> has been compiled. Section 4 lists the language features to check in a scratch
> module before committing to any shape. File and line references were checked
> against `787c27c`; they will drift, so re-read the code before editing.

## Contents

1. [Summary](#1-summary)
2. [Why types, and why in lll](#2-why-types-and-why-in-lll)
3. [The principles, applied to lll](#3-the-principles-applied-to-lll)
4. [What Lisette supports, and what to verify first](#4-what-lisette-supports-and-what-to-verify-first)
5. [Refactoring themes](#5-refactoring-themes)
   - [A. Team scope and identifiers](#5a-team-scope-and-identifiers)
   - [B. Issue vocabulary as enums](#5b-issue-vocabulary-as-enums)
   - [C. Writes as typed patches](#5c-writes-as-typed-patches)
   - [D. Authorization as values](#5d-authorization-as-values)
   - [E. Typed errors](#5e-typed-errors)
   - [F. Explicit context](#5f-explicit-context)
   - [G. Typed events and wire frames](#5g-typed-events-and-wire-frames)
   - [H. One source of truth across Go, JS and Lisette](#5h-one-source-of-truth-across-go-js-and-lisette)
6. [Order of work](#6-order-of-work)
7. [What not to do](#7-what-not-to-do)
8. [Checklist for new code](#8-checklist-for-new-code)
9. [Appendix A: finding index](#appendix-a-finding-index)
10. [Appendix B: proposed types at a glance](#appendix-b-proposed-types-at-a-glance)

---

## 1. Summary

Most of the problems the review found have one cause: the code knows something
that its types don't say.

- **An empty string means "every team".** `configured_team_id()` returns `""`
  when no team is configured. A missing setting therefore widens a query
  instead of failing it. This is how `lll label delete bug` can delete another
  team's `bug` label.
- **A state is validated, then thrown away.** The board calls
  `let _ = query.state(state)?` and sends the raw string on. Every later reader
  compares string literals again, and two definitions of "ready" have drifted
  apart.
- **Errors are English text.** Claim conflicts are detected by searching Go's
  error messages from Lisette, and the HTTP status is parsed back out of an
  error string.
- **Permission is a ritual, not a value.** Each board write must remember four
  calls in the right order. Nothing stops a handler from skipping them.
- **Configuration travels through the environment.** `--team` reaches the rest
  of the program through `os.Setenv`.

The Lisette sources declare six enums: `pb.Caller`, `realtime.DeadToken`,
`FilterUse`, `Install`, `Viewer` and `ScopedVerdict`. Everything else that is
conceptually a fixed set (states, priorities, access levels, realtime actions
and topics, error kinds, team scope) is a `string`, an `int` or a `bool`.

The refactoring is eight moves:

| | Move | What it rules out | Section |
|---|---|---|---|
| A | Team scope as `TeamScope { Only(TeamId), Every }`; ids as distinct types; one `IssueKey` parser | silent widening to every team; swapped ids; the gate and the fetch disagreeing about a key | [5.A](#5a-team-scope-and-identifiers) |
| B | Issue vocabulary as enums (`IssueState`, `Priority`, `Readiness`) | copies of the state list drifting; `?` glyphs; two "ready" rules | [5.B](#5b-issue-vocabulary-as-enums) |
| C | Writes as typed patches (`IssuePatch`, `DescriptionWrite`) | contradictory flag combinations; hand-built JSON; lost description updates | [5.C](#5c-writes-as-typed-patches) |
| D | Authorization as values (`Access`, `Viewer` once per request, `WritableIssue`, `ReleaseAs`) | handlers that skip a check; contradictory access states; silent overrides | [5.D](#5d-authorization-as-values) |
| E | Typed errors (`PbError`, `ClaimError`, `CliError`) with stable server codes | branching on English text; statuses lost when wrapped; one exit code for everything | [5.E](#5e-typed-errors) |
| F | Explicit context (`TeamSelection`, `pb.Client`) instead of environment variables | hidden inputs; repeated config reloads; globals that defeat parallel tests | [5.F](#5f-explicit-context) |
| G | Typed events and frames (`RecordEvent`, `Patch`) | unknown topics treated as issues; missed reconnects; malformed SSE frames | [5.G](#5g-typed-events-and-wire-frames) |
| H | One source of truth across Go, JS and Lisette | access rules drifting between three languages; readable secrets; cross-team references | [5.H](#5h-one-source-of-truth-across-go-js-and-lisette) |

Section 6 orders the work. The live bugs get small fixes that need no new
types first. The types that stop each class of bug from coming back follow.

---

## 2. Why types, and why in lll

### The comments already know

lll's code is unusually well commented, and many comments state a rule:

- *"Only the listing verbs and the unscoped web board tolerate that second
  answer; anything that writes a team-owned record uses current_team."*
  (`src/commands/team.lis:465-467`)
- *"Relation ids (assignee, project, labels) are handed to PocketBase
  unchecked."* (`src/commands/serve_actions.lis:169-170`)
- *"Names are unique within a team, not across them."*
  (`src/records/labels.lis:9`)
- *"A webhook's secret is therefore readable by other members."*
  (`pb/pb_migrations/1789500000_webhooks.js:10`)

None of these rules is enforced. A rule in a comment holds only as long as
every future edit remembers it, and the review found places where an edit
didn't. Most of the proposals below take a rule that a comment already states
and move it into a function signature, where the compiler checks it.

### Four reasons lll benefits more than most codebases

**It is multi-tenant, and widening is the costly failure.** Showing too little
is an annoyance. Showing or changing another team's records breaks the
product's main promise. Code that treats "no value" as "no restriction" fails
open. Types can make widening an explicit decision with a name, which a
reviewer can see and grep for.

**Its main users are programs.** Agents run the CLI unattended (see the
`backlog-loop` skill). They branch on exit codes and on `--json` output, and
cannot reliably interpret English error text. Every output shape and exit code
is therefore an API. Types keep each API defined in one place, and an
exhaustive `match` makes the compiler find every site a new case must reach.

**Its rules cross three languages.** Access rules exist as JavaScript strings
in migrations, as Go in `gopb`, and as Lisette in the board. Types do not cross
a language boundary. That boundary needs explicit contracts, meaning stable
codes on the wire and conformance tests. Each side needs one place that turns
the wire format into its own types.

**The board is a deputy.** The board reads as its own process identity, which
can see every team, on behalf of viewers who can see less. Board-token sessions
also write that way. This is the classic *confused deputy* setup: any path that
forgets to narrow acts with the deputy's authority. The standard defence is a
capability, a value that carries exactly the authority a request is entitled
to. A forgotten check then becomes a missing value, and the code does not
compile.

### What types cannot do

Client-side types never replace enforcement on the server: anyone can send the
same request with `curl` and skip the CLI. This document assumes a fixed split:

- **The server owns invariants.** Examples are "references stay within a team",
  "archived teams are read-only" and "only the holder may release a claim".
  These are enforced in `gopb` on every save, whoever the caller.
- **Client types own intent and diagnosis.** They stop lll's own code from
  sending a wrong request, give the user an accurate error, and make the
  compiler list every site a change affects.

Some findings are not type problems, and this document mentions them only in
passing:

- **Claim-expiry race (C5):** needs a conditional delete inside the
  transaction.
- **Serial SSE bridge (W4):** needs concurrency and logging.
- **Webhook delivery:** needs an outbox so deliveries survive a restart.

---

## 3. The principles, applied to lll

Each subsection covers four things:

- what the principle says
- where lll breaks it today
- what the typed version looks like
- how to find more instances

### 3.1 Parse, don't validate

**What it says.** A *validator* checks a value and gives back nothing new,
either `Result<(), E>` or the same string. A *parser* checks a value and gives
back a more precise type that records that the check passed. After parsing, the
rest of the program never receives the unchecked form. Validation leaves that
knowledge in the programmer's head; parsing puts it in the type.

**In lll today.** `query.state(s)` returns `Ok(s)`, the same string it was
given. The board calls it and discards the result:

```lisette
let _ = query.state(state)?    // serve_actions.lis, in create_write and state_write
```

It then sends the raw `state` string on. Nothing distinguishes a checked state
from an unchecked one, so a new handler that forgets the call still compiles.
In the same way:

- `require_active_team` returns `()`.
- `attachments.require_file` checks a filename, returns nothing, and so both of
  its callers check it again.

**Typed version.** `IssueState.parse(s) -> Result<IssueState, string>`. Code
that needs a state takes an `IssueState`, so the only way to get one is to
parse. Parsing happens once, at each boundary where outside data enters:

- argv (`flags`)
- form posts (the board)
- PocketBase responses (`records`)
- realtime frames (`realtime`)
- error bodies (`pb`)

**Find more.**

- `let _ = ` applied to a checking function
- functions whose `Ok` type is the same as their input type
- `-> Result<(), string>` functions named `check_*` or `require_*`

### 3.2 Make illegal states unrepresentable

**What it says.** If two fields can contradict each other, replace them with a
sum type (an enum with payloads) whose variants are exactly the legal
combinations. If a value has a special case, such as "empty means all", make
that case its own variant.

**In lll today.**

- `ViewerMember { rw: bool, all: bool }` sits next to a separate list of teams
  (`serve_gate.lis:260-286`).
  - `all = true` with a partial team list can be expressed.
  - `Viewer.Full`, and `Viewer.Scoped` with `all = true`, are two spellings of
    full access.
- Releasing a claim takes `force: bool, reason: string`. That gives four
  combinations, two of them meaningless: force without a reason, and a reason
  without force.
- `issue update` encodes "not given" as `""` for state, `-1` for priority, and
  `""` versus `"none"` for assignee. Deciding whether there is anything to do
  takes a twelve-term conjunction (`issue.lis:1263-1340`).
- `issue list` takes `--ready` and `--blocked` as two booleans, and checks at
  runtime that both are not set.
- `team_id: ""` means every team.

**Typed version.**

- `Reach { Teams(Slice<TeamKey>), Everything }`
- `ReleaseAs { Holder, Override(Reason) }`
- `Edit<T> { Keep, Clear, Set(T) }`
- `ListMode { Page { .. }, Ready, Blocked }`
- `TeamScope { Only(TeamId), Every }`

**Find more.**

- pairs of booleans
- a boolean next to an optional string
- sentinel values (`""`, `-1`, `0`) documented as meaning something
- comments of the form "only meaningful when…"

### 3.3 Distinct types for identifiers

**What it says.** Give each kind of identifier its own type, even though all of
them are strings underneath. Passing an issue id where a claim id belongs then
fails to compile.

**In lll today.**

- **Positional strings.** `query.filter(team_id, state, assignee_id,
  project_id, label_id, search)` takes six strings by position.
  `delete.lis:11-12` puts a label id in one slot and a project id in another.
  Swapping them compiles, and the count it produces decides whether `delete`
  needs `--force`.
- **Adjacent ids.** `claims.update_assignment(caller, issue_id, claim_id,
  fields, agent, force, reason)` takes four adjacent strings.
- **Hand-built keys.** Issue keys are rebuilt by hand as
  `f"{x.expand.team.key}-{x.number}"` in about 43 places. That gives `"-12"`
  whenever the read did not expand `team`.

**Typed version.**

- `TeamId`, `IssueId`, `LabelId`, `ProjectId`, `MemberId` and `ClaimId`, or one
  generic `Id<T>`.
- Parsed `TeamKey` and `IssueKey` types.
- Structs with named fields in place of long positional parameter lists.

**What it doesn't buy.** In Lisette these are ordinary structs, so another
module can build one from any string ([4.2](#42-not-seen-in-the-repo--verify-in-a-scratch-module-first)).
Distinct id types prevent *mix-ups*, not forgery. Preventing forgery needs
module privacy ([3.4](#34-capabilities-proof-as-a-value)).

**Find more.**

- functions with three or more `string` parameters
- `f"{...key}-{...number}"`
- functions such as `observed_id` that return `""` for "none"

### 3.4 Capabilities: proof as a value

**What it says.** If an operation is allowed only after a check, make the check
return a value that the operation requires. That value is called a *witness*.
If the witness can only be constructed by the check (private fields, one
constructor in its own module), calling the operation without the check does
not compile.

**In lll today.** Every board write repeats the same sequence, in 11 handlers in
`serve_actions.lis`:

1. `acting_as`
2. `who.issue(key)`
3. `require_active_team(issue.expand.team)`
4. `patch_issue(who.caller, issue.id, …)`

Nothing enforces the sequence. `patch_issue` accepts any `(caller, id)` pair,
including the process caller with an issue nobody scope-checked. Today
`favorite_write` and `views_save` skip the sequence. They are safe only because
the scoped-route allowlist in `serve_gate.lis` keeps member viewers away from
those routes, so the safety comes from a mechanism in another file.

**Typed version.** A `writes` module owns three things: the witnesses `Writer`
and `WritableIssue`, the one function that creates a `WritableIssue`, and the
write functions that consume one. Creating a `WritableIssue` fetches the issue
as the writer, checks reach, and checks the archived flag. See
[5.D.3](#d3-witnesses-and-why-they-need-their-own-module), including why the
write functions must live in the same module as the witness.

**Find more.**

- comments of the form "callers must first…"
- functions that take a credential plus an id

### 3.5 Typed errors

**What it says.** An error that callers branch on is data, not prose. Give it a
type with one variant for each thing a caller might do differently. Parse it
once at the boundary, and turn it into text only at the edge (CLI output or
the board's flash message).

**In lll today.**

- **Errors are strings.** Commands return `Result<(), string>`.
- **The status is parsed back out of text.** The HTTP status is recovered by
  parsing the error message (`src/pb/status.lis:6-18`, used in about 21
  places). That works only while the message still starts with `"GET "` or
  `"POST "`. Any wrapping such as `f"{key}: {e}"` makes the status read as 0.
- **Claim conflicts are found by substring.** The CLI matches
  `strings.Contains(e, "is claimed by")`, `"already claimed by"` and
  `"needs force"` (`issue.lis:1448, 1686, 1716, 2387`; `member.lis:1259`)
  against `fmt.Sprintf` strings in `gopb/claims.go` and `gopb/assignment.go`.
  Rewording a Go message silently changes CLI behaviour, and no test fails.
- **Help travels as an error.** Help text is an `Err` string carrying a
  control-character marker.
- **Every failure exits 1.**

**Typed version.** Errors pass through three layers:

1. `PbError`, parsed once at the HTTP boundary.
2. Domain errors such as `ClaimError`, parsed from a stable code that the
   server adds.
3. `CliError` at the CLI edge, mapped to exit codes by one exhaustive `match`.

**Find more.**

- `strings.Contains(e,`
- `.starts_with(` on error values
- `response_status(`
- `help_marker`

### 3.6 Explicit dependencies

**What it says.** A function's inputs should be its parameters. Process-wide
mutable state, such as environment variables and globals, is an input that any
function can read and any function can change. That hides ordering
dependencies and stops tests from running in parallel.

**In lll today.**

- `--team` is applied with `os.Setenv("LLL_TEAM", key)` plus a marker variable
  `LLL_TEAM_FROM_FLAG` (`src/commands/scope.lis:23-26`).
- `--admin-email` and `--admin-password` are written into the environment
  (`token.lis:219-231`).
- Login swaps `LLL_URL` and restores it by hand.
- The board token and the realtime token refresh also go through `os.Setenv`.
- The PocketBase client has no value to hold its settings, so every call
  re-reads the config files.

**Typed version.** Resolve a `Context { client, team, output }` once in `main`
and pass it down.

**Find more.** `os.Setenv(`, and `os.Getenv("LLL_` outside `src/config` and
`main`.

### 3.7 Totality: exhaustive matches, no catch-all arms on domain values

**What it says.** When a `match` lists every variant and has no `_` arm, adding
a variant breaks the build at every site that must decide what the new case
means. The compiler turns "find every place that cares about states" into a
to-do list. A `_` arm silently opts that site out.

**In lll today.**

- `display.glyph` matches states with `_ => "?"`.
- The realtime dispatch in `serve_sse.lis` is an `if/else` chain on topic
  strings. Its final `else` sends every other topic to the issue handler.
- "Terminal" (`done || cancelled`) is written out in about six places, and
  "pickable" (`todo || backlog`) in three.

**Typed version.** Use enums for states, topics, actions and modes. Write each
policy as a function over the enum with one arm per variant.

**Find more.**

- `_ =>` in a `match` on anything that is conceptually an enum
- `if x == "…" … else if x == "…"` chains

### 3.8 One source of truth

**What it says.** Declare each fact once. Derive everything else from it, or
check it against that declaration in a test.

**In lll today.**

- **The state vocabulary** exists in `query.states()`, in `display.glyph`, in
  the init migration's select field, and in the hand-written predicates.
- **The access model** exists in three places:
  - JS rule strings in `1791700000_bot_owner_scope.js`, with
    `1791900000_member_roster_scope.js` re-declaring its own constants
  - Go's `effectiveAccess` and `rosterSees`
  - the board's own re-scoping code
- **Issue writes are spelled twice.** Create uses the typed `models.NewIssue`.
  Update builds its JSON by concatenating strings (`issue.lis:1376-1429`).

**Typed version.** Keep one definition, and either derive the copies from it or
add a test that checks them against it. Across languages, a conformance test is
usually the cheaper first step ([5.H.3](#h3-access-rules-a-conformance-test-first-then-one-table)).

---

## 4. What Lisette supports, and what to verify first

### 4.1 Already used in this repo, and safe to rely on

| Feature | Where it is used |
|---|---|
| Enums with tuple payloads, exhaustive `match` | `pb.Caller { Process, Member(string) }` (`src/pb/client.lis:159`); `Viewer` (`serve_gate.lis:260`) |
| Enums with struct payloads | `AGENTS.md` (`Member { team: string }`) |
| `impl` blocks on structs | `Filters`, `FrameParser`, `Member`, `Parsed`, `Names`, `Acting`, `ScopedViewer`, `Roster` |
| Private fields with a public constructor | `realtime.FrameParser` (private fields, `pub fn new`) |
| Generic structs and functions | `CollectionPage<T>`, `fetch_all_records<T>` (`src/records/pagination.lis`) |
| `#[json]` structs, renamed keys, `omitempty` on `Option` | `models.*`, `CollectionPage` |
| Tuples | `split_issue_key` returns `(string, int)` |
| `map_err` | used throughout `issue.lis` |

Two existing types already follow the patterns in this document. `pb.Caller`
makes the choice of credential an explicit value. `realtime.DeadToken`
(`Exit`/`Remint`) is a policy passed in as an enum instead of a boolean. The
proposals extend patterns the codebase already has.

### 4.2 Not seen in the repo — verify in a scratch module first

Each item below affects the exact shape of a proposal. Checking them takes
about half a day and should be step 0.

1. **`impl` on enums.** No enum in the repo has methods. If enums can't have
   them, the methods below become free functions in the same module (for
   example `state_is_terminal(s: IssueState)`). Nothing else changes.
2. **Enums or wrapper structs inside `#[json]` structs.** Nothing in the repo
   shows an enum, or a struct with one field, encoding as a bare JSON string.
   Until that is proven, keep every `#[json]` field a plain string and parse
   after decoding ([4.3](#43-the-wiredomain-split)).
3. **Named string types** (Go's `type TeamId string`). If Lisette has them, id
   types encode to JSON for free and the wire/domain split gets thinner.
4. **`#[json(omitempty)] Option<string>` holding `Some("")`.** Does it emit
   `""` or drop the key? This is exactly the difference between "clear the
   assignee" and "leave it alone".
5. **Zero values.** This decides whether a witness can be forged by filling a
   struct with zero values. Two questions:
   - What does `..` put in an enum field? Probably the first variant.
   - Can another module write `writes.WritableIssue { .. }` for a struct whose
     fields are all private? Go allows `pkg.T{}` for a struct with unexported
     fields.

   See the zero-value rule below.
6. **Unused type parameters.** Does `struct Id<T> { value: string }` compile
   when `T` is unused? Go allows it. If Lisette does not, write the id types
   out one by one.
7. **Match guards and or-patterns** (`A | B =>`, `X(h) if h.status == 404 =>`).
   The sketches below avoid both.
8. **Methods on another module's type.** Go forbids them, and Lisette compiles
   to Go, so accessors on `models.Issue` must be declared in `models`.
9. **A method with the same name as a field.** A public field `state` and a
   public method `state()` probably compile to the same Go identifier, which Go
   rejects. Give accessors distinct names, such as `issue_state()` beside the
   `state` field.

**The zero-value rule.** If item 5 shows that `..` fills an enum field with its
first variant:

- **List the fail-closed variant first.**
  - `TeamScope { Only(TeamId), Every }`: a zero `Only` holds an empty id, which
    matches no team.
  - `Reach { Teams(..), Everything }`
  - `Mode { ReadOnly, ReadWrite }`
  - `Edit<T> { Keep, Clear, Set(T) }`
- **Consider reordering `pb.Caller` to `{ Member(string), Process }`.** Today
  its zero value would be `Process`, the board's full authority, which is the
  fail-open direction. A zero `Member("")` sends no token, so it is refused.
- **Make writes fail closed.** Write functions that take a witness should
  refuse an empty id, so a zero-filled witness is rejected even if it can be
  constructed.
- **Don't use `..` on structs that hold scope or authority fields.**

### 4.3 The wire/domain split

Keep the `#[json]` structs in `models` exactly as PocketBase sends them. Add
domain types next to them, and convert in one place in each direction:

```
PocketBase JSON ──decode──▶ models.* (wire: strings) ──parse────▶ domain types ──▶ commands, board
PocketBase JSON ◀─encode─── body (map or #[json])    ◀──to_wire── IssuePatch   ◀── commands, board
```

The cheapest form is accessor methods declared in `models` (4.2, items 8 and
9):

```lisette
impl Issue {
  /// The parsed state. An unknown value is an error, never a "?" glyph.
  pub fn issue_state(self) -> Result<IssueState, string> {
    IssueState.parse(self.state)
  }

  pub fn issue_id(self) -> IssueId {
    IssueId { value: self.id }
  }

  /// None when this read did not expand `team`, instead of a key like "-12".
  pub fn issue_key(self) -> Option<IssueKey> { … }
}
```

A stronger form is a separate domain struct,
`records.parse_issue(w: models.Issue) -> Result<records.Issue, string>`, whose
fields are already typed. Code holding a `records.Issue` cannot reach the raw
string at all. Use accessors on read paths, where they are cheap and
incremental. Use the domain struct on the write path, where the guarantee
matters.

Where each parse happens:

| Boundary | Raw input | Parsed into | Owner |
|---|---|---|---|
| argv | strings | `IssueKey`, `TeamSelection`, `IssuePatch`, `ListMode` | `flags` and each verb's `parse_*` |
| environment and config files | strings | `Context` | `config` / `main` |
| board form posts | `r.PostFormValue(…)` | `IssuePatch` and a new-issue form holding team-checked references | first lines of the handler |
| PocketBase records | `models.*` | `IssueState`, ids, `Access`, `MemberKind` | accessors in `models`, or `records` |
| PocketBase errors | status and body | `PbError` → `ClaimError` | `pb`, `claims` |
| `/api/lll/access` | JSON | `Access` | the viewer resolver |
| realtime frames | topic and JSON | `RecordEvent` | `realtime` |

---

## 5. Refactoring themes

### 5.A Team scope and identifiers

#### A.1 Replace the empty-string team with `TeamScope` (fixes a live bug)

**Today.** This is the code as it stands:

```lisette
/// The configured team's id, or "" for "every team". Only the listing verbs
/// and the unscoped web board tolerate that second answer; anything that
/// writes a team-owned record uses current_team.
fn configured_team_id() -> Result<string, string> {
  Ok(configured_team()?.map_or("", |t| t.id))
}
```

<sub>`src/commands/team.lis:465-470`</sub>

The comment states the rule, but nothing enforces it. `label edit` and
`label delete` break it:

```lisette
let label = records.resolve_label(configured_team_id()?, name)?   // label.lis:166 and :186
```

`project edit`, `project delete` and `project view` do the same
(`project.lis:185, 221, 236`). With no team configured, `resolve_label` filters
on the name alone and takes the first match from any team the token can see
(`src/records/labels.lis:12-20`). Label names are unique only within a team
(TASK-173), so two teams each having a `bug` label is normal, and
`lll label delete bug` can delete the wrong one. The same first-match shortcut
makes `issue next --exclude-label bug` exclude only one team's `bug` label.

The sentinel also compounds with other bugs. An unknown realtime topic decodes
as an empty issue whose team is `""`, and `board_snapshot("")` then renders
every team ([5.G.1](#g1-recordevent-including-the-reconnect)).

**Why a type fixes it.** A parameter typed `string` says nothing about whether
widening is allowed. The fix is to make *narrow* and *wide* different types:

```lisette
// src/models/ids.lis (module models)

pub struct TeamId { value: string }

impl TeamId {
  pub fn as_str(self) -> string { self.value }
  pub fn same(self, other: TeamId) -> bool { self.value == other.value }
}

/// How far a read may reach. `Every` is a deliberate widening: grep for it.
/// `Only` is listed first so that a zero-filled scope fails closed (section 4.2).
pub enum TeamScope {
  Only(TeamId),
  Every,
}
```

Each signature then says which of the two it accepts:

```lisette
// records: name lookups feed writes, so they never accept Every.
pub fn resolve_label(team: TeamId, name: string) -> Result<models.Label, string>
pub fn resolve_project(team: TeamId, name: string) -> Result<models.Project, string>

// Listings may be wide, and say so.
pub fn fetch_labels(scope: TeamScope) -> Result<Slice<models.Label>, string>

// Under Every, one name can match several labels, so return all of them.
pub fn labels_named(scope: TeamScope, name: string) -> Result<Slice<models.Label>, string>
```

```lisette
// team.lis: used by listing verbs only.
fn configured_scope() -> Result<TeamScope, string> {
  match configured_team()? {
    Some(t) => Ok(TeamScope.Only(t.team_id())),
    None => Ok(TeamScope.Every),
  }
}
```

The label commands become:

```lisette
let team = current_team()?                               // errors when no team is configured
let label = records.resolve_label(team.team_id(), name)?
```

`records.resolve_label(configured_scope()?, name)` is now a type error, because
a `TeamScope` is not a `TeamId`. The whole class of bug, a writer using the
wide answer, can no longer be written.

Three design points:

- **Why not `Option<TeamId>`?** `None` reads as "missing", and missing values
  get defaulted with `unwrap_or` or `map_or`, which is how `""` crept in.
  `TeamScope.Every` is a positive decision with a name.
  `grep -rn "TeamScope.Every"` gives the complete list of unscoped reads, which
  is the list a security review needs.
- **One result or many.** `resolve_label` returns one label because a name is
  unique within one team. Under `Every`, a name can match several labels, so
  `labels_named` returns a slice and the caller has to handle that. The
  first-match bug came from a signature that promised a uniqueness the query
  couldn't guarantee.
- **The query builder matches instead of comparing.** `query.scoped` and
  `query.filter` take a `TeamScope` and `match` on it. Dropping the team clause
  becomes an explicit match arm instead of an `if team_id == ""` branch. The
  team clause that `records/docs.lis` writes out by hand to avoid this trap can
  then be deleted.

**Migration.**

1. Fix the five call sites with `current_team()` now, as step 1 in section 6.
   No new types are needed for that.
2. Add `TeamId` and `TeamScope`, change the `records` and `query` signatures,
   and let the compiler list the callers.
3. Delete `configured_team_id`.

**Tests.** Set up two teams that each have a `bug` label.
`resolve_label(team_a, "bug")` returns team A's label, and
`labels_named(TeamScope.Every, "bug")` returns both.

#### A.2 Distinct id types

```lisette
// One generic form, if unused type parameters compile (section 4.2, item 6):
pub struct Id<T> { value: string }
// Used in signatures as Id<models.Issue>, Id<models.Label>, and so on.

// Otherwise, written out one by one:
pub struct IssueId { value: string }
pub struct LabelId { value: string }
pub struct ProjectId { value: string }
pub struct MemberId { value: string }
pub struct ClaimId { value: string }
```

Each id is built in one place, an accessor on the wire struct such as
`issue.issue_id()` or `label.label_id()`, and exposes `as_str()` for building
URLs.

Replace long positional parameter lists with structs that have named fields:

```lisette
pub struct IssueQuery {
  pub scope: TeamScope,
  pub states: Slice<IssueState>,
  pub assignee: Option<MemberId>,
  pub project: Option<ProjectId>,
  pub label: Option<LabelId>,
  pub search: string,
}
```

`delete.lis` then builds an `IssueQuery` with `label: Some(id)` and the other
fields written out. Swapping the label and project is a type error, and the
field names document the call. Following the zero-value rule, write every field
out here and don't use `..`, because `scope` is an authority field.

Two more changes of the same kind:

- `observed_id`, which returns `""` for "no claim", returns
  `Option<ClaimId>` instead.
- `update_assignment` takes an `IssueId` and an `Option<ClaimId>`, so the two
  can no longer be swapped.

**Where to stop.** Only identifiers and keys get their own types. Those are
values that are easy to confuse with siblings of the same representation and
that flow into queries. Titles, descriptions, names and other free text stay
`string`. Giving everything its own type creates conversion noise without
preventing any bug.

#### A.3 One `IssueKey` parser, and routes that compare teams

**Today.**

- **Two parsers disagree** about some keys:

  | Input | `split_issue_key` (`records/key.lis`) | `issue_of_team` (`serve_gate.lis`) |
  |---|---|---|
  | `ENG-+5` | ENG #5 (`strconv.Atoi` accepts a sign) | rejected (digits only) |
  | `ENG-007` | ENG #7 | the digit string `007` |

  The same string can therefore get different answers from the gate and from
  the fetch, which means an authorization question is answered twice.
- **The bare redirect mixes byte and rune offsets.** The `/issue/{key}`
  redirect (`serve.lis:367-371`) takes a byte offset from `strings.LastIndex`
  and passes it to `substring`, which expects rune indices. `records/key.lis`
  itself warns about this trap.
- **The routed team is never compared.** `issue_page` takes the routed team and
  the key as unrelated values. So `/t/LLL/issue/ENG-3` renders ENG-3 under
  LLL's rail and accent for full viewers (A5). It leaks nothing, but links on
  the page are built under the wrong team prefix.

**Typed version.**

```lisette
/// A team key as the server stores it: trimmed and upper-case.
pub struct TeamKey { value: string }

/// TEAM-NUMBER, with one grammar for the whole program: the team half as
/// normalize_team_key accepts it, then ASCII digits only, no sign, at least 1.
pub struct IssueKey { team: TeamKey, number: int }

impl IssueKey {
  pub fn parse(raw: string) -> Result<IssueKey, string>
  pub fn team(self) -> TeamKey { self.team }
  pub fn to_string(self) -> string { f"{self.team.as_str()}-{self.number}" }
  pub fn in_team(self, t: TeamKey) -> bool { self.team.same(t) }
}
```

What changes:

- **Leading zeros are decided once.** Accept `ENG-007`, normalize it to number
  7, and redirect a non-canonical URL to `/t/ENG/issue/ENG-7`.
- **One parser.** `ScopedViewer.sees_issue` takes an `IssueKey`, and
  `issue_of_team` is deleted.
- **Keys come from one accessor.** `models.Issue` gets
  `issue_key() -> Option<IssueKey>`, which returns `None` when the read did not
  expand `team`. The type shows that a key depends on how the record was
  fetched, so `"-12"` keys can no longer appear. The 43 hand-built keys become
  calls to this accessor.

Route parsing gives the mismatch its own variant, so every handler has to
decide what it means:

```lisette
pub enum IssueRoute {
  /// /t/ENG/issue/ENG-3
  Home(IssueKey),
  /// /t/LLL/issue/ENG-3: redirect to the issue's own team, or 404.
  Elsewhere { routed: TeamKey, key: IssueKey },
}

pub fn route_issue(routed: TeamKey, raw: string) -> Result<IssueRoute, string>
```

The bare `/issue/{key}` redirect becomes `IssueKey.parse(raw)?` followed by
`key.team()`, with no offset arithmetic.

#### A.4 Team-checked references, on both sides of the wire

**Today.**

- **Board create doesn't check relations.** `create_write` sends posted label
  and project ids to PocketBase unchecked. Its comment says this is deliberate,
  to save fetches (`serve_actions.lis:164-171`). `project_write` and
  `labels_write` do check membership, by fetching the team's list.
- **The server check skips full-access callers.** `checkNewRefs` returns early
  for a caller with access to every team (`gopb/team_scope.go:295-297`), and it
  runs only on API requests.

So a full-access board session can attach team B's label to a team A issue
(A1). The re-check rated this a low-severity data-integrity bug, because nobody
gains access. The board then shows a foreign label, which is exactly what
`without_foreign_refs` exists to scrub after the fact.

**The type-level idea.** Tell apart "an id somebody posted" and "an id known to
belong to this team":

```lisette
/// A relation target proven to belong to `team`. Built only by records,
/// from a read filtered to that team.
pub struct TeamRef<T> { team: TeamId, id: Id<T> }

/// The team's labels, projects and roster, fetched once per request.
pub struct TeamRefs { … }

impl TeamRefs {
  pub fn label(self, raw: string) -> Result<TeamRef<models.Label>, string>
  pub fn project(self, raw: string) -> Result<Option<TeamRef<models.Project>>, string>
  pub fn member(self, raw: string) -> Result<Option<TeamRef<models.Member>>, string>
}

pub fn team_refs(team: TeamId) -> Result<TeamRefs, string>
```

The board parses the whole form once into a typed request whose relation
fields are `TeamRef`s, and the write functions accept only those.
`create_write`, `project_write` and `labels_write` then share one check, and a
new handler can't send an id it didn't resolve. The extra fetches the old
comment worried about amount to one fetch, of the same data the form was
rendered from.

**The real fix is on the server** ([5.H.1](#h1-the-same-team-invariant-enforced-on-every-save)).
A validator there refuses a cross-team reference on every save, whoever the
caller. The client type gives a good error early; the server makes the rule
true. This is the general pattern throughout this document: *the server holds
the invariant, and the client type mirrors it.*

#### A.5 Filters as a type (optional, low payoff)

`query.quote` exists so that no caller pastes a value into a PocketBase filter
unescaped; `query.test.lis` has a test with a filter-breakout payload. About 30
call sites apply `query.quote` and `url.QueryEscape` by convention.

A `Filter` struct with a private field would turn that convention into a type.
It would be built only by `eq`, `contains`, `and` and the `TeamScope`
constructor, and encoded in one place.

Today's sites are all correct, except `watch.lis:257`, which pastes in a
server-issued id unquoted (safe in practice). Do this last, if at all. It only
works if `query` stays its own module, because privacy is per module.

### 5.B Issue vocabulary as enums

#### B.1 `IssueState`

**Today.** The states are listed in `query.states()`, in a `match` in
`display.glyph` that ends with `_ => "?"`, and in the init migration's select
values. On top of that are hand-written predicates: *terminal*
(`done || cancelled`) in about six places, and *pickable* (`todo || backlog`)
in three.

Adding a state such as `triage` compiles, and then goes wrong silently:

- the glyph prints `?`
- the predicates misclassify it
- `watch --ready` treats any issue blocked by it as blocked forever

**Typed version.**

```lisette
pub enum IssueState { Backlog, Todo, InProgress, InReview, Done, Cancelled }

impl IssueState {
  /// The one parser. Each arm uses the exact wire string from query.states().
  pub fn parse(raw: string) -> Result<IssueState, string> {
    match raw {
      "backlog" => Ok(IssueState.Backlog),
      "todo" => Ok(IssueState.Todo),
      // … one arm for each remaining wire value …
      _ => Err(f"unknown state '{raw}'"),
    }
  }

  pub fn wire(self) -> string { … }          // the inverse of parse
  pub fn all() -> Slice<IssueState> { … }

  /// Done and cancelled issues are closed.
  pub fn is_terminal(self) -> bool {
    match self {
      IssueState.Backlog => false,
      IssueState.Todo => false,
      IssueState.InProgress => false,
      IssueState.InReview => false,
      IssueState.Done => true,
      IssueState.Cancelled => true,
    }
  }

  /// The states an agent may pick up.
  pub fn is_pickable(self) -> bool { … one arm per variant … }
}
```

The `_` arm in `parse` is fine, because it matches a *string*, which has
unboundedly many values. The rule applies to matches on the *enum*.
`is_terminal` lists all six variants, so adding `Triage` stops this function
from compiling until someone decides whether triage is terminal. That compile
error is the point of the design.

The wire format stays a string (4.2, item 2). `models.Issue` gets
`issue_state() -> Result<IssueState, string>`, and writes take an `IssueState`.
`display.glyph`, `state_label`, `work_site_stale` and the board's columns
become exhaustive matches.

Add a test that `IssueState.all()` maps one-to-one onto the init migration's
select values. That turns the migration into a checked copy instead of a
drifting one.

#### B.2 `Priority`

**Today.**

- Priority is an `int`, and `-1` means "not given", next to the valid values 0
  to 4.
- The CLI's `check_priority` and the board's `priority_value` parse the scale
  in two different ways.
- `import_dir` turns an unknown priority into 0 without warning.

```lisette
/// The first variant is not called `None`, because that name belongs to the
/// prelude's Option.
pub enum Priority { NoPriority, Urgent, High, Medium, Low }

impl Priority {
  pub fn from_wire(n: int) -> Option<Priority>
  pub fn parse(raw: string) -> Result<Priority, string>   // a name or a digit; shared by CLI and board
  pub fn wire(self) -> int
}
```

"Not given" becomes `Option<Priority>` in a patch ([5.C](#5c-writes-as-typed-patches)),
so `-1` disappears. Import reports an unknown priority instead of guessing.

#### B.3 `Readiness`: one definition of "ready"

**Today, two rules disagree.**

- `issue next` and `issue list --ready` use `open_blockers` over
  `expand.blocked_by` (`issue.lis:2306`). PocketBase's `expand` silently leaves
  out a related record the reader can't see (another team, hidden, or
  deleted). So an issue whose only blocker is invisible counts as **ready**.
- `watch --ready` (`watch.lis:493-503`) treats an unknown blocker as open. So
  the same issue is **not ready**.

An agent running `lll issue next` can be handed work that `lll watch --ready`
says is blocked.

**Why a boolean can't fix this.** When the reader can't see everything, "is it
ready?" has three honest answers:

- yes
- no, because of these open blockers
- *can't tell*, because some blockers are invisible to this reader

A `bool` forces each implementation to fold the third answer into one of the
other two, and the two implementations folded it differently.

```lisette
pub enum Readiness {
  /// In a pickable state, and every blocker is closed.
  Ready,
  /// Has open blockers, or blockers this reader cannot see.
  Blocked { open: Slice<IssueKey>, unseen: Slice<IssueId> },
  /// Not in a pickable state.
  NotPickable(IssueState),
}

/// The one rule, used by `issue next`, `issue list --ready` and `watch --ready`.
/// Built from the issue's blocked_by ids rather than from expand, so a blocker
/// this reader cannot see lands in `unseen` instead of silently disappearing.
pub fn readiness(issue: models.Issue, states: Map<string, IssueState>) -> Readiness
```

The key change is reading the relation ids, which are complete, instead of the
expansion, which drops records the reader can't see. "Unseen" then gets its own
field.

The policy, whether `unseen` blocks `issue next`, becomes one line in one
function. This document recommends treating it as blocked, since an agent
shouldn't claim work that might be blocked, and printing the unseen ids so a
human can check. That choice belongs to the maintainer.

#### B.4 One `--json` shape for `issue list`

**Today.**

- **Plain `--json`** prints PocketBase's page: `page`, `perPage`, `totalPages`,
  `totalItems` and `items`.
- **`--ready`, `--blocked` or `--sort priority`** print
  `models.IssueList { items, totalItems }` instead, where `totalItems` is the
  filtered count of a single page (`issue.lis`, around lines 863-896).

A script reading `.totalPages` breaks as soon as someone adds `--ready`. And
`--ready` silently misses ready issues beyond the first page.

**Typed version.** Parse the mode once, so that "ready, page 3" cannot be
expressed:

```lisette
enum ListMode {
  Page { page: int, per_page: int },
  /// Always reads every page, then filters.
  Ready,
  Blocked,
}
```

Then emit one listing shape in every mode:

| Field | Page mode | Ready / Blocked |
|---|---|---|
| `items` | the page | every matching issue |
| `totalItems` | the server's total | the count of `items` |
| `complete` | `true` only on the last page | `true` |
| `page`, `perPage`, `totalPages` | present | absent |

Existing consumers of plain `--json` see the same keys as before, plus
`complete`. Readiness filtering uses `readiness` from B.3.

Pagination moves to the existing pager in `records/pagination.lis`. That covers
two groups:

- the duplicated pagination loops in `search.lis`, `doc_records.lis` and
  `issue.lis:2438`
- the single-page reads that silently truncate in `project view` and
  `webhook list`

### 5.C Writes as typed patches

#### C.1 `IssuePatch`

**Today.** `lll issue update` (`issue.lis:1263-1473`, about 210 lines):

- encodes "not given" with sentinel values
- enforces mutually exclusive flags with about eight hand-written checks
- decides "nothing to update" with a twelve-term conjunction
- builds the PATCH body by concatenating strings, such as
  `"\"state\":" + json_quote(state)?`

Create uses the typed `models.NewIssue`, while update spells the same fields
out by hand. A renamed field can therefore be right in one and misspelt in the
other. The board builds its own typed patches separately (`StatePatch`,
`IssueProjectPatch` and others).

**Typed version.** Every field of a patch has one of two shapes:

- **Can't be cleared** (title, state, priority): `Option<T>`, where `None`
  means "keep".
- **Can be cleared** (assignee, project): three states, keep, clear and set,
  which `Option` can only express by nesting.

```lisette
/// Keep is listed first because it is the safe zero value (section 4.2).
pub enum Edit<T> { Keep, Clear, Set(T) }

pub enum LabelEdit {
  Keep,
  Replace(Slice<LabelId>),
  Adjust { add: Slice<LabelId>, remove: Slice<LabelId> },
}

pub struct IssuePatch {
  pub title: Option<string>,
  pub state: Option<IssueState>,
  pub priority: Option<Priority>,
  pub assignee: Edit<MemberId>,
  pub project: Edit<ProjectId>,
  pub labels: LabelEdit,
  pub description: Option<DescriptionEdit>,
}
```

**Why `Edit<T>` instead of `Option<Option<T>>`.** Both have three states. But
`Some(None)` versus `None` is easy to mix up at a call site and doesn't say
what it does. `Edit.Clear` versus `Edit.Keep` does.

One function owns all of the flag logic:

```lisette
fn parse_update(p: flags.Parsed) -> Result<IssuePatch, CliError>
```

Once it returns, contradictory combinations no longer exist: there is no
`IssuePatch` value that means "replace the description *and* append to it".
`IssuePatch.is_empty()` replaces the twelve-term conjunction. The board parses
its forms into the same type, so the CLI and the board share one write path
([5.D.3](#d3-witnesses-and-why-they-need-their-own-module)).

#### C.2 Read-derived writes carry their stamp

**Today.** `--description-append` and `--description-replace` compute the new
description from the issue as read moments earlier, then PATCH the whole field
(`issue.lis:1354-1373`). A precondition is sent only if the user also passes
`--if-unchanged-since`. An edit that lands between the read and the PATCH is
silently overwritten, so the "surgical" edit clobbers someone else's change.

The server already supports preconditions (`gopb/precondition.go`), and
`patch_with_stamp` already exists. What's missing is anything that ties "this
value was computed from read X" to "this write must be conditioned on X".

**Typed version.** Make the computed value carry the version it came from:

```lisette
/// The `updated` timestamp of the record a value was derived from.
pub struct Stamp { value: string }

pub enum DescriptionEdit {
  /// The whole new text (--description, --description-file). Needs no read.
  Whole(string),
  /// These need the current text.
  Append(string),
  Replace { old: string, new: string },
}

pub enum DescriptionWrite {
  Blind(string),
  /// Computed from the read at Stamp; the PATCH must be conditioned on it.
  Derived(string, Stamp),
}

pub fn apply(edit: DescriptionEdit, current: models.Issue) -> Result<DescriptionWrite, string>
```

The write function takes a `DescriptionWrite` and sends `If-Unmodified-Since`
for `Derived`. Losing an update now requires deliberately unpacking the value
and discarding the stamp. When the user passes `--if-unchanged-since`, send
theirs instead.

The `/assignment` path is different. It needs no stamp for the assignee,
because it already arbitrates on the observed claim id.

#### C.3 Serialize in one place

Build the PATCH body from an `IssuePatch` in one function. There are two ways
to do it:

- **A map** (`Map<string, Unknown>`): `Keep` adds no key, `Clear` adds `""`,
  and `Set(x)` adds `x`. This doesn't depend on `omitempty` semantics.
  Recommended.
- **A `#[json]` struct** with `omitempty` on `Option` fields: only if item 4 of
  4.2 shows that `Some("")` encodes as `""`. Otherwise clearing an assignee
  silently does nothing.

Either way, the JSON field names live in one place shared with
`models.NewIssue`, and the `json_quote` string-building goes away.

### 5.D Authorization as values

#### D.1 `Access`: one shape for who may do what

**Today.** A member's access is four strings (`models.lis:34-47`):

| Field | Values | Note |
|---|---|---|
| `kind` | `"person"`, `"bot"`, `""` | |
| `owner` | a member id | meaningful only for bots |
| `scope` | `"all"`, `"teams"`, `""` | |
| `mode` | `"rw"`, `"ro"`, `""` | |

`Member.within` compares and writes these strings. It is safe only because both
of its callers first check for `scope == ""` (legacy rows). A typo such as
`"RW"` is just another string, and a `mode == "ro"` check then treats it as
read-write. The board flattens the same information into
`ViewerMember { rw, all }`, next to a separate list of teams.

```lisette
/// Fail-closed variants are listed first (section 4.2).
pub enum Mode { ReadOnly, ReadWrite }
pub enum Reach { Teams(Slice<TeamKey>), Everything }
pub struct Access { pub reach: Reach, pub mode: Mode }

pub enum MemberKind {
  Person,
  /// A bot may have no owner (the migrations' NO_OWNER case).
  Bot { owner: Option<MemberId> },
}
```

`Reach` holds team keys because the board routes by key. `TeamScope` holds team
ids because queries filter by id. Converting between them is a lookup in
`records`.

A bot's effective access, written as total functions instead of string
comparisons:

```lisette
impl Access {
  /// Never more than the owner's.
  pub fn within(self, owner: Access) -> Access {
    Access {
      reach: narrower_reach(self.reach, owner.reach),
      mode: narrower_mode(self.mode, owner.mode),
    }
  }
}

fn narrower_mode(a: Mode, b: Mode) -> Mode {
  match a {
    Mode.ReadOnly => Mode.ReadOnly,
    Mode.ReadWrite => b,
  }
}

fn narrower_reach(a: Reach, b: Reach) -> Reach {
  match a {
    Reach.Everything => b,
    Reach.Teams(mine) => match b {
      Reach.Everything => Reach.Teams(mine),
      Reach.Teams(theirs) => Reach.Teams(mine.filter(|k| theirs.any(|t| t.same(k)))),
    },
  }
}
```

**Where it is parsed.** `models.Member.access() -> Result<Option<Access>, string>`.
`None` is an explicit branch for "legacy server, no scope fields", instead of a
`scope == ""` guard that each caller must remember.

`MemberKind` makes a person with an owner impossible to express. Invites and
`member set` build an `Access` and serialize it in one place.

#### D.2 Resolve the viewer once per request

**Today.** `gated` calls `admit`, which resolves the viewer and returns only a
boolean, so handlers resolve it again through `board_viewer`. For a member-token
cookie, each resolution is an uncached round trip to `/api/lll/access`
(`serve_gate.lis:351-361`), about five per `issue_page` load (W2). Board-token
and link viewers resolve locally. Beyond the latency, the answers can differ
within one request if access changes partway through.

`Viewer` also has two spellings of full access: `Full`, and `Scoped` with
`member.all = true`. That is why `is_scoped(r)` exists, and why renderers take
a `scoped: bool`. A site that passes `false` shows foreign references.

```lisette
pub enum Viewer {
  /// The board token: the board's own member, every team.
  Board,
  /// A signed team link: read-only, no identity.
  Link(Slice<TeamKey>),
  /// A member's own token.
  Member(MemberViewer),
}

pub struct MemberViewer { id: MemberId, name: string, token: string, access: Access }

pub fn reach(v: Viewer) -> Reach {
  match v {
    Viewer.Board => Reach.Everything,
    Viewer.Link(teams) => Reach.Teams(teams),
    Viewer.Member(m) => m.access.reach,
  }
}
```

What changes:

- **One resolution per request.** `gated` resolves the viewer once and passes
  it to the page handler, whose type becomes
  `fn(http.ResponseWriter, Ref<http.Request>, Viewer)`.
- **Renderers match.** They take a `Reach` and `match` on it instead of
  receiving a boolean.
- **No misrouted full-access members.** A member with access to every team now
  has `Reach.Everything` and never goes through the scoped allowlist.

#### D.3 Witnesses, and why they need their own module

This is the witness pattern from [3.4](#34-capabilities-proof-as-a-value) made
concrete. A new module, `src/writes`, holds the witnesses *and* the writes that
consume them:

```lisette
// src/writes/writes.lis. Fields are private to this module.

/// Someone allowed to write, and the credential their writes ride.
pub struct Writer { caller: pb.Caller, author: MemberId, reach: Reach }

/// An issue this writer may change: read as the writer, inside its reach,
/// and its team is not archived.
pub struct WritableIssue { issue: models.Issue, caller: pb.Caller }

pub enum WriteRefusal { ReadOnly, AnonymousLink, OutOfReach, Archived, Missing }

pub fn board_writer(v: Viewer) -> Result<Writer, WriteRefusal>
pub fn cli_writer(ctx: Context) -> Result<Writer, WriteRefusal>

impl Writer {
  /// The one place the scope and archived checks live.
  pub fn writable_issue(self, key: IssueKey) -> Result<WritableIssue, WriteRefusal>
}

impl WritableIssue {
  pub fn issue(self) -> models.Issue { self.issue }
}

// The writes. Each one requires the witness, so none can run unchecked.
pub fn update(target: WritableIssue, patch: IssuePatch) -> Result<(), PbError>
pub fn comment(target: WritableIssue, body: string) -> Result<(), PbError>
pub fn claim(target: WritableIssue, agent: string) -> Result<ClaimId, ClaimError>
pub fn release(target: WritableIssue, observed: Option<ClaimId>, how: ReleaseAs) -> Result<(), ClaimError>
```

Three things make this a real guarantee rather than a naming convention:

1. **Module privacy.** Lisette hides non-`pub` fields per *module*, not per
   file. `src/commands` holds the whole CLI and the whole server, about 96
   files, and `Acting`'s private `caller` is already read from another file
   there (`serve_attachments.lis`). A witness declared in `serve_gate.lis`
   could be built with a struct literal anywhere in `commands`. In
   `src/writes`, only `writes` can build one. For the same reason, moving the
   server out of `commands` (W1) is a prerequisite, not a cleanup.
2. **The witness never hands out its credential.** If `WritableIssue` had a
   `pub fn caller(self) -> pb.Caller`, a handler could take the caller and
   write to a *different* issue. So the write functions live in the same
   module as the witness. This module is also the missing shared write layer
   (L1): `src/writes` is where CLI writes and board writes meet.
3. **Zero values fail closed** (section 4.2). The write functions refuse a
   witness with an empty issue id, in case `writes.WritableIssue { .. }` turns
   out to compile in other modules.

**What it buys.**

- The eleven `acting_as` → `who.issue` → `require_active_team` sequences
  collapse to `writer.writable_issue(key)?`.
- The client-side archived check (A2) lives in one function.
- A new board action that forgets the check doesn't compile, because there is
  no other way to call `writes.update`.

This is still client code. The server must enforce the archived and scope rules
on its own ([5.H.2](#h2-archived-teams-enforced-on-the-server)). The witness
makes lll's own code correct and gives good errors; it doesn't stop `curl`.

#### D.4 `ReleaseAs`: overriding a claim is a deliberate value

**Today.** Release and assignment take `force: bool, reason: string`. The board
passes `force = true` with an empty reason on every click (`assignee_write` and
`release_write` in `serve_actions.lis`).

The re-check found this is by design. Force is the intended override
(LLL-512/516): it writes a comment and needs a matching observed claim id, so
it is not a security hole. But a bare `true` at a call site carries no meaning,
and the reason the override comment is supposed to record is always empty.

```lisette
pub enum ReleaseAs {
  /// The caller holds the claim.
  Holder,
  /// Breaking someone else's hold. The reason becomes the override comment.
  Override(Reason),
}

/// Non-blank text. The only constructor refuses empty input.
pub struct Reason { text: string }
pub fn reason(text: string) -> Result<Reason, string>
```

Go mirrors it, so the server can't receive "force without a reason" either:

```go
// releaseAuthority is how a release was authorized: exactly one of these.
type releaseAuthority interface{ isReleaseAuthority() }

type asHolder struct{ memberID, agent string }

type override struct {
	memberID string
	reason   string // non-empty; enforced by newOverride
}

func (asHolder) isReleaseAuthority() {}
func (override) isReleaseAuthority() {}
```

The board then has to produce a `Reason`. That is a product decision: either a
confirmation dialog when the claim belongs to someone else, or a generated
reason such as "reassigned on the board by NAME".

Also route the holder's direct `assignee` PATCH through the same authority
function. Today the holder can clear the assignee without releasing (C1), which
leaves a live hold on an unassigned issue. With one function, both write paths
decide claim authority the same way.

#### D.5 Reads as the caller: `AttachmentRef`

**Today.** `attachments.read_file` always mints the file token and reads as
the server process, while uploads and removals take a `pb.Caller`. On the
board, the only thing stopping a scoped viewer from downloading another team's
attachment is a hand-written `if let Viewer.Scoped(v) = board_viewer(r)` block
in `serve_attachments.lis` (lines 54-66). If that block is removed in a
refactor, or a second download route is added, the bytes are served with full
authority.

```lisette
/// An attachment that exists on an issue. Built only by require_file.
pub struct AttachmentRef { issue_id: IssueId, name: string }

pub fn require_file(issue: models.Issue, name: string) -> Result<AttachmentRef, string>
pub fn read_file(caller: pb.Caller, file: AttachmentRef) -> Result<…, PbError>
```

Minting the token as the caller lets PocketBase's rules decide, as they already
do for writes. The scoped check in the handler becomes a second line of
defence instead of the only one. Because `require_file` now returns a value,
`read_file` and `remove` no longer repeat the filename check.

#### D.6 The structural fix: read as the viewer

D.1–D.5 narrow what the board does with its all-team identity. The end state is
to stop using that identity for viewer reads:

- Fetch with the viewer's member token (`pb.Caller.Member`), so PocketBase's
  collection rules decide what each viewer sees.
- Keep a board-side check only for signed team links, which have no token.

Then the hand-written filters stop being the only thing between a viewer and
another team's data. Those filters are:

- `scoped_route`
- `without_foreign_refs`
- `roster_for`
- the rail filter
- SSE's scoped payloads

**Cost.** Today one snapshot per team serves every viewer. Reading per viewer
makes the SSE fan-out more expensive, so cache snapshots by `Reach`, letting
viewers with the same reach share one, instead of caching per viewer. Do this
last (step 8).

### 5.E Typed errors

#### E.1 `PbError`: parse once at the HTTP boundary

**Today.** This is the current function in `src/pb/status.lis`:

```lisette
/// Decode the status field emitted by request/read_body, never digits in the
/// URL or response body. Transport and decoding failures have no HTTP status.
pub fn response_status(message: string) -> int {
  if !["GET ", "POST ", "PATCH ", "DELETE ", "PUT ", "HEAD ", "OPTIONS "].any(|method| message.starts_with(method)) {
    return 0
  }
  …
}
```

`read_body` formats the status into a string, and about twenty callers parse it
back out. That causes two problems:

- Any wrapping that adds a prefix turns the status into 0.
- A request that reached something other than lll (the wrong port, or a proxy
  page) looks the same as "record not found". So `actor()` and `token_member`
  answer "no such member" when the URL is simply wrong.

```lisette
pub enum PbError {
  /// No HTTP response: DNS, refused connection, TLS, timeout.
  Unreachable { url: string, cause: string },
  /// lll answered with an error.
  Api { method: string, path: string, status: int, message: string, code: Option<string> },
  /// Something answered that is not lll.
  NotLll { url: string, status: int },
  /// The response did not decode.
  Decode { what: string, cause: string },
  /// The stored token was refused.
  Token(TokenRefusal),
}

pub enum TokenRefusal { NotLoggedIn, Corrupted, Expired, Rejected }
```

`token_verdict`'s five strings (`"valid"`, `"corrupted"`, `"expired"`,
`"rejected"`, `"opaque"`) become an enum the same way, with one variant per
existing value.

Every `pb` verb returns `Result<T, PbError>`, and text is produced only at the
edges:

- **CLI:** `display(e) -> string`.
- **Board:** a flash renderer replaces the prefix-sniffing in `display_error`
  (`src/pb/error_display.lis`).
- **Realtime:** `auth_failure`, which currently searches for
  `"/api/realtime: 401"`, becomes a match on `Api` with status 401 or 403, or
  on `Token`.

#### E.2 Stable codes from the server

Lisette can't type Go's messages, so the contract has to be on the wire. gopb
adds a stable, machine-readable code to every refusal that clients branch on,
in the error's `data` object:

```go
// Refusal codes. Clients branch on these, never on the message text.
// Changing one is a breaking API change.
const (
	codeClaimHeld       = "claim_held"
	codeNeedsForce      = "needs_force"
	codeClaimChanged    = "claim_changed"
	codeNotClaimed      = "not_claimed"
	codeBotExceedsOwner = "bot_exceeds_owner"
)
```

Use a namespaced key such as `lll_code`, not `code`. PocketBase uses `data` for
per-field validation errors keyed by field name, so a collection field called
`code` would collide.

The change is additive. Old clients ignore the key, and new clients fall back
to today's behaviour when it is absent.

#### E.3 Domain errors: `ClaimError`

```lisette
pub enum ClaimError {
  HeldBy { holder: string, agent: string },
  NeedsForce { holder: string },
  /// The claim you observed was released or replaced: re-read and retry.
  Changed,
  NotClaimed,
  /// 404: the issue is outside your scope, or gone.
  Hidden,
  /// The server predates the claim routes.
  RouteMissing,
  Other(PbError),
}
```

**This fixes a live misdiagnosis.** `claims.transact` and `references.append`
turn every 404 into "the server does not support atomic claim operations —
update your server" (`src/claims/claims.lis:85-96`). But the current server's
`issueWritable` answers 404 for an issue the member can't see
(`gopb/team_scope.go:81-93`), deliberately, so that the issue's existence isn't
revealed. A scoped member who tries to claim an out-of-scope issue is therefore
told to upgrade their server.

With a type, `Hidden` and `RouteMissing` are different variants. `RouteMissing`
is chosen only when a capability probe says the route is absent; the CLI
already probes this way for idempotency.

**What goes away.** `issue.lis` matches on `ClaimError` exhaustively, so the
`--force -b "why"` hint is attached to `NeedsForce` and can't be lost when Go
rewords a message. These are deleted:

- the four `strings.Contains` checks
- `member.lis`'s check for `"bot never exceeds its owner"`
- `response_status` and `response_body`

#### E.4 `CliError` and exit codes

```lisette
pub enum CliError {
  /// Not a failure: printed to stdout, exit 0.
  Help(string),
  Usage(string),
  NotFound(string),
  Conflict(string),
  Auth(string),
  /// A PocketBase failure, with what the command was doing when it happened.
  Pb(string, PbError),
  Failure(string),
}

fn exit_code(e: CliError) -> int {
  match e {
    CliError.Help(_) => 0,
    CliError.Usage(_) => 2,
    CliError.NotFound(_) => 3,
    CliError.Conflict(_) => 4,
    CliError.Auth(_) => 5,
    CliError.Pb(_, error) => pb_exit_code(error),   // 404 → 3; 409, 412 → 4; 401, 403 → 5; else 1
    CliError.Failure(_) => 1,
  }
}
```

**Help stops being an error.** `Help` becomes a variant, so the
control-character marker (`flags.help_marker`) and the `HasPrefix` check in
`main` go away. So does a hazard: today a
`map_err(|e| f"{key}: {e}")` between dispatch and `main` would turn `-h` into an
error message.

**The codes are a public contract.** Agents and scripts depend on them, so
document them in `lll --help` and `docs/api.md`, and treat any change as
breaking.

**Compatibility.** Scripts that test for a non-zero exit keep working. Scripts
that test for exactly 1 need updating for usage and not-found errors.

#### E.5 Wrapping without losing structure

The `map_err(|e| f"{key}: {e}")` pattern is why statuses get lost. With typed
errors, the context goes into a field instead:

```lisette
let issue = records.fetch_issue(key).map_err(|e| CliError.Pb(f"reading {key.to_string()}", e))?
```

The message the user sees is built from both parts at the edge. The status
survives, both for the exit code and for any caller that branches on it.

### 5.F Explicit context

#### F.1 `--team` as a parsed value

**Today** (`src/commands/scope.lis:23-26`):

- The `--team` value is written to `LLL_TEAM`, plus `LLL_TEAM_FROM_FLAG=1`, and
  read back later by `config.load_traced()`.
- The team's origin is a string, `"env:LLL_TEAM"` or `"file:/path"`, which
  `team.lis` parses again with `HasPrefix` to word an error message.

The review found three consequences:

- **A repeated `--team` keeps the last value.** `--team A --team B` silently
  uses B. That is the kind of silent drop LLL-381 fixed for every other flag.
- **Per-verb `--team` declarations are dead.** `label create` and
  `project create` declare their own `--team`, but the pre-pass strips the flag
  before they parse it, so that branch never runs.
- **The marker can be inherited.** A `LLL_TEAM_FROM_FLAG=1` inherited from a
  parent `lll` would blame a real `LLL_TEAM` on a flag nobody typed.

```lisette
pub enum TeamOrigin { Flag, Env, File(string) }

/// Which team the user selected, and how. Not to be confused with TeamScope
/// (5.A.1), which is how far a read may reach.
pub struct TeamSelection { pub key: TeamKey, pub origin: TeamOrigin }
```

`flags.extract_team` returns
`Result<(Slice<string>, Option<TeamSelection>), CliError>` and refuses a second
`--team`. Error wording becomes a `match` on `TeamOrigin`. Both `os.Setenv`
calls, the marker variable and the prefix parsing are deleted.

#### F.2 A client value

```lisette
pub struct Client { url: string, credential: Ref<Credential> }

pub struct Context {
  pub client: pb.Client,
  pub team: Option<TeamSelection>,
  pub output: Output,
}

pub enum Output { Human, Json, Raw }
```

`main` builds the `Context` once, and commands receive it. This removes the
config reload on every call: `pb/client.lis:96-142` re-reads the files on
every request, and about 66 call sites resolve config or the current team. It
also makes commands testable against an `httptest` server.

Migrate gradually. Keep `pb.get(path)` and its siblings as thin wrappers over a
default `Client` while commands move over one at a time, and delete the
wrappers last.

#### F.3 A credential holder instead of `os.Setenv("LLL_TOKEN")`

Realtime refreshes the process token with `os.Setenv("LLL_TOKEN", …)`
(`realtime.lis`, around lines 225-230), and `pb/client.lis:286` rewrites it in
the middle of a request. A `Ref<Credential>` shared by the client and realtime
replaces both.

Realtime runs in its own task, so guard the swap, for example with a
`sync.Mutex` or an `atomic.Value` through Go interop. This also removes the
ordering dependency in `up.lis`, which relies on the environment being set
before later code reads it.

The re-check found that the admin password reaching child processes is mostly
theoretical, since the only children are `git` and a browser opener. The case
for F rests on testability and on making precedence visible, not on that leak.

### 5.G Typed events and wire frames

#### G.1 `RecordEvent`, including the reconnect

**Today.** Realtime delivers `Event { topic: string, data: string }`
(`realtime.lis:13-21`). Three problems follow:

- **Unknown topics fall into the issue handler.** The subscribed topics are
  listed in `serve.lis`. The dispatch in `serve_sse.lis` is an `if/else` chain
  whose final `else` sends every other topic to the issue handler. If someone
  subscribes to a new topic, say `labels`, and forgets the dispatch, its events
  decode as an empty issue whose team is `""`. `board_snapshot("")` then
  renders every team, so two sentinels compound.
- **Actions are strings.** They are compared in about eight places in
  `watch.lis`.
- **Consumers aren't told about reconnects.** When the stream drops and
  `realtime.reconnect` resubscribes, anything that changed during the outage
  stays stale until the next event for that team (W3). Favorites and views can
  stay stale indefinitely.

```lisette
pub enum Topic { Issues, Comments, Claims, Favorites, Views }
pub enum Action { Create, Update, Delete }

pub enum RecordEvent {
  Issue(Action, models.Issue),
  Comment(Action, models.Comment),
  Claim(Action, models.Claim),
  Favorites,
  Views,
  /// The stream dropped and came back. Anything may have changed.
  Resubscribed,
}
```

Decode once in the realtime reader, drop and log an unknown action at that
point, and send `RecordEvent` on the channel. Consumers `match` exhaustively,
which does three things:

- A new `Topic` breaks the build at every consumer until it is handled.
- Nothing can fall through to the issue handler.
- Every consumer has to say what it does after `Resubscribed`.

The reconnect gap (W3) therefore becomes a compile error until the bridge
re-snapshots every registered scope. `watch --json` can keep the raw payload
next to the parsed variant for its NDJSON output.

#### G.2 Datastar frames

**Today.** `patch_event` can't express a mode or a selector. As a result:

- **Frames are built by hand in three places:** `serve_actions.lis:504`,
  `serve_attachments.lis:44` and `serve_property_recovery.lis:14` each build a
  `datastar-patch-elements` frame themselves.
- **Action results are raw SSE text.** Actions return them as `Ok(string)`:
  sometimes empty, sometimes one event, sometimes two concatenated.

A frame that misses the `data: elements` prefix on a line, or the trailing
blank line, is ignored or merged with the next one by the browser, and drafts
are lost. That is the failure the `datastar-fragments` skill warns about, and
such a frame compiles without complaint.

```lisette
pub enum PatchMode { Morph, Replace }

pub enum Patch {
  Elements { html: string, selector: Option<string>, mode: PatchMode },
  Signals(string),
}

/// The only code that writes SSE framing.
pub fn encode(p: Patch) -> string
```

Actions return `Result<Slice<Patch>, …>`, and `finish_action` encodes them.
Add modes as they are needed. The change is small and uses only features the
repo already uses.

### 5.H One source of truth across Go, JS and Lisette

Types stop at a language boundary. Across one, three tools remain:

- put the invariant on the side that sees every write, which is the server
- give the wire a stable code
- write a conformance test wherever two languages encode the same rule

#### H.1 The same-team invariant, enforced on every save

`checkNewRefs` enforces a *caller-relative* property: the caller can see the
target. It also skips callers with access to every team. The board renders
against a *record-relative* invariant: an issue's labels and project belong to
the issue's team. A data invariant must not depend on who is writing. The board
process, a superuser, a migration and an internal `app.Save` all count.

```go
// sameTeam refuses a newly added relation whose target is in another team.
// It runs on every save, whoever the caller: there is no all-access shortcut.
// Only added ids are checked, so a legacy cross-team link does not block an
// unrelated edit (the same rule checkNewRefs follows).
func sameTeam(app core.App, record *core.Record) error {
	team := recordTeam(app, record)
	for field, target := range sameTeamRefs[record.Collection().Name] {
		ids := added(record.GetStringSlice(field), record.Original().GetStringSlice(field))
		for _, id := range ids {
			ref, err := app.FindRecordById(target, id)
			if err != nil {
				return validation.Errors{field: validation.NewError("validation_missing_ref", "no such "+target)}
			}
			if ref.GetString("team") != team {
				return validation.Errors{field: validation.NewError("validation_foreign_ref", "belongs to another team")}
			}
		}
	}
	return nil
}
```

**How to bind it.** Bind it to the record-validate hook, not the request hooks,
so it also covers internal saves. Check the exact hook name against the pinned
PocketBase version. `validation.Errors` is the form `gopb/references.go`
already uses.

**Decide per relation.**

- Labels and projects must share the issue's team.
- `blocked_by` may be cross-team on purpose; the readiness code handles foreign
  blockers. If so, leave it out of `sameTeamRefs` and keep the visibility check
  for it.

**Clean up existing data.** Before relying on the invariant, run a one-off
query to find existing cross-team links. Once the data is clean,
`without_foreign_refs` is dead code for new records.

#### H.2 Archived teams, enforced on the server

**Today (A2).** Several places check `archived`:

- the board, at about twelve call sites
- parts of the CLI
- `references.go`

These do not:

- `issueWritable`
- the `/claim`, `/release`, `/renew` and `/assignment` routes
- the collection rules
- `lll issue update`, comments, and a raw PATCH

**Fix.** Add the check to `issueWritable` and to request hooks for the
collections that belong to issues, with one refusal message and an `lll_code`.
The client's `WritableIssue` (D.3) then mirrors it.

#### H.3 Access rules: a conformance test first, then one table

The access model exists in three places: JS rule strings, Go
(`effectiveAccess`, `rosterSees`) and the board. Each rule migration rewrites
whole rule strings, so it must repeat every earlier clause. The comment in
`1791700000_bot_owner_scope.js` says that a clause missing there "would be
dropped".

1. **Conformance test (cheap; do it first).** Write a table-driven Go test:
   - Create one member per access shape: every team or some teams, read-write
     or read-only, person or bot with an owner. Create two teams.
   - Assert that list, view, create and update on records in each team succeed
     or fail exactly as `effectiveAccess` predicts.

   Drift between the JS rules and Go then shows up as a failing test.
2. **One table (only if drift keeps happening).**
   - Declare each collection's rule shapes once, including a list of
     write-only fields such as the webhooks `secret`.
   - Generate the rule strings from that table in a Go migration.
   - Have `/api/lll/access` emit `reach` and `mode` directly, so the board
     parses straight into `Access` (D.1).

#### H.4 The webhook secret

**Today.**

- **The secret is readable.** The `secret` field is plain text
  (`1789500000_webhooks.js:52`). The webhooks rule is the generic team read
  (`team("team")` in `1791700000_bot_owner_scope.js`), so read-only guests can
  read the secret and forge deliveries.
- **Delivery never re-checks access.** It doesn't check who registered the
  hook. The payload does filter the assignee against the team roster, so it
  doesn't leak foreign member data.
- **Deliveries aren't durable.** They run as goroutines with no outbox.

**Fix.**

- Add a migration that sets `hidden: true` on `secret` and gives webhooks their
  own rule tuple requiring read-write access.
- In Go, read the secret only through a type that can't be printed or
  marshalled:

```go
// webhookSecret never appears in logs or JSON.
type webhookSecret struct{ v string }

func (webhookSecret) String() string               { return "[redacted]" }
func (webhookSecret) MarshalJSON() ([]byte, error) { return []byte(`"[redacted]"`), nil }
```

This has a product consequence: owners can no longer read the secret back. Show
it once when the webhook is created and add a rotate command, the same model as
tokens.

#### H.5 Small conformance tests

- `IssueState.all()` matches the init migration's select values (B.1).
- Migration timestamp prefixes are unique. Today 1789500000, 1789700000 and
  1789900000 each appear twice, so their order falls back to filename sorting.
- `pb/README.md` stops documenting `pb_hooks/main.pb.js`, which no longer
  exists.

---

## 6. Order of work

```
 Step 1  live fixes, no new types ─────────────── independent; do first

 Step 0  verify Lisette ─┬─▶ Step 2  scope and ids ──┐
                         ├─▶ Step 3  errors ─────────┼─▶ Step 5  src/writes + viewer ─▶ Step 8  one source of truth,
                         ├─▶ Step 4  vocabulary ─────┘                                          reads as the viewer
                         ├─▶ Step 6  context
                         └─▶ Step 7  events and frames
```

| Step | Work | Depends on | Done when |
|---|---|---|---|
| 0 | Answer section 4.2's questions in a scratch module; record the answers on the lll board | — | every question has a recorded answer, and the sketches here are updated to match |
| 1a | Hide the webhook secret; give webhooks a read-write rule (H.4) | — | a read-only member's list of webhooks has no `secret` |
| 1b | Label and project edit, delete and view use `current_team()` (A.1) | — | a test with two `bug` labels deletes only the configured team's |
| 1c | Check archived in `issueWritable` and the claim routes (H.2) | — | writes to an archived team are refused through every route |
| 1d | Add the same-team validator for labels and projects, plus an audit query (H.1) | — | a full-access cross-team POST is refused |
| 1e | Description append and replace always send the read's stamp (C.2) | — | a concurrent edit makes the second write fail instead of being clobbered |
| 1f | Correct the comment at `gopb/claim_expiry.go:66-69`; make the expiry delete conditional (C5) | — | no expiry can delete a just-renewed claim |
| 2 | `TeamId`, `TeamScope`, `TeamKey`, `IssueKey`, `IssueRoute` (A.1–A.3) | 0 | `configured_team_id` is deleted; `grep TeamScope.Every` lists only listings |
| 3 | `lll_code` in gopb, then `PbError`, `ClaimError`, `CliError` and exit codes (E) | 0 | no `strings.Contains` on an error; `response_status` is deleted; exit codes are documented |
| 4 | `IssueState`, `Priority`, `Readiness`, `ListMode`, one listing shape, one pager (B) | 0 | no `_ =>` on states; `issue next` and `watch --ready` share `readiness` |
| 5 | Move the server out of `commands`; `Viewer` once per request; `Access`; `src/writes` with `Writer`, `WritableIssue`, `IssuePatch`, `ReleaseAs`, `AttachmentRef` (D, C.1, C.3) | 2, 3, 4 | every issue write takes a `WritableIssue`; one `/api/lll/access` call per request |
| 6 | `TeamSelection`, `pb.Client`, credential holder (F) | 0 | no `os.Setenv` outside tests |
| 7 | `RecordEvent` with `Resubscribed`; `Patch` frames (G) | 0 | `serve_sse` and `watch` match on `RecordEvent`; a reconnect triggers a re-snapshot |
| 8 | Access conformance test, then one rules table; the board reads as the viewer (H.3, D.6) | 5 | the conformance test is green; `without_foreign_refs` is deleted |

Every step can ship on its own. During a type migration, the compiler's error
list is the to-do list: change a signature, then fix every site the compiler
reports, one module at a time.

---

## 7. What not to do

- **Don't put enums or wrapper structs inside `#[json]` structs** until step 0
  proves they encode as plain strings. Parse after decoding instead.
- **Don't give free text its own type.** Only identifiers and keys benefit.
- **Don't treat client types as the security boundary.** The server enforces;
  the client mirrors.
- **Don't migrate everything at once.** Add accessors before changing fields,
  add wrappers before removing old functions, and move one module at a time.
- **Don't silence the compiler with `_ =>` during a migration.** Write the arm
  out. If a match really has a default, comment why.
- **Don't give a witness a public getter for its credential.** The capability
  leaks through it.
- **Don't zero-fill (`..`) structs that hold scope or authority fields.**
- **Don't generate JS rules before the conformance test shows drift.** The test
  is cheaper and may be enough.
- **Don't expect types to fix concurrency or durability.** The claim-expiry
  race (C5), the serial SSE bridge (W4) and the webhook outbox need ordinary
  engineering.

---

## 8. Checklist for new code

For reviewers, and for agents working the backlog:

- [ ] A function that feeds a write takes a `TeamId`, never a `TeamScope`.
- [ ] Every `TeamScope.Every` is a listing, and a comment says why.
- [ ] Input from argv, forms, PocketBase or realtime is parsed on the first
      line that sees it.
- [ ] No `match` on a domain enum has a `_` arm.
- [ ] Nothing branches on the text of an error.
- [ ] No `os.Setenv` outside tests.
- [ ] No `force: bool`; authority is a variant.
- [ ] A read-modify-write sends the read's stamp.
- [ ] New issue writes go through `src/writes`.
- [ ] A command emits one `--json` shape whatever its other flags.

Until the types land, cheap grep checks in the gate can catch regressions:

| Smell | Pattern to flag | Replace with |
|---|---|---|
| widening sentinel | `team_id == ""`, `map_or("", ` on team values | `TeamScope` |
| checked, then thrown away | `let _ = query.` | parse into an enum |
| branching on error text | `strings.Contains(e, "`, `.starts_with(` on errors | `PbError` / `ClaimError` |
| configuration in globals | `os.Setenv(`, `os.Getenv("LLL_` outside `config` and `main` | `Context` |
| authority as a boolean | `, true, "")` in claim calls | `ReleaseAs` |
| hand-built JSON | `json_quote(`, `"\"` concatenation | `IssuePatch` → body |
| catch-all on domain values | `_ =>` in a match on a state, topic or mode | exhaustive arms |
| hand-built SSE | `event: datastar-patch-elements` outside `serve_render` | `Patch` + `encode` |

This checklist could become a codebase skill (see the `codebase-skills` skill)
so that agents load it before touching these areas.

---

## Appendix A: finding index

The re-check column comes from an adversarial pass over each claim:
*confirmed* means the code supports it, and *partly* means the core is right
but a detail or the severity was corrected.

| ID | Finding | Re-check | Theme |
|---|---|---|---|
| A1 | Board create accepts another team's label or project ids; the server skips full-access callers | confirmed; re-rated low (data integrity, not escalation) | A.4, H.1 |
| A2 | Archived teams are read-only only in client code | confirmed | D.3, H.2 |
| A3 | Webhook secret readable by read-only guests; no access re-check on delivery; no outbox | confirmed, medium | H.4 |
| A4 | Access model kept in three or four hand-maintained copies | confirmed, medium | D.1, D.2, D.6, H.3 |
| A5 | `/t/LLL/issue/ENG-3` renders under LLL | confirmed, low | A.3 |
| A6 | Favorites and views written as the process; bare write routes use the boot team | partly, low (by design today; only full viewers reach these routes) | D.3 |
| C1 | The holder can clear the assignee without releasing the claim | confirmed, medium (only through a raw PATCH) | D.4 |
| C2 | Deleting a claimed issue releases the claim silently; a code comment says otherwise | confirmed, low (the cascade is deliberate; the comment is wrong) | step 1f |
| C3 | The board always forces claim writes | partly, low (force is the designed override) | D.4 |
| C4 | Description append and replace can overwrite a concurrent edit | confirmed, medium | C.2 |
| C5 | Claim expiry can delete a just-renewed claim | confirmed, low (narrow window) | not a type fix; step 1f |
| L1 | No shared write layer; update builds JSON by hand | partly, medium (claims and references already share one) | C, D.3 |
| L2 | Environment variables used as configuration | partly, medium | F |
| L3 | Errors are strings; status parsed out of text | partly, medium (a latent hazard more than an observed bug) | E |
| L4 | One exit code; help travels as an error | partly, low | E.4 |
| L5 | `issue list --json` has two shapes | confirmed, medium | B.4 |
| L6 | Duplicated pagination; single-page reads truncate | partly, low | B.4 |
| W1 | The server lives in `commands` and calls CLI helpers | partly, medium (22 production files, about 6.4k lines) | D.3 (prerequisite for witnesses) |
| W2 | Repeated uncached access lookups per request | confirmed, medium (member-token viewers only) | D.2 |
| W3 | No resync after a realtime reconnect | partly, medium (the next event or a reload catches up) | G.1 |
| W4 | SSE bridge is serial and silent on failure | confirmed, medium | not a type fix |
| W5 | Datastar frames built by hand | confirmed, low | G.2 |
| W6 | Migrations rewrite whole rules; duplicate prefixes; stale README | partly, low | H.3, H.5 |
| N1 | Label and project edit, delete and view can hit another team's record | new; confirmed in code | A.1 |
| N2 | `issue next` and `watch --ready` disagree on "ready" | new | B.3 |
| N3 | A 404 for a hidden issue is reported as "update your server" | new | E.3 |
| N4 | Bare `/issue/{key}` redirect mixes byte and rune offsets | new, low | A.3 |
| N5 | Attachments are always read as the process | new | D.5 |
| N6 | An unknown realtime topic falls into the issue handler | new | G.1 |
| N7 | A repeated `--team` keeps the last value; per-verb `--team` is dead code | new | F.1 |

## Appendix B: proposed types at a glance

| Type | Module | Replaces | Section |
|---|---|---|---|
| `TeamId`, `TeamScope` | `models` | `team_id: string` with `""` meaning every team | A.1 |
| `Id<T>` (or `IssueId`, `LabelId`, `ProjectId`, `MemberId`, `ClaimId`) | `models` | interchangeable id strings | A.2 |
| `IssueQuery` | `query` | six positional string parameters | A.2 |
| `TeamKey`, `IssueKey` | `records` (`key.lis`) | `split_issue_key`, `issue_of_team`, hand-built keys | A.3 |
| `IssueRoute` | server | an unchecked routed team | A.3 |
| `TeamRef<T>`, `TeamRefs` | `records` | unchecked posted relation ids | A.4 |
| `Filter` (optional) | `query` | quoting by convention | A.5 |
| `IssueState` | `models` | state strings in four places | B.1 |
| `Priority` | `models` | `int` with `-1` for "not given" | B.2 |
| `Readiness` | `records` | two disagreeing boolean rules | B.3 |
| `ListMode` | `commands` | `--ready` and `--blocked` as two booleans | B.4 |
| `Edit<T>`, `LabelEdit`, `IssuePatch` | `writes` | sentinels and hand-built JSON | C.1 |
| `Stamp`, `DescriptionEdit`, `DescriptionWrite` | `writes` | unconditioned read-modify-write | C.2 |
| `Mode`, `Reach`, `Access`, `MemberKind` | `models` | access strings; `rw` and `all` booleans | D.1 |
| `Viewer`, `MemberViewer` | server | `Full`/`Scoped` plus booleans; repeated resolution | D.2 |
| `Writer`, `WritableIssue`, `WriteRefusal` | `writes` | the `acting_as` sequence | D.3 |
| `ReleaseAs`, `Reason` | `writes` / `claims` | `force: bool, reason: string` | D.4 |
| `AttachmentRef` | `attachments` | `require_file` returning `()` | D.5 |
| `PbError`, `TokenRefusal` | `pb` | status parsed from text; verdict strings | E.1 |
| `ClaimError` | `claims` | substring matching on Go messages | E.3 |
| `CliError` | `flags` (or a new `cli` module) | `Result<(), string>`; the help marker | E.4 |
| `TeamOrigin`, `TeamSelection` | `flags` | `os.Setenv`; origin prefixes in strings | F.1 |
| `Client`, `Credential`, `Context`, `Output` | `pb` / `main` | environment variables; config reloads | F.2, F.3 |
| `Topic`, `Action`, `RecordEvent` | `realtime` | topic and action strings; silent reconnects | G.1 |
| `PatchMode`, `Patch` | server (`serve_render`) | hand-built SSE strings | G.2 |
