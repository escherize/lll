---
name: datastar-fragments
description: Use when changing lll live board updates, SSE routing, server-rendered fragment boundaries, draft preservation, or async search responses. Diagnose stale columns and lost client state; do not load for unrelated HTML or static CSS edits.
---

# Datastar fragment ownership

This project vendors Datastar 1.0.3. The routing and ownership rules below were
checked against the current implementation and browser regressions on
2026-09-12. Read the affected handler and template together before moving a
fragment boundary.

## Route events after subscription

The board's PocketBase subscription in
[run_server](../../../src/commands/serve.lis) receives unfiltered issue events.
Do not state-filter it to the visible columns: an update leaving a PB filter
may emit no event to that subscription, leaving the old column stale. This
server hosts multiple teams; scope delivery in the
[bridge and hub](../../../src/commands/serve_sse.lis), not by turning the shared
source subscription into the boot team's or one column's view.

A board connection is scoped by team and ordering; an issue connection is
scoped by key. Board membership/order changes render the board from a fresh
read. Issue streams obtain a fresh initial snapshot, and the bridge serializes
current-state reads so a queued old event record does not overwrite it.
Description revisions are per connection and advance only after queue delivery;
a global last-description value cannot represent what slow or new clients saw.

## Give each fragment a response owner

For normal successful issue edits, the action writes persisted state and the
shared broadcast refreshes its issue/board representation. Avoid also returning
a stale full detail view from that POST: it competes with the live stream.

This is **not** a rule that POST responses contain no markup. Current examples
include flash messages, clearing a successful attachment form, settings views,
and restoring authoritative property values after a rejected edit. Search
responses own their results and title. Preserve those distinctions:

- [flashing/actions](../../../src/commands/serve_actions.lis) own alerts and
  explicitly returned action fragments/signals.
- [property recovery](../../../src/commands/serve_property_recovery.lis) replaces
  the property controls after failure; it leaves title/comment drafts alone.
- [attachment actions](../../../src/commands/serve_attachments.lis) clear only a
  successful upload form. Rejected uploads preserve the selected file.
- [search](../../../src/commands/serve_search.lis) owns search-result fragments;
  the [search input](../../../web/templates/search.html) specifies request
  cancellation for changing queries. Keep the response-order browser test when
  altering this flow.

Use shared `patch_event`/`signals_event` helpers. Stable element IDs name morph
boundaries; an empty result still needs a root so a later patch can add or clear
its contents. Use the explicit replacement behavior where controls must lose
rejected local values rather than retain them through a morph.

## Preserve client-owned work

Small signals hold local interaction state such as an open dialog, search text
or title draft. Keep their owner outside the subtree replaced by live updates,
as in [issue.html](../../../web/templates/issue.html). Comment and upload forms
also have independent boundaries. A title/state update must not clear their
unfinished work.

The description has its own `#issue-description` boundary. Metadata-only
updates leave it untouched, preserving rendered Mermaid SVG and other local
DOM state. See [the stream browser check](../../../scripts/browser_issue_stream.js).
The emoji catalogue and related findings are intentionally page-only; do not
reintroduce them into every metadata event by expanding the shared view model.

For a stable wrapper around a form, prefer a neutral element when the form has
an input named `id`: DOM named-property access can shadow `form.id` and break
identity-based morphing. The settings draft regression is in
[browser_settings_drafts.js](../../../scripts/browser_settings_drafts.js).

Render collections on the server using the existing templates. JavaScript
expressions and loops are possible; “Datastar forbids client loops” is not the
reason for this design. Likewise, favorites are persisted because they are
workspace-shared domain state—not because localStorage is technically
unavailable. Signals or browser storage would not become their authority.

## Verify the transition

Test the change through a second client or CLI while the first page has an
unfinished edit. Wait for the expected value or event, not arbitrary prior
markup or a fixed sleep. Include the applicable rejected action, reconnect,
empty/deleted result, and keyboard path. Inspect the page when layout changes.

The relevant existing suites are [web e2e](../../../scripts/e2e_web.sh),
[issue streams](../../../scripts/test_issue_stream.py), and the browser files
linked above. Use the repository's isolated scratch workflow and tracking gate
from [the lll skill](../lll/SKILL.md). These are project ownership rules, not
universal restrictions on Datastar applications.
