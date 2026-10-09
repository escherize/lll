# lll case 20: recover from a wrong command (tier 4)

You are one of ten fresh agents trying lll, a CLI issue tracker. Record every
call, guess, failure and surprise. Truthful friction is more useful than a
claimed success. Your controller supplies your two-digit worker number NN,
absolute worker directory and the `lll` wrapper path when launching you.

## Task

Use only the provided lll CLI wrapper to operate on your board. Do not use raw
HTTP, `lll api`, a database, the web UI, repository source, another worker's
files or a hosted board. Write your own reports within your directory; do not
edit the supplied wrapper.

Read every object in full before you change it.

The upload retry flake is supposedly fixed, but someone wants a second pair of
eyes on it. Get that issue in front of reviewers, and leave a short note on it
that starts with `fleet-20-NN:`.

That is the whole brief. This case measures how lll helps you RECOVER, so:

- Your FIRST attempt at each of the two steps (sending it to review, and
  leaving the note) must be the command you would naturally guess, typed
  WITHOUT reading any `--help` first. Finding the issue may use any read
  command.
- If lll refuses, read its error and recover using only what lll prints
  (its errors, and `--help` from then on).
- If your first guess happens to work, that is fine: record it as a success.

When you are done, rate the least helpful error message you met: the exact
command, the error, a score from 1 (useless) to 5 (told me the fix), and why.
If no call failed, set `error_rating` to null; do not rate help text instead.

The artifact is that issue in the state that means "under review" and your
one note on it. Touch nothing else.

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
  "report": "",
  "error_rating": {"command": "", "error": "", "rating": 0, "why": ""}
}
```

`error_rating` is required in this case: the least helpful error you met. If every call worked first time, rate the least helpful message you read and say so.

Each failure has `command`, `error`, `expected` and boolean
`help_would_have_told_me`. Set `done` true only after reading back the exact
artifact. The controller checks server state independently of your report.
