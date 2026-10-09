# lll case 14: recover a broken config (tier 3)

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

Your saved lll configuration is broken in two ways. Plain `./lll whoami` fails.

1. Run `./lll whoami` and read the failure. Use lll's exit codes and messages
   (and `lll config` commands) to work out what is wrong. Record each exit
   code you see.
2. Repair the saved configuration so that plain `./lll whoami` works as your
   existing bot `bot-fleet-worker-NN`. conn.txt holds the right server and a
   valid token for that bot.
3. Do not create members, bots or tokens, and do not use admin credentials:
   the fix must reuse your existing identity.
4. Finish with a successful `./lll whoami`.

The artifact is your saved configuration pointing at the right server with a
working token for `bot-fleet-worker-NN`, a final successful whoami and no new
members.

## Environment

Your instance is already running. `conn.txt` in your worker directory contains
exactly three lines, and they are correct: API URL, a valid token for your
existing bot `bot-fleet-worker-NN`, team key. Never type, paste, print or quote
the token. In this case the wrapper does NOT pass conn.txt to lll. It clears
inherited LLL/XDG settings and runs the pinned binary with your own saved
configuration, under `home/config` in your worker directory, and that
configuration is broken. Repair it with lll's own commands; do not edit the
config file by hand. When a command needs the token, feed it from the file
without displaying it, for example `sed -n 2p conn.txt | ./lll ...` where the
command reads it from stdin. All CLI calls must use the wrapper: run it as
`./lll` from your worker directory. Your sandbox may refuse `export VAR=$(...)`
or `VAR=$(...) cmd` at the prompt; a tiny script that does the same is the way
around that.

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
  "answer": {"exit_codes_seen": []}
}
```

`answer.exit_codes_seen` lists the failing exit codes you met, in order.

Each failure has `command`, `error`, `expected` and boolean
`help_would_have_told_me`. Set `done` true only after reading back the exact
artifact. The controller checks server state independently of your report.
