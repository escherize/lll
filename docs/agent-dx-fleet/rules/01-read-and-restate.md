# lll case 01: read and restate (tier 1)

You are one of ten fresh agents trying lll, a CLI issue tracker. Record every
call, guess, failure and surprise. Truthful friction is more useful than a
claimed success. Your controller supplies your two-digit worker number NN,
absolute worker directory and the `lll` wrapper path when launching you.

## Task

Use only the provided lll CLI wrapper to operate on your board. Do not use raw
HTTP, a database, the web UI, repository source, another worker's files or a
hosted board. You may read the provided connection file and write your wrapper
and reports within your own directory. The supplied wrapper already connects to
your instance; prefer its `--help` to guessing.

1. Find the issue about retrying a comment after a socket reset in team FLEET.
2. Read the full issue before writing anything. There are decoy issues.
3. Add exactly one comment to that target, with this exact body, replacing NN
   with your worker number:
   `fleet-01-NN: A socket reset made the retry skip the comment; preserve one comment and report the saved result.`
4. Read back the comment and confirm its body and your author identity. Do not
   change any issue fields or comment on a decoy.

The artifact is exactly one matching comment on the target, authored by your
existing bot identity `bot-fleet-worker-NN`. If a write fails, inspect before
retrying; duplicates fail the independent check. Do not create identities,
start servers, change machine configuration or claim production issues.

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
