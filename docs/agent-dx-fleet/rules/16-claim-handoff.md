# lll case 16: claim handoff (tier 4)

You are one of ten fresh agents trying lll, a CLI issue tracker, working in
pairs. Record every call, guess, failure and surprise. Truthful friction is
more useful than a claimed success. Your controller supplies your two-digit
worker number NN, your partner's number PP, your absolute worker directory and
the `lll` wrapper path when launching you. You and your partner share one
board; each of you has your own bot and your own wrapper.

Your role comes from your worker number. An odd NN is role A. An even NN is
role B. Do not change your mind about your role.

## Task

Use only the provided lll CLI wrapper to operate on your board. Do not use raw
HTTP, `lll api`, a database, the web UI, repository source, another worker's
files or a hosted board. Write your own reports within your directory; do not
edit the supplied wrapper. Prefer its `--help` to guessing.

Read every object in full before you change it.

You and your partner hand one issue from A to B. Shared issue:
`Migrate the upload worker (workers AA and BB)`, where AA is role A's number
and BB is role B's.

Role A (odd NN):
1. Read the issue, then claim it.
2. Add exactly one comment:
   `fleet-16-NN: handing off to bot-fleet-worker-PP; the queue drain is next.`
3. Release your claim. Read back: no claim, your comment present.
   Then you are done: set `done` true after this readback. Do not wait for B.

Role B (even NN):
1. Wait until A's comment is on the issue AND the issue has no claim. Poll
   with `issue view` at most every 5 seconds, for at most 10 minutes, or use
   a bounded watch. Do not take the issue early, and never force it.
2. Claim it.
3. Add exactly one comment: `fleet-16-NN: picked up from bot-fleet-worker-PP.`
4. Read back: you hold the claim and are the assignee; both comments present.

Your role is decided by your number: odd is A, even is B. Do not change your
mind.

The artifact is the issue held by and assigned to B, with A's comment then
B's. Touch nothing else.

Your role is decided by your worker number: odd is role A, even is role B.
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
