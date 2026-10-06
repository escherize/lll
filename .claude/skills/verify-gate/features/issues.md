# Issue list and sort

## Sub-features

The zero-JavaScript `/issues` table: server-side sort and filter through query
params, an honest row count, and bad params degrading to the flash strip rather
than erroring. Per-column server-side ordering on the board (`?order=`), with
order-scoped SSE morphs and positional drops disabled off-manual. Pagination.

## How to get to it (user POV)

Open `/issues` from the rail. Click a column heading to sort; the page reloads
with a query param and no JavaScript is involved. On the board, the ordering
picker changes `?order=`.

## Driving it with the browser suite

`scripts/browser_issue_sort.js` (inline, as `title_sort`) and
`scripts/browser_board_pagination.js` (run by `test_board_pagination.py`).

## Gotchas

`/issues` is the no-JavaScript surface. A change that makes it depend on a
client-side handler breaks the thing it exists to provide, and the driver will
not necessarily notice - check by hand with JavaScript disabled if you touched
that table.

The row count must be honest. A count that reports the page rather than the
result set is the bug this section pins.
