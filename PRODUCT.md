# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Developers and their coding agents coordinating work on shared projects, in the
terminal first and a browser second. [inferred from project PRD, confirmed in
session] The web board's primary viewer is a developer glancing at team state,
or a wall/secondary display left open — dark rooms, editor-adjacent, low
ambient light.

## Product Purpose

`lll` is a shared record for people and agent workers coordinating development.
It began as a Linear-style issue tracker and now connects tasks and claims with
durable findings, decisions, attribution and handoffs. Team roles and bounded
bot delegation control access to that work. The CLI is the primary interface;
the live web board lets people follow and update it. Success means workers can
resume with the context previous workers recorded, and people can see who is
doing what.

## Positioning

A self-hosted coordination backbone for people and agent workers, distributed
as one binary with PocketBase compiled in and served in-process. The shared
board and agent-facing CLI keep work and its reasoning available across
sessions and machines. People and external agent tools launch and run workers;
lll coordinates their work through claims, a durable record and bounded access.

## Operating Context

Changes arrive continuously from CLI, agents, and other browsers over one SSE
stream; the board must absorb live morphs (cards moving columns) without
disorienting the viewer. Server-rendered Go templates + Datastar; templates and
static assets are embedded in the binary.

## Capabilities and Constraints

- Fixed six-state workflow: backlog, todo, in-progress, in-review, done, cancelled.
- Priorities 0-4 (none/urgent/high/medium/low). Assignees, projects, labels, comments exist.
- Web actions: create issue, change state (drag between columns, reorder within
  one), inline field edits on issue pages, markdown comments, and a settings
  page for labels, members, projects and the team accent.
- Filtering exists: filter chips (assignee/label/priority/state), hideable
  columns, saved views, favorites, and `/search?q=…` which queries the database
  rather than the rendered page.
- One instance is one workspace containing teams. Projects group work inside
  one team; they are not a separate sharing boundary. Issues belong to a team
  and can also belong to a project or an issue hierarchy.
- Identity is a member credential. People can join through invitations and
  use the same identity in the browser and CLI; bots have their own identities
  and credentials. Effective bot access is bounded by its human owner and,
  for delegated workers, its creator.
- Native PocketBase rules and server hooks enforce team access. Board pages,
  search and live fragments read as their viewer. Personal sign-in, an
  operator's bootstrap credentials and the shared board credential serve
  different purposes; a session label adds no authority.
- Team data access uses Viewer/Editor grants; workspace Admin is a separate
  responsibility. The 1.8 migration preserves legacy all-team/future-team grants
  and credentials, promotes nobody automatically, and explains explicit
  conversion. See [the permissions contract](docs/permissions.md) and
  [migration procedure](docs/permissions-migration.md).
- No frontend build step. Server-rendered templates use Datastar, with
  JavaScript for navigation, project preferences and Mermaid diagrams. CSS custom
  properties define the design tokens.

## Brand Commitments

- Visual world pinned by the user: clone Linear's style — dark-first muted
  palette, compact density, state/priority iconography, left-rail + board
  layout. [user-directed]
- Accent: orange #f0883e (not Linear's indigo; teal was considered and rejected
  as played out) so lll keeps its own identity. [user-confirmed]
- Dark-only for now. [user-confirmed]
- Typeface: Inter Variable, self-hosted (web/static/fonts/InterVariable.woff2). [user-confirmed]

## Product Principles

- Reading is the product; density and scanability beat expression.
- Board and issue pages update subscribed content live. Pages without a live
  subscription, including the docs index, refresh their snapshot on reload.
- Ship templates and static assets in one binary.
- Agents are first-class users; keep markup/ids stable for morphing.
