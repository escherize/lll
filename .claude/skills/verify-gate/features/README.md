# Feature map

What a user can do, and the driver that proves it. Every driver here is real
and already runs inside `scripts/e2e_web.sh` - this index says which one covers
your change, so a verification run drives the path the issue describes instead
of whichever entry point is convenient.

**A proof that drives one convenient entry point is incomplete when this map
lists others.** If your change touches the board and the issue page, drive both.

| Feature | Driver | Runs as |
|---|---|---|
| [Board and realtime](board.md) | `browser_issue_stream.js` | `test_issue_stream.py` |
| [Claims](claims.md) | `browser_claims.js` | `test_board_claims.py` |
| [Search](search.md) | `browser_search.js` | inline (`search_ordering`) |
| [Issue list and sort](issues.md) | `browser_issue_sort.js`, `browser_board_pagination.js` | inline, `test_board_pagination.py` |
| [Drafts and forms](drafts.md) | `browser_settings_drafts.js`, `browser_create_failure.js`, `browser_state_failure.js` | inline |
| [Attachments](attachments.md) | `browser_attachments.js` | `test_attachments.py` |

Other drivers in the suite, without their own page because no issue has needed
one yet: `browser_assignment.js` (assigning from the issue page),
`browser_cmdk.js` (the command palette), `browser_hidden_columns.js` (hiding
board columns), `browser_settings_delete.js` (deletion from settings),
`browser_thread_layout.js` (comment thread layout).

## Adding to this map

A new user-facing feature gets a file here in the same change that ships it.
Four H2s, in this order, answered from the user's point of view:

```
## Sub-features
## How to get to it (user POV)
## Driving it with the browser suite
## Gotchas
```

Do not add a page for a feature with no driver. Either write the driver (its
own issue, stage 3 work) or say plainly in the evidence that the path was
verified by hand.
