# lll case 12: work across two teams (tier 3)

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

This board has two teams, FLEET and OPS. Each has a label called `bug`.

1. First, try to create an issue titled `fleet-12-NN rollout checklist`
   WITHOUT naming any team. lll must refuse because no team is configured.
   Record the exit code and message. Check that nothing was created. This
   refusal is the expected result: put it in `answer.no_team_exit` and the
   call log, not in `failures`.
2. Create `fleet-12-NN rollout checklist` in team OPS with OPS's label `bug`.
3. Create `fleet-12-NN rollout notes` in team FLEET with FLEET's label `bug`.
4. Read both back and confirm each sits in its own team with its own team's
   label.

The artifact is exactly two new issues, one per team, each labelled with its
own team's `bug`. Do not create labels, teams or saved configuration.

## Environment

Your instance is already running. Do not open `conn.txt`: it holds your credentials, and the wrapper reads it
for you. Never type, paste, print or quote a token. The controller-provided wrapper reads the URL and token from
it without shell eval, clears inherited LLL/XDG settings, sets HOME/config to
your own directory and runs the pinned binary there. In this case the wrapper
deliberately configures NO team: every command that needs one must name it.
Do not attach a directory or save a default team. All CLI calls must use the
wrapper: run it as `./lll` from your worker directory. Your bot
`bot-fleet-worker-NN` is already provisioned; no login or token creation is
needed.

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
  "answer": {"no_team_exit": 0}
}
```

`answer.no_team_exit` is the exit code lll gave in step 1 (a number).

Each failure has `command`, `error`, `expected` and boolean
`help_would_have_told_me`. Set `done` true only after reading back the exact
artifact. The controller checks server state independently of your report.
