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

`lll` is a Linear-style issue tracker over a self-hosted PocketBase: teams,
ENG-123 identifiers, states, priorities, projects, labels, comments. The CLI is
the primary interface; the web board is a live read-and-light-write surface.
Success: state of work legible in seconds, updates visible in realtime without
reload.

## Positioning

Linear's model without Linear's SaaS: self-hosted, ONE binary with PocketBase
compiled in and served in-process, agent-friendly (`--json`, NDJSON watch
streams). Long-term it replaces Backlog.md-style file trackers for multi-agent
development.

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
- The v1.7 baseline has one read/write mode across each member's teams. The
  LLL-793 candidate adds per-team Viewer/Editor grants and a separate workspace
  Admin role with an access-preserving migration; this does not assert a
  production deployment. See [the permissions contract](docs/permissions.md)
  and [migration procedure](docs/permissions-migration.md).
- No build step, no JS beyond Datastar, CSS custom properties for tokens. [user-confirmed]

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
- Everything the CLI can see, the board shows live; no stale views.
- One binary, no pipelines: templates and assets are embedded in it.
- Agents are first-class users; keep markup/ids stable for morphing.
