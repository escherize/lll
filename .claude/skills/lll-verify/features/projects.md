# Projects

## Sub-features

Projects grouped by status in lifecycle order, with project counts and collapsible
headers. Rows retain alphabetical order within each nonempty group and link to
the project's filtered issue list. Empty teams retain the creation guidance.

## How to get to it (user POV)

Open Projects in the sidebar. Click a status header, or focus it and press Enter
or Space, to collapse or expand it. The choice is remembered per team in this
browser across reloads and new tabs; it is not a shared workspace setting.

## Driving it with the browser suite

`scripts/browser_project_groups.js`, run inline in `scripts/e2e_web.sh`, covers
all five statuses, counts, reload/new-tab persistence, reopening with the keyboard,
team isolation, project drilldown and raw output, unavailable/invalid storage,
empty teams, and native collapse without JavaScript. Fixtures are disposable.

## Gotchas

Only presentation state lives in localStorage, keyed by team record ID and status.
Project records, issue counts and raw output do not depend on it. Empty status
groups are omitted, and unknown server statuses stay visible after known statuses.
There is no new SSE connection; status changes appear on the next page load.

Native collapse works without JavaScript, but remembering it requires JavaScript
and available browser storage. Storage failures display a notice instead of
breaking the controls or silently pretending the preference was saved.
