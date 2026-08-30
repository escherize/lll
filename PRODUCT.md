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

Linear's model without Linear's SaaS: local-first, two binaries, agent-friendly
(`--json`, NDJSON watch streams). Long-term it replaces Backlog.md-style
file trackers for multi-agent development.

## Operating Context

Changes arrive continuously from CLI, agents, and other browsers over one SSE
stream; the board must absorb live morphs (cards moving columns) without
disorienting the viewer. Server-rendered Go templates + Datastar; templates and
static assets are embedded in the binary.

## Capabilities and Constraints

- Fixed six-state workflow: backlog, todo, in-progress, in-review, done, cancelled.
- Priorities 0-4 (none/urgent/high/medium/low). Assignees, projects, labels, comments exist.
- Web actions today: create issue (title+state), change state, comment. No auth, no filtering UI yet.
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
- Two binaries, no pipelines: assets ship as plain files.
- Agents are first-class users; keep markup/ids stable for morphing.
