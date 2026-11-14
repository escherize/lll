# Team permissions and migration

Working design for LLL-793. This document describes the proposed user model and
verification requirements; it is not a claim that the feature has shipped.

## Authorization retains its evidence

Apply [Parse, don’t validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/)
and [Ghosts of Departed Proofs](https://kataskeue.com/gdp.pdf) to internal permission
interfaces: checking a permission produces a typed, resource-bound authorization
value. Mutation operations consume that value, not a separate raw object id and
an unrelated boolean check. This is internal proof-bearing API design, not a
replacement network protocol or capability URL system.

Permissions are mutable. A proof is about an actor, operation, resource and
current database transaction. Parse the actor again inside the write transaction,
including the current token key, effective ownership limits and archived-team
state. Mint no proof for a missing or hidden resource. Never cache the result in
a session or use one issue's proof on another issue. The mutation must use the
resource and database bound to the proof. Do not return a mutable record or
arbitrary database handle from the proof interface.

Go does not provide the rank-2 generative names used by the GDP paper. Use
package-private construction and operations plus an explicit scope-closed guard;
zero values and values retained beyond the callback must refuse use. This is a
practical runtime lifetime check, not a claim of full compile-time verification.
PocketBase collection rules continue to protect native records endpoints.


## User model

One server is one workspace. A workspace member can have no team access.
Workspace administration is a separate responsibility from team data access.
Team access is None, Viewer or Editor. Projects group work inside a team and
inherit that team's access. Sessions use the identity and grants of their
credential; a session name never adds authority.

An Editor can perform the existing team-content writes: issues, comments,
claims, documents, labels, projects and webhooks, including archive/delete
operations already supported for those records. Archived teams remain read-only.
An Editor cannot manage workspace roles, team memberships or team lifecycle.
A Viewer reads team content and can manage their own favorites/saved views.

Compatibility exception: an existing all-team read-write grant retains its
historical team lifecycle powers and, for independent people, invitation powers.
The management API identifies this as `legacy_management`. It does not promote
the person to Admin or authorize changes to other people's grants. Converting
to explicit team roles removes both that legacy grant and future-team coverage;
the preview reports both losses. Operators can assign Admin separately before
converting a legacy manager.

Workspace administrators can manage people and team grants. Administration
alone does not make private team content readable. Granting oneself access is
an explicit, audited grant operation, subject to the same revision check and
receipt as another membership change. Superusers remain infrastructure
operators and bypass data rules; they are not ordinary member identities.

Personal bots have independent credentials. Their effective grant in each team
is the intersection of their own grant, human owner's current grant and any
creating bot's delegation ceiling. Lost owner access takes effect immediately;
owner removal leaves bots denied and preserves attribution. Existing unowned,
operator-created bots retain their explicit grants. This migration does not
create a new workspace-owned service-account lifecycle or transfer personal
bots automatically when somebody leaves.
Disabling, removing or rotating a personal bot remains the owner's or
infrastructure operator's authority; a workspace Admin role alone does not
confer it. A creating bot may rotate its own bounded workers while its current
owner and grant conditions still hold, but cannot disable or remove them.

## Compatibility contract

Existing `scope=all` means all current AND future teams. It must survive upgrade
without expansion to today's finite list. Existing Viewer/Editor equivalents
and token keys must remain unchanged. Existing broad data access must not be
mistaken for consent to a new administration role; promotion is explicit.

Finite per-team roles are represented by readable teams and an Editor subset.
A preserved global read-write grant remains recognizable as a legacy all-team
grant. Converting it into finite roles is an explicit operation whose preview
shows the loss of future-team coverage; a single team dropdown must not do it
silently. Mixed grants must never be collapsed to global read-write.

New servers advertise the permissions capability and return per-team roles.
Legacy clients receive a conservative global write projection: mixed team
roles cannot be represented as global read-write. Their ordinary records API
writes still receive the authoritative team-specific decision. A legacy access
mutation against a mixed member must fail before changing any grant, with an
upgrade instruction. New clients must refuse unsupported role management on
old servers before writing. Profile edits must preserve committed grants even
when loaded before a concurrent permission change.

## Rollout and recovery

1. Back up the complete stopped PocketBase data directory, including auxiliary
   data, and record the installed binary version. Never copy a live WAL database
   piecemeal or run two server binaries against the same directory.
2. Rehearse against a restored copy with production-like identities. Produce a
   before/after grant report covering people, owned/delegated bots, read-only
   accounts, empty scopes, unowned operator bots and all-team grants.
3. Apply additive schema changes transactionally. Require identical effective
   access before/after for every existing identity and team, plus a newly
   created team for wildcard coverage. Verify no token key changed.
4. Deploy server support before clients. Verify old-client/new-server and
   new-client/old-server behavior, direct records endpoints, custom routes,
   subscriptions and board reads. Assign the initial member administrator using
   operator credentials; do not infer or silently promote administrators.
5. Enable mixed roles only after grant reports pass. Changes use previews with
   a revision guard, explain the source of effective access and retain an audit
   receipt without credentials. Exercise revoke and active-session behavior.
6. To roll back before mixed roles are used, verify the downgrade preflight and
   retained legacy grant equivalence. Once mixed grants exist, an old binary
   cannot express the model: refuse destructive down migration. Restore the
   verified backup with its matching old binary, accepting and explicitly
   reporting the loss of writes since that backup, or roll forward. Never
   round mixed grants up to global write for compatibility.

## Required evidence

- Algebra: per-team intersection and coverage, including wildcard/finite cases.
- Enforcement: Viewer cannot write Finance through any route while Editor can
  write Engineering; cross-team moves need destination write access too.
- Revocation: owner/creator narrowing, detachment, rotation, stale profile saves
  and active board/stream access cannot restore grants.
- Administration: no implicit private-data access, explicit auditable self-grant,
  no member/bot escalation through generic records writes.
- Migration: fresh install, populated upgrade, idempotent restart, failure
  rollback, matching-backup restore, future teams and both client-skew paths.
- Product: CLI and mobile board show roles and why access exists, distinguish
  workspace responsibility from team grants, and explain legacy all-team grants.

## Reproducible upgrade evidence

The permission fixture is deliberately optional for older release rehearsals;
its baseline must support the 1.7 member/bot/creator contract:

```sh
python3 scripts/rehearse_upgrade.py --before /path/to/lll-1.7.0 \
  --after /path/to/candidate --permissions --report /tmp/permissions-upgrade.json
python3 scripts/test_team_roles.py /path/to/candidate \
  --report /tmp/team-role-enforcement.json
```

The first command creates ten distinct identities (people, empty scopes,
unowned and personal/delegated bots), records actual read/write decisions,
upgrades the populated database, reuses the original member credentials and
compares those decisions. It tests a team created after upgrade, then starts
the old binary on the stopped pre-upgrade backup and compares the original
matrix again. Operator authentication is renewed after boot; member tokens
are not renewed. A passing receipt is baseline-preservation evidence, not
proof that every new role-management feature works.

The second command checks new mixed-role enforcement, source/destination
moves, native/custom route agreement, self-escalation refusal, hidden roster
probes, safe legacy mutation refusal, bot inheritance and owner revocation.
Both commands own throwaway databases and accept no hosted server URL.


## Workspace administration and receipts

Migration assigns every existing identity workspace role Member. Initial Admin
promotion is an explicit operator action. Admin is available only to independent
people; bot ownership and workspace responsibility cannot be combined.
Administration reveals team and member metadata needed to manage grants, not
private issues or documents. Self-granting private team access requires the
same revision-guarded operation and audit event as granting another person.

The permissions endpoint exposes a revision and a preview. Applying a change
against an older revision returns a conflict without modifying grants. Unknown
operation fields and invalid roles are rejected before a writable target exists.
A workspace role change preserves data grants exactly. A non-operator cannot
remove the final Admin; an operator can recover or reassign administration.

Permission events contain only the changed grant/ownership/responsibility fields
and the authenticated actor. They contain no token, password or email. The grant
and its event share one transaction: failure to save the event rolls back the
grant. Preview writes nothing. Native member mutations and automatic delegation
narrowing are recorded too; automatic changes have actor kind System. Stale
profile saves preserve committed grant fields and do not invent duplicate events.
Events cannot be created through the records API or updated, even by operators;
operator deletion is explicit retention, as for the existing content audit log.


## CLI workflow

Inspect the workspace roster and a person's grants with an Admin member token
(or explicit operator credentials):

```sh
lll member permissions
lll member permissions Alice --json
lll member access Alice --team ENG --role editor --preview --json
lll member access Alice --team ENG --role editor --revision REVISION_FROM_PREVIEW
lll member access Alice --team FIN --role viewer
```

`--role none` removes only the named team's grant. `--workspace-role admin`
changes responsibility independently of data grants. To assign the initial Admin,
the operator authenticates explicitly without saving or sharing its credential:

```sh
lll member access Alice --workspace-role admin \
  --admin-email operator@example.com --admin-password -
```

A configured member token takes precedence over inherited operator environment
credentials. The password `-` is read privately from stdin. These commands never
print credentials. New role-management commands check server capabilities and
refuse older servers before sending a mutation. Legacy scope/mode flags remain
operator-only and cannot be combined with the role-management flags.

`--preview` returns before/after states and no audit event. To convert a retained
all-team grant, supply `--convert-all-teams` explicitly and inspect the reported
loss of future-team coverage and legacy management rights. Keeping the selected
team's role unchanged still performs an explicitly requested conversion, so all
current roles can be preserved while future-team coverage is removed. Use `--revision` when
applying a previously reviewed preview; a stale revision is a refusal, not an
automatic retry. JSON stdout contains only the state or receipt.
