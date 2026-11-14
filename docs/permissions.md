# Identity, organization and permissions

The v1.7 release is the deployed baseline for this work. LLL-793 adds the
per-team and workspace roles described below; its implementation branch and
this document do not establish that a server has been upgraded. Follow
[the migration procedure](permissions-migration.md) before enabling those roles.

## Organization

One server instance is one workspace. A workspace contains teams. Every issue,
document, label and project belongs to one team. An issue can belong to a
project and can have child issues within its team. A project groups work; it
does not create another privacy or permission boundary.

## Identity and effective access

A member is an identity, either a person or a bot. Its token identifies the
actor for CLI calls, browser actions and attribution. An invitation can create
a person or add grants to an existing independent person without replacing
that person's token. A team link is a read-only identity scoped to its team.

A bot can have a human owner. Its effective access is the intersection of its
own grants and the owner's current grants. A bot creating another worker also
bounds that worker by its own access, while both retain the same human owner.
Narrowing, detachment and credential retirement cannot restore old authority
through a cached login. Owner, creator and workspace Admin are distinct
relationships. A session or agent label coordinates work; it grants no access.
Personal bot disable/removal and token control remain with its owner or the
infrastructure operator; workspace Admin alone does not grant those powers.
A creating bot can rotate its bounded workers while its owner and grants remain
valid, and cannot disable or remove them.

In v1.7, a member has a readable set of teams (or all current and future teams)
and one read-only/read-write mode across that set. Different roles in different
teams cannot be represented by that release's clients.

## Per-team roles in the LLL-793 candidate

| Team role | Effective content access |
| --- | --- |
| No access | Team content is hidden |
| Viewer | Read team content; manage personal favorites and saved views |
| Editor | Viewer access plus existing team-content writes, including deletion |

Archived teams remain read-only for every actor. Moving content requires Editor
access in both source and destination teams. Projects inherit their team's
roles. The management screen shows both the assigned grant and effective access,
so an owner's restriction on a bot is visible.

Workspace Admin is separate: it manages people, team grants and team lifecycle.
It grants no private issue or document access by itself. Admins can explicitly
grant themselves team access; such changes are recorded. Only an independent
person can be Admin. An operator assigns the first Admin explicitly; migration
promotes nobody.

Existing all-team read-write grants retain their historical management powers
as a compatibility grant. They do not automatically become Admins. Converting
them to individual team roles requires an explicit preview and confirmation:
future-team coverage and the legacy management grant are both removed.

## Credentials and enforcement

Personal tokens are suitable for browser and CLI sign-in. Invitation codes are
single-use credentials, not reusable team tokens. Owned bots use their own
credentials unless a person deliberately uses their personal identity for work.

Operator credentials bootstrap and recover the server; keep them separate from
personal sign-in. The shared board credential resolves to the configured board
member; it does not define an independent permission system. A process credential
is never a substitute for a viewer's credential when reading board content.

PocketBase collection rules protect native reads and writes, including direct
API access. Server request hooks and custom routes enforce additional invariants.
Live fragments read with the viewer's credential and streams recheck grants.
Internal write APIs bind fresh actor, resource and operation to their transaction;
[the authorization design](permissions-migration.md#authorization-retains-its-evidence)
explains the typed proof boundary and Go's lifetime limitations.

The complete native rules are pinned in
[`scripts/fixtures/collection_rules.json`](../scripts/fixtures/collection_rules.json).
The board's historical `scoped-access-invites` PRD records earlier decisions and
sketches; it is not the current rule specification. See also
[invitation behavior](inviting.md).
