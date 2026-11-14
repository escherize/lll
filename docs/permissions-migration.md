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
