# Search

## Sub-features

`/search` filtering as it is typed, with results patched in and no page load.
The address bar following the query. The X clearing both the field and the
query.

## How to get to it (user POV)

Open `/search` from the rail, type, and watch results narrow without a
navigation. The URL updates as you type, so the search is shareable and the
back button works.

## Driving it with the browser suite

`scripts/browser_search.js`, run inline in `e2e_web.sh` as `search_ordering`.

## Gotchas

Result ordering is part of the contract, not incidental - the driver's name
says so. A change that returns the right set in the wrong order fails here.

Empty search has its own behavior. An issue about empty search pointing at the
wrong place has already been filed once (LLL-484).
