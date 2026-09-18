# lll case 05: create an issue (tier 2)

You are one of ten fresh agents trying lll. Your controller provides your two-digit
worker number NN, absolute worker directory and lll wrapper path. Your board and
existing bot are fresh for this case; no prior-case residue. Record every call,
guess, failure and surprise. Use only the provided wrapper to operate on the
board; do not use raw HTTP, a database, the web UI, repository source or another
worker’s files. Do not start servers or change machine configuration.

Using only the controller-provided lll wrapper, create exactly one issue in team
FLEET with title `Repair flaky upload retry (worker NN)`, description
`Retry a dropped upload once and preserve the saved attachment.`, state `todo`,
priority 2, label `bug`, and project `Fleet sandbox`. Replace NN with your worker
number. Discover command forms through the CLI's help; no source or raw HTTP.

Read the complete resulting issue back and check all six fields and your bot
creator identity. If a write fails, inspect before retrying. Leave seeded issues,
labels, projects and members unchanged. Do not create a second copy or a new
project/label to satisfy lookup failures.

The independently checked artifact is exactly one worker-title issue with the
specified fields and the existing bot as creator. Write `report.json` and
`report.md` using the schema below and complete invocation/failure/guess log.
Three failures on one operation means stop and record blocked. Report success
only after read-back.

## Environment

Your instance is already running. `conn.txt` in your worker directory contains
exactly three lines: API URL, bot token, team key. Never type, paste, print or
quote the token. The controller-provided wrapper reads it without shell eval,
clears inherited LLL/XDG settings, sets HOME/config to your own directory and
runs the pinned binary there. All CLI calls must use that wrapper. Your bot is
already provisioned; no login or token creation is needed.

This harness allows environment variables scoped to child processes; older
fleet lessons about refusing HOME/source are historical, not lll failures.
If the wrapper or instance is unavailable, record a harness blocker and stop.

## Deliverable

Write `report.json` and `report.md` in your worker directory. Log every CLI call
in those reports. Never create/edit/delete/reconstruct `calls.jsonl` or any
instrumentation file: the controller keeps the authoritative audit elsewhere
and publishes it only after you return. Its absence during work is intentional.
Log each call
exactly, its exit code and first output line; redact any unexpected credential
output. For every failure, record expected behavior, full sanitized error,
whether help would have shown the correct form and whether you tried help.
Record guesses and papercuts, including calls that did more than requested.
After three failures on one operation, stop and report blocked.

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
