# lll case 08: record a finding (tier 2)

You are one of ten fresh agents trying lll, a CLI issue tracker. Record every
call, guess, failure and surprise. Truthful friction is more useful than a
claimed success. Your controller supplies your two-digit worker number NN,
absolute worker directory and the `lll` wrapper path when launching you.

## Task

Use only the provided lll CLI wrapper to operate on your board. Do not use raw
HTTP, `lll api`, a database, the web UI, repository source, another worker's
files or a hosted board. Write your own reports within your directory; do not
edit the supplied wrapper. Prefer its `--help` to guessing.

Read every object in full before you change it.

1. Record one finding in team FLEET with:
   - slug `fleet-08-NN-upload-lock`
   - title `Upload retry holds the cache lock (worker NN)`
   - area `storage`
   - paths `src/upload` and `src/retry`
   - body `The retry path takes the cache lock before the upload finishes.`
   - confidence `suspected` (you are not sure yet).
2. Read it back and check every field.
3. You have now verified it: mark the finding confirmed with lll.
4. Read it back again and confirm its confidence is confirmed and nothing
   else changed.

The artifact is exactly one finding with those fields, confidence confirmed,
authored by your bot. Do not create a second copy.

## Environment

Your instance is already running. Do not open `conn.txt`: it holds your credentials, and the wrapper reads it
for you. Never type, paste, print or quote a token. The controller-provided wrapper reads it without shell eval,
clears inherited LLL/XDG settings, sets HOME/config to your own directory and
runs the pinned binary there. All CLI calls must use that wrapper: run it as
`./lll` from your worker directory. Your bot `bot-fleet-worker-NN` is already
provisioned; no login or token creation is needed.

This harness allows environment variables scoped to child processes; older
fleet lessons about refusing HOME/source are historical, not lll failures.
If the wrapper or instance is unavailable, record a harness blocker and stop.

## Deliverable

Write `report.json` and `report.md` in your worker directory. If a file tool
refuses to write them, use a shell heredoc instead:

    cat > report.json <<'EOF'
    {"done": false, ...}
    EOF

Log every CLI call in those reports. Never create/edit/delete/reconstruct
`calls.jsonl` or any instrumentation file: the controller keeps the
authoritative audit elsewhere and publishes it only after you return. Its
absence during work is intentional. Log each call exactly, its exit code and
first output line; redact any unexpected credential output. For every failure,
record expected behavior, full sanitized error, whether help would have shown
the correct form and whether you tried help. Record guesses and papercuts,
including calls that did more than requested. After three failures on one
operation, stop and report blocked.

Use this JSON shape:

```json
{
  "done": false,
  "invocations": 0,
  "failures": [],
  "guesses": [],
  "papercuts": [],
  "api_thoughts": "",
  "report": ""
}
```

Each failure has `command`, `error`, `expected` and boolean
`help_would_have_told_me`. Set `done` true only after reading back the exact
artifact. The controller checks server state independently of your report.
