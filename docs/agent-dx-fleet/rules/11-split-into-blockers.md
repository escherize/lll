# lll case 11: split an issue into blockers (tier 3)

You are a fresh agent evaluating lll through its CLI. Record every
call, guess, failure and surprise. Truthful friction is more useful than a
claimed success. Your controller supplies your two-digit worker number NN,
absolute worker directory and the `lll` wrapper path when launching you.

## Task

Use only the provided lll CLI wrapper to operate on your board. Do not use raw
HTTP, `lll api`, a database, the web UI, repository source, another worker's
files or a hosted board. Write your own reports within your directory; do not
edit the supplied wrapper. Prefer its `--help` to guessing.

Read every object in full before you change it.

1. Find `Ship offline mode (worker NN)` in team FLEET and read it.
2. Create three issues, each priority urgent, titled exactly:
   - `Offline mode: cache schema (worker NN)`
   - `Offline mode: sync queue (worker NN)`
   - `Offline mode: conflict banner (worker NN)`
3. Record that the original issue cannot start until each of the three is done (the
   three block the original issue).
4. Ask lll what to work on next (its "what next" command, without taking it).
   It must now offer one of the three, not the original issue.
5. Read back the original issue and confirm its three blockers.

Use blocker links for this task; do not create parent/child links.

The artifact is three new issues blocking the original issue, and lll's next pick
being one of them. Do not claim anything; change nothing else.

## Environment

Your instance is already running. Do not open `conn.txt`: it holds your credentials, and the wrapper reads it
for you. Never type, paste, print or quote a token. The controller-provided wrapper reads it without shell eval,
clears inherited LLL/XDG settings, sets HOME/config to your own directory and
runs the pinned binary there. All CLI calls must use that wrapper: run it as
`./lll` from your worker directory. Your bot `bot-fleet-worker-NN` is already
provisioned; no login or token creation is needed.

This harness permits environment variables scoped to child processes.
If the wrapper or instance is unavailable, record a harness blocker and stop.

## Deliverable

Write `report.json` and `report.md` in your worker directory. If a file tool
refuses to write them, use a shell heredoc instead:

    cat > report.json <<'EOF'
    {"done": false}
    EOF

Complete the full JSON shape below before returning your report.

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
  "answer": {"next": "FLEET-1"}
}
```

`answer.next` is the key lll offered in step 4.

Each failure has `command`, `error`, `expected` and boolean
`help_would_have_told_me`. Set `done` true only after reading back the exact
artifact. The controller checks server state independently of your report.
