# LLL-402: lll agent DX fleet plan

Status: approved initial cases 01 and 05; execution is in progress. The user
said go after reviewing this plan and the first briefs on 2026-09-18.
Other cases remain a roadmap requiring separate review.

Source: [agent-dx-fleet](https://github.com/metabase/agent-instructions/blob/main/bryan/skills/agent-dx-fleet/SKILL.md),
main skill blob `f76bc9c4b7a44d4ec13ff67106e60840f5732ea1`. The design, report
schema, lessons, rules template and lifecycle scripts were read as well.

## Approved initial scope

Run case 01 (tier 1) and case 05 (tier 2), in that order, with ten fresh workers
per case. Other cases are a prepared roadmap, not approval to run them. Use the
combined main binary after LLL-372 and LLL-475 pass main verification; record its
commit and SHA-256. This evaluates the tool people will receive rather than a
known earlier credential/banner defect.

Use Agent fallback: ten workers in batches of at most three, then a fresh
reviewer. Proposed worker model: `gpt-5.6-luna`, the available cheap worker model;
the reviewer inherits the parent model. The external skill's `haiku`/`opus`
Workflow models and Workflow tool are unavailable here. Each worker receives
only its rules and slot paths, without this implementation conversation. The
reviewer reads every raw report, writes per-worker summaries and buckets issues.
The first pass costs twenty worker launches plus two reviewer launches. Fixes
or failed-case reruns require a new recorded run, not fabricated success.

## Isolation and provisioning

Every worker gets a separate loopback board, database, working directory and
HOME/config root below a temporary run directory, and one existing bot identity
with a token in `conn.txt`. No hosted team, member or credential is used. The
controller owns all processes, seeds fixtures and keeps its own credentials
outside worker directories. Every connection/credential file is 0600 in a 0700
directory. Workers use a provided CLI wrapper that reads connection facts,
clears inherited LLL/XDG settings, sets the isolated home and invokes the pinned
binary from their own directory. They never copy tokens into prompts or reports.

For each worker, seed team FLEET, labels `bug`/`docs`, project `Fleet sandbox`, a
controller person, one bot, three distinct issues and a decision doc. Case 01's
target has title `Retry loses the issue comment`, priority 2 and description
`A socket reset caused the retry to skip the comment. Preserve one comment and
report the saved result.` Decoys have unrelated titles and descriptions. Store
all seeded IDs and complete before-state in controller receipts.

The implementation is `scripts/agent_dx_fleet.py`, with fake lifecycle/isolation
checks in `scripts/test_agent_dx_fleet.py` registered in the full gate.

Readiness requires the complete URL/token/team tuple, the owned board banner,
a live owned child and authenticated access as the expected bot. A nonempty
connection file alone is insufficient. The upstream provision script currently
uses file size as readiness and the caller's umask; the real run uses the
owning controller directly instead. Its teardown
comment says process group but actually signals immediate descendants and later
reuses saved PIDs. Use an owning controller that terminates, waits/reaps and
only escalates still-live children it owns. Test these harness properties with
fakes before real provisioning; count harness failures separately from lll.

## Cases and independent ground truth

All names/comment prefixes include the worker number. Instances and fixtures are
fresh between cases/reruns. Read before acting when measuring a state change.

| Case | Tier | Task | Ground-truth artifact/check |
| --- | --- | --- | --- |
| 01 | 1 | Find the retry issue, read it fully and restate the cause in a comment | Exactly one `fleet-01-NN:` comment on the seeded target, by that worker bot; issue fields and decoys unchanged |
| 02 | 1 | Find the seeded decision by body text and explain its rejected option | One `fleet-02-NN:` issue comment linking the correct decision slug and naming the rejected option; no doc mutations |
| 03 | 1 | List todo issues by label and priority, then report matching keys | Report keys equal a controller REST query; all records unchanged |
| 04 | 1 | Inspect claim/author identity on the target and explain ownership | Report matches controller member/claim/creator records; no identity creation or edits |
| 05 | 2 | Create one issue with title, description, state, priority, label and project | Exactly one worker-title issue with all six fields correct, created by that worker bot; no seed changes |
| 06 | 2 | Create a wiki doc with a unique slug and multiline body | Exactly one doc with exact slug/body/kind/team; no unintended links |
| 07 | 2 | Add one comment using stdin with quotes and multiline text | Exactly one comment with byte-exact expected body and bot author |
| 08 | 2 | Create an issue assigned to the existing worker bot | One issue whose assignee matches the seeded bot; no new members |
| 09 | 2 | Add a finding tied to a path and read it back two ways | One finding with exact path/body, retrieved by list and near-path; no duplicates |
| 10 | 3 | Read, claim, start, close with evidence and release | Target done with evidence comment, no claim, correct creator; decoys unchanged |
| 11 | 3 | Start an issue and identify every state change | Controller before/after diff agrees with report; no branch/config changes |
| 12 | 3 | Update title and priority while preserving unrelated fields | Exact two-field change; description, relations and comments preserved |
| 13 | 3 | Add and remove one blocker twice | Expected dependency list without duplicates; second operations harmless; unrelated blockers retained |
| 14 | 3 | Triage a filtered stale set, leaving recent and foreign-state decoys | Only controller-selected IDs change; exact state/comment artifacts |
| 15 | 3 | Retry keyed issue creation after reading the first result | Exactly one issue per key/team with expected payload and unchanged conflicting retries |
| 16 | 4 | Two roles concurrently rename and comment on one object | Both changes survive on one issue; no lost comment or duplicate |
| 17 | 4 | Wait for a partner's transition with bounded watch | Consumer report matches producer event; process exits before deadline; no polling-created writes |
| 18 | 4 | Hand off a finding/decision to a fresh reader | Reader's link and explanation match the producer artifact; retrieval works by two supported paths |
| 19 | 4 | Recover from plural noun, invalid state and unknown flag | Exactly three intentional calls recorded; final valid artifact correct; reviewer ranks error usefulness |
| 20 | 4 | Complete a bounded issue loop using only board context | Claimed/read/worked/evidenced/done/released artifact and linked reasoning; decoys unchanged |

Cases 16-18 need paired identities on a dedicated shared fixture instead of
per-worker servers. Their separate role rules and bounded waiting must be
reviewed before launch. Do not infer approval for coordination from the initial
independent cases.

## Judge, report, repair

Write independent REST checkers before provisioning. Compare actual records to
controller receipts, including decoys, duplicate counts, exact fields and
comment authors. Worker `done` is a claim, not the pass signal. Save sanitized
raw reports (`report.json` and `report.md`), summaries, review, checker output,
model/commit/binary fingerprints and a table of case/run/truth/failures/workers.

Classify each failure as tool, harness or task-design before counting. A case
passes when all ten ground-truth artifacts exist and fewer than two workers hit
a tool-owned failed invocation. Repeated classes or a reviewer-designated blocker
become separately claimed lll issues; do not mix repair into this audit branch.
Fix the owning component and rerun the same case with fresh workers/fixtures
before advancing. An unresolved owner decision is a handoff, not an invented
policy. Stop after the approved initial cases and present the evidence before
expanding the run.

Teardown every owned listener and verify it is gone, redact stored evidence,
keep the durable reports and remove disposable token/data files. LLL-402 remains
open until the approved real runs and skill-friction corrections are verified.
