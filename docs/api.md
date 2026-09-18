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

## Optimistic writes

`PATCH /api/collections/issues/records/{id}` honours an `If-Unmodified-Since`
header: pass the `updated` stamp your read returned, and the server answers
`412` — without applying the write — when the record has changed since. The
refusal body names the current stamp to retry with. Without the header the
PATCH behaves exactly as before. (`lll issue update --if-unchanged-since`
sends it for you.) The header applies to the `issues` collection only.

## Retried issue creation

`POST /api/collections/issues/records` accepts `Idempotency-Key: <stable-key>`
for JSON requests. Keys are scoped per team. The first request creates an
issue; matching retries return the current issue with `reused: true` and do
not apply the creation again. A changed payload returns `409` with a conflict
message. Fingerprints use canonical JSON, including origin and the enforced
member creator; object key order is irrelevant. Key/fingerprint fields are
server-owned and retain their creation values through subsequent edits.
Deleting the issue removes its key reservation. Requests without a key keep
ordinary creation behavior. Non-JSON keyed requests are explicitly refused.

Authenticate and check `GET /api/lll/issues/idempotency` for
`{"supported":true}` before relying on the header: older servers can ignore
unknown headers. `lll issue create --idempotency-key KEY` checks this before
writing and reports `Reused` for matching retries. The lll skill gives a recipe
for deriving a stable key.

## The schema

`lll api --schema` prints the collection/field reference: every collection
and field, its type, whether it is required, and the access rules a member
token answers to. It is generated from the migrations (their end state — what
the server actually enforces), not hand-typed; regenerate after schema
changes with `mise run api-schema`. The gate verifies the two agree —
`gen_api_schema.py --check` runs in e2e and fails naming what drifted, so the
reference cannot silently fall behind the schema again (LLL-435).
