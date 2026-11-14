# Permissions for people and agent workers

lll is a coordination backbone for people and agent workers: a shared record
of work with access bounded by team roles and delegation. Claims record who
has taken a task; findings, decisions and handoffs keep context available
to the next worker. Permissions determine which parts of that record each
identity can read, change or delegate.

lll began as a Linear-style issue tracker: teams, issues, states and projects.
As people added agents, the board also became the place to coordinate work
across sessions and machines. A task could pass between workers while its
claims, comments, findings and decisions stayed available with attribution.

That introduces a further requirement: each worker needs access appropriate
to its work, and delegated access must remain bounded when its owner's or
creator's access changes. In 1.8, lll separates identity, team content access,
workspace administration and bot delegation. People and external agent tools
choose, launch and run the workers; lll records their work and enforces access
to the board.

This guide describes lll 1.8.0. Upgrading from 1.7 preserves existing grants
and member credentials. Follow [the migration procedure](permissions-migration.md)
before enabling per-team roles; the operator explicitly assigns the first Admin.

## Organization

One server instance is one workspace. A workspace contains teams. Every issue,
document, label and project belongs to one team. An issue can belong to a
project and can have child issues within its team. Projects group work and
inherit their team's access.

## Identity and effective access

A member is an identity, either a person or a bot. Its credential identifies
the actor for CLI calls, browser actions and attribution. An invitation can
create a person or add grants to an existing independent person without
replacing that person's token. A team link uses a read-only identity scoped
to its team.

A session or agent label distinguishes workers sharing a credential for
coordination and attribution. It grants no access. Separate bot credentials
let workers act under distinct identities; their permissions still follow
the team grants and delegation rules below.

## Per-team roles in 1.8

| Team role | Effective content access |
| --- | --- |
| None (No access in the board) | Team content is hidden |
| Viewer | Read team content; manage personal favorites and saved views |
| Editor | Viewer access plus existing team-content writes, including deletion, subject to record-specific rules |

Editor covers issues, comments, claims, documents, labels, projects and
webhooks. Rules such as comment authorship and claim ownership still apply.
Archived teams remain read-only for every actor. Moving content requires
Editor access in both source and destination teams, and must satisfy the
record's reference constraints. Projects inherit their team's roles.

An Editor cannot manage workspace roles, team memberships or team lifecycle
by virtue of that team role. The Permissions page shows both assigned grants
and effective access, including restrictions from a bot's owner or creator.

## Workspace administration

Workspace Admin manages people, team grants and team lifecycle. It grants no
private issue or document access by itself. Admins can explicitly grant
themselves team access; these changes are audited. Only an independent person
can be Admin. An infrastructure operator assigns the first Admin explicitly;
migration promotes nobody.

Existing all-team read-write grants retain their historical management powers
as a compatibility grant, including invitation powers for independent people.
They retain access to future teams and do not automatically become Admins.
Converting an all-team grant to individual team roles requires an explicit
preview and confirmation: future-team coverage and the legacy management grant
are both removed. Admin can be assigned separately when needed.

## Bot ownership and delegation

A bot can have a human owner. Its effective access in each team is the
intersection of its own grant and the owner's current grant. When a bot creates
a worker identity, that identity retains the same human owner and is also
bounded by the creating bot's access. Narrowing either limit narrows the worker.
Owner removal leaves personal bots denied while preserving attribution.
Existing unowned, operator-created bots retain their explicit grants.

Owner, creator and workspace Admin are distinct relationships. Disabling,
removing or rotating a personal bot remains its owner's or the infrastructure
operator's authority; workspace Admin alone does not confer those powers.
A creating bot can rotate its bounded workers while its owner and grants
remain valid, and cannot disable or remove them. Detachment and credential
retirement cannot restore old authority through a cached login.

For example, a person who is Editor in Engineering and Viewer in Finance can
own a bot with those same grants. A worker using an identity created by that
bot is bounded by both the person and the creating bot. If the creator loses Engineering access,
its worker loses that access too, even if the person's grant is unchanged.

## Manage access and bring people in

The available surfaces serve different tasks:

| Task | Current surface |
| --- | --- |
| Inspect and change team grants or workspace responsibility | The **Permissions** page at `/permissions`, or `lll member permissions` and `lll member access`; changes support preview and apply |
| Create a personal bot | **Add a bot** in the sidebar for an eligible person with write access, or `lll bot create` |
| Add a basic member account | **Members** settings; this is an account form |
| Set passwords or mint credentials with operator authority | **Access** settings; each privileged action requires operator credentials |
| Create single-use invitation links | `lll invite create`; link creation is currently a CLI workflow |

Invitation links can grant Viewer or Editor access to named teams. A new
visitor joins as a person; an existing independent person adds the invited
grants while keeping their identity and token. The setup page provides CLI
login guidance and, for eligible people, a command to create their own bot.
See [inviting people and their agents](inviting.md) for the steps and how to
handle a partially completed group of invites.

Creating invitations requires a workspace Admin, an infrastructure operator,
or an independent person with a retained legacy all-team read-write grant.
Editor access to a team alone does not authorize invitations. There is no
separate team inviter permission in 1.8.

A scoped invitation permission and a quick invitation form in the board are
proposed improvements. They are not available in this release; the current
invitation workflow uses the CLI and the authority described above.

## Credentials and enforcement

Personal tokens work for browser and CLI sign-in. Invitation codes are
single-use credentials. Bots use their own credentials; a person using a
personal token for agent work attributes that work to their own identity.

Operator credentials bootstrap and recover the server. Superusers bypass
data-access rules and remain separate from ordinary member identities and
workspace Admin. The shared board credential resolves to the configured board
member. Board content is read with the viewer's credential, including when the
viewer has narrower access than the board process.

PocketBase collection rules protect native reads and writes, including direct
API access. Server request hooks and custom routes enforce additional
invariants. Live fragments read with the viewer's credential and streams
recheck grants. Internal write APIs bind fresh actor, resource and operation
to their transaction. [The authorization design](permissions-migration.md#authorization-retains-its-evidence)
explains the typed proof boundary: Go uses runtime scope-lifetime guards here,
so this is not a claim of full compile-time lifetime verification.

In 1.7, a member had a readable set of teams, or all current and future teams,
and one read-only/read-write mode across that set. Those clients cannot
represent different roles in different teams. The
[migration and compatibility contract](permissions-migration.md) describes
preserved credentials, client compatibility, explicit conversion and recovery.

The complete native rules are pinned in
[`scripts/fixtures/collection_rules.json`](../scripts/fixtures/collection_rules.json).
The board's historical `scoped-access-invites` PRD records earlier decisions
and sketches; use the current contract and migration guide for implemented
behavior.
