# lll case 19: invite a scoped colleague (tier 4)

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

This board has team FLEET and another team your colleague must never see.

1. Invite a colleague named `colleague-NN` with email
   `colleague-NN@example.com`, limited to team FLEET only, using lll's
   member invite. Save its output to `invite-NN.txt` in your directory; it
   holds a temporary password, so never print it.
2. Log in as the colleague with that password, keeping the colleague's login
   in its own config home inside your directory (for example
   `LLL_CONFIG_HOME=$PWD/colleague`), so your own identity is untouched.
3. As the colleague, list the teams. Confirm only FLEET appears.
4. As yourself, confirm the colleague exists and is limited to FLEET.

Exact forms, so the password is never displayed, typed or copied:

- Invite once, stdout only: `./lll member invite colleague-NN --email
  colleague-NN@example.com --team FLEET > invite-NN.txt`. Run it exactly
  once; a second run cannot recover the password.
- Log in by piping the password straight from that file, in a tiny script:
  `sed -n 's/^ *temporary password: //p' invite-NN.txt | LLL_CONFIG_HOME="$PWD/colleague" ./lll login --url "$(sed -n 's/.*lll login --url \([^ ]*\).*/\1/p' invite-NN.txt)" --email colleague-NN@example.com`
  (the wrapper sets LLL_URL, and lll sends credentials only to a server you
  name, so the login names the invite's url)
- Never copy the password into a script, a command or your report.

The artifact is one new member limited to FLEET whose own team list shows
only FLEET. Create nothing else.

## Environment

Your instance is already running. Do not open `conn.txt`: it holds your credentials, and the wrapper reads it
for you. Never type, paste, print or quote a token, this one or any other. The controller-provided wrapper reads
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
  "report": "",
  "answer": {"colleague_teams": []}
}
```

`answer.colleague_teams` lists the team keys the colleague saw in step 3.

Each failure has `command`, `error`, `expected` and boolean
`help_would_have_told_me`. Set `done` true only after reading back the exact
artifact. The controller checks server state independently of your report.
