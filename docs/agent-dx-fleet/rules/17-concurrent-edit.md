# lll case 17: concurrent description edits (tier 4)

You are a fresh agent evaluating lll through its CLI, working in
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
same time. Shared issue: `Shared release notes (workers AA and BB)`, where AA is role A's
number and BB is role B's (e.g. `workers 07 and 08`).

Both roles:
1. Read the issue's description.
2. Run `./fleet-ready append` after reading. It waits for your partner to
   finish reading too (at most ten minutes), so neither writer starts alone.
   Then append exactly one line to the end of the description: role A appends
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

## Guarded replacement variant

Repeat on `Guarded release notes (workers AA and BB)`, with the same two lines:

1. Read the full issue as JSON and keep its `updated` stamp and description.
2. Run `./fleet-ready guarded` after reading. Both roles must cross this
   separate barrier before the first replacement.
3. Replace the description with the text you read plus your one line, using
   `--if-unchanged-since STAMP` from that read. Every replacement in this
   variant must include its read's stamp. Do not use append in this variant.
4. One initial write should be refused because both agents read the same
   version. On exit 4, read the issue again and retry with the new description
   and stamp, preserving your partner's line. Do not repeat the barrier.
   Record this expected stale-write refusal separately from tool friction.
5. Read back until both lines are present, with the same bounded wait above.

The artifacts are two descriptions, each with the original first line and
both worker lines exactly once. Each must contain exactly three lines, with
no extra blank line or terminal newline character. The guarded issue must also have an audited
stale-write refusal and successful guarded updates by both roles. Touch nothing
else. A missing partner is a harness blocker, not an lll failure. The barriers
force overlapping read/write intentions; they do not force an internal HTTP
transaction interleaving.

Look your number up in the table above; 09 is role A.
Do not change your mind about your role, even if your partner seems slow.

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
  "report": ""
}
```

Each failure has `command`, `error`, `expected` and boolean
`help_would_have_told_me`. Set `done` true only after reading back the exact
artifact. The controller checks server state independently of your report.
