# lll case 17: concurrent description edits (tier 4)

You are one of ten fresh agents trying lll, a CLI issue tracker, working in
pairs. Record every call, guess, failure and surprise. Truthful friction is
more useful than a claimed success. Your controller supplies your two-digit
worker number NN, your partner's number PP, your absolute worker directory and
the `lll` wrapper path when launching you. You and your partner share one
board; each of you has your own bot and your own wrapper.

Your role comes from your worker number:

| NN | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 |
|----|----|----|----|----|----|----|----|----|----|----|
| role | A | B | A | B | A | B | A | B | A | B |
Do not change your mind about your role.

## Task

Use only the provided lll CLI wrapper to operate on your board. Do not use raw
HTTP, `lll api`, a database, the web UI, repository source, another worker's
files or a hosted board. Write your own reports within your directory; do not
edit the supplied wrapper. Prefer its `--help` to guessing.

Read every object in full before you change it.

You and your partner each add one line to the same issue's description at the
same time. Shared issue: `Shared release notes (workers AA and BB)`.

Both roles:
1. Read the issue's description.
2. Without waiting for your partner, append exactly one line to the end of
   the description: role A appends
   `fleet-17-NN: role A checked the upload path.` and role B appends
   `fleet-17-NN: role B checked the upload path.`
3. Do not replace the description: your partner may be writing at the same
   moment, and a replace can erase their line. If lll refuses because the
   issue changed, read it again and retry.
   If you appended a wrong line, fix only that line with
   `--description-replace 'OLD=NEW'`, which swaps one substring.
4. Read back until both lines are present (bounded: at most 10 minutes,
   every 5 seconds). Report whether your partner's line arrived.

Your role is the one the table gives your number. Do not change your
mind.

The artifact is a description with the original first line and both
appended lines, each exactly once. Touch nothing else.

Look your number up in the table above; 09 is role A.
Do not change your mind about your role, even if your partner seems slow.

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
