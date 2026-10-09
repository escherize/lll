# lll case 02: export a precise subset (tier 1)

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

This is a read-only case: change nothing on the board.

1. In team FLEET, find every OPEN issue that carries the label `bug` AND
   belongs to the project `Checkout`. Open means state backlog, todo,
   in-progress or in-review; done and cancelled are not open. There are decoys:
   closed bugs, a non-bug in Checkout and a bug outside Checkout.
2. Export exactly that subset as JSON with the CLI's machine-readable output
   and save the CLI's stdout, unedited, to `fleet-02-NN.json` in your
   directory.
3. Read the file back and count the issues in it.

The artifact is `fleet-02-NN.json` holding exactly the matching issues, and
your report's `answer` naming their keys and count. Any write to the board
fails the case.

## Environment

Your instance is already running. `conn.txt` in your worker directory contains
exactly three lines: API URL, bot token, team key. Never type, paste, print or
quote the token. The controller-provided wrapper reads it without shell eval,
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
  "answer": {"keys": ["FLEET-1"], "count": 1}
}
```

`answer.keys` lists the matching issue keys (any order); `answer.count` is how many.

Each failure has `command`, `error`, `expected` and boolean
`help_would_have_told_me`. Set `done` true only after reading back the exact
artifact. The controller checks server state independently of your report.
