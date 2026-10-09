# lll case 15: hand off bot credentials (tier 3)

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

You act as a person, `fleet-worker-NN` (not a bot). You will create a bot for
a helper agent, hand its credentials off as an environment file, rotate them
and prove the old ones are dead.

1. Create a bot named `bot-helper-NN`, saving ONLY its environment exports
   (lll can print just those) to `helper-NN.env` in your directory. Never
   print the file.
2. Using that file (as LLL_TOKEN for one command), run `whoami` as the
   helper and confirm the identity.
3. Rotate the helper's token, saving the new exports to
   `helper-NN-rotated.env`.
4. Prove the old token fails: run `whoami` with `helper-NN.env` again and
   record the exit code (it should mean "not authenticated").
5. Prove the new one works: run `whoami` with `helper-NN-rotated.env`.

The artifacts are one new bot owned by you, both env files (the controller
redacts them after judging), a refused call with the old token and a
successful whoami as the helper with the new one. Create nothing else.

## Environment

Your instance is already running. `conn.txt` in your worker directory contains
exactly three lines: API URL, your token, team key. Never type, paste, print or
quote a token, this one or any other. The controller-provided wrapper reads
conn.txt without shell eval, clears inherited LLL/XDG settings, sets
HOME/config to your own directory and runs the pinned binary there. All CLI
calls must use that wrapper: run it as `./lll` from your worker directory.

In this case you also act as a second identity. The wrapper honours two
settings you give it for one command, and always uses conn.txt's server:
`LLL_TOKEN` (a token, read from a file you saved, never typed) and
`LLL_CONFIG_HOME` (a directory inside your worker directory, holding that
identity's own saved login). Your sandbox may refuse `export VAR=$(...)` or
`VAR=$(...) cmd` at the prompt; a tiny script that sets the variable and runs
`./lll` is the way around that. Files that hold tokens or passwords stay in
your directory; never print them.

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
