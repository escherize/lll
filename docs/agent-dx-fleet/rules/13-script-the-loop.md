# lll case 13: script the loop (tier 3)

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

Team FLEET has issues labelled `sweep`. Some are ready to work; one is blocked
and must stay open.

1. Write a shell script `fleet-13-NN.sh` in your directory. It takes the
   label as its only argument (`$1`, no default). It must loop: ask lll for
   the next ready issue with that label and take it in the same call, close
   it, and repeat. It must branch on lll's EXIT CODES, not on message text: on
   "nothing to do" it stops and exits 0; on any other failure it exits with
   that code. Read `./lll issue next --help` before writing it, and capture
   the key from stdout only (no `2>&1`).
2. The script calls the wrapper (`./lll`, or its absolute path). It must not
   contain a token or read conn.txt; the wrapper supplies the connection.
3. Read the script back, then rehearse: `./fleet-13-NN.sh practice` (three
   disposable issues). Fix the script and rehearse again until that run exits
   0 with every practice issue done. Read back with `./lll issue list --label
   practice`: every practice issue done and unclaimed. If a rehearsal strands a
   claim, release it with `./lll issue release KEY` (practice only; the only
   manual action allowed on a practice issue - never close one by hand), then
   rehearse again: a release is not a clean run. Only after a rehearsal exits
   0 and the read-back shows every practice issue done, run `./fleet-13-NN.sh sweep`,
   exactly once. Never claim, close, release, reopen or update a `sweep`
   issue by hand. If the sweep run goes wrong, stop and report; do not repair
   the board by hand.
4. Confirm with lll, without taking anything: every ready `sweep` issue is
   done and unclaimed (its claim is empty; the assignee that close leaves
   behind is expected, so do not clear it), and the blocked one is untouched.
   Take "nothing to do" from the sweep run's own output and exit status; if
   you check again, use `./lll issue next --label sweep` with no `--claim`.

The artifacts are the script file and the board: ready sweep issues done, no
claims, nothing else changed.

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
