# lll case 18: consume a partner's live changes (tier 4)

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

Role A watches the board live; role B makes changes A must see. Shared
issue: `Watch handshake (workers AA and BB)`, where AA is role A's number
and BB is role B's (e.g. `workers 07 and 08`).

Role A:
NN and PP are always TWO digits, zero-padded: worker 9 is `09`, so A's
comment is `fleet-18-09: watching`, never `fleet-18-9`. If a bounded wait
times out, stop and report blocked (role A still stops its stream first, step
4). This applies to BOTH roles.

1. Start lll's live event stream for team FLEET in machine-readable form in
   the background, stdout to `fleet-18-NN-watch.jsonl` and stderr to
   `fleet-18-NN-watch.err` in your directory.
2. Wait until the stream says it is ready (on stderr), then add exactly one
   comment to the shared issue: `fleet-18-NN: watching`.
3. Wait (bounded: at most 15 minutes, longer than B's wait) until B's comment starting
   `fleet-18-PP: done` appears on the shared issue, then a few seconds more.
   While waiting, check the stream's PID is still alive (`kill -0 PID`). If it
   died, record a failure and set `done` false.
4. Stop the stream by its own PID (never `pkill`) and confirm the process is
   gone.
5. From your log, list the keys of issues B created or changed. If your log
   holds no create and update for B's key, set `done` false and say so.

Role B:
1. Wait (bounded: at most 10 minutes, every 5 seconds) until A's comment
   `fleet-18-PP: watching` appears on the shared issue.
2. Create one issue titled `fleet-18-NN live event` with priority medium,
   then change its priority to high.
3. Add exactly one comment to the shared issue: `fleet-18-NN: done KEY`,
   where KEY is the issue you created.

Your role is the one the table gives your number. Do not change your
mind.

The artifacts are B's one issue (priority high), the two comments and A's
log holding the create and update events for B's issue.

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
  "report": "",
  "answer": {"partner_keys": []}
}
```

Role A: `answer.partner_keys` lists the keys you saw in your log. Role B may omit `answer`.

Each failure has `command`, `error`, `expected` and boolean
`help_would_have_told_me`. Set `done` true only after reading back the exact
artifact. The controller checks server state independently of your report.
