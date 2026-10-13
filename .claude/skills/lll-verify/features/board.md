# Board and realtime

## Sub-features

The board page grouped by the six states with cards in the right columns. The
app shell's rail, one template, same on every page. Changes made anywhere - the
CLI, the web board, another agent - appearing on every open board with no
reload, over one SSE stream.

## How to get to it (user POV)

Open the board login URL the scratch banner printed. The bare `/` path 303s to
its team-routed twin (`/t/SCRAT/`). Create an issue from another terminal with
`lll issue create` and watch it arrive without touching the page.

## Driving it with the browser suite

`scripts/browser_issue_stream.js`, run by `scripts/test_issue_stream.py` with
`binary api board` arguments from inside `e2e_web.sh`.

The driver opens a board page, drives a CLI-side change, and waits for the card
to appear. It is the canonical proof that a change did not break SSE.

## Gotchas

A broadcast must not clear a draft the user is mid-way through typing. That is
fragment ownership, and it is the failure this driver exists to catch - see
[datastar-fragments](../../datastar-fragments/SKILL.md) before changing
anything that patches elements.

A card appearing after a reload is not proof. The point is that it arrives
without one.
