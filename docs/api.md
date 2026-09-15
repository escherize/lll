# The lll board API

The board's data API is PocketBase REST, served at the board's address — the
same url the CLI is configured against (`LLL_URL`, or `url` in
`~/.config/lll/lll.toml`; `lll config --list` shows which value won and where
it came from). There is no separate API host to point at.

## Auth

Requests authenticate with a member token as a Bearer header:

    Authorization: Bearer <token>

`lll login` stores your token from an interactive login; `lll token create`
mints a long-lived one for an agent (superuser only). Both live wherever the
CLI reads them, and every collection rule is written against
`@request.auth.id` — an authenticated member — so scripts should send a token
too.

## The raw passthrough

`lll api METHOD PATH [--body TEXT]` sends the request for you: it rides the
configured url and token, prints the response body to stdout and the status
line to stderr, and shows non-200 responses as-is rather than as command
errors:

    lll api GET "/api/collections/issues/records?filter=(state='todo')"
    lll api POST /api/collections/comments/records --body '{"issue":"...","body":"hi"}'

## The schema

`lll api --schema` prints the collection/field reference: every collection
and field, its type, whether it is required, and the access rules a member
token answers to. It is generated from the migrations (their end state — what
the server actually enforces), not hand-typed; regenerate after schema
changes with `mise run api-schema`.
