# Parallel DX review

Measure how lll meets a stranger, by giving N agents N sealed environments and
one task, then aggregating what they hit.

An author cannot review their own tool's onboarding, because they cannot forget
it. This harness buys that forgetting: every agent gets a server nobody else
touches, an empty HOME, a fresh git repository, and no source access. What they
reach for first is the measurement.

## Run it

```sh
scripts/dx-review.sh -n 8 --agent-cmd 'your-agent --prompt-file {brief}'
```

Placeholders in `--agent-cmd`, substituted per agent:

| Token | Value |
|---|---|
| `{brief}` | that agent's task file |
| `{dir}` | that agent's environment root |
| `{report}` | the JSON path that agent must write |
| `{n}` | agent number |

Without `--agent-cmd` the script provisions everything, prints a manifest and
stops, so any runtime can drive the briefs. Aggregate afterwards:

```sh
scripts/dx-review.sh --root /tmp/lll-dx.XXXX --report-only
```

Some agent runtimes reap background processes when a tool call exits. In those
runtimes, keep the harness running while external reviewers work:

```sh
scripts/dx-review.sh -n 6 --agent-cmd 'while [ ! -f "{report}" ]; do sleep 1; done'
```

Wait for `running 6 agents in parallel`, then give fresh reviewers the printed
run directory's `agent-N/BRIEF.md` files. The placeholder commands keep the
servers supervised until every report exists. Reviewers should write reports
to a temporary file and rename them into place when complete. If a reviewer
cannot finish, stop the harness; do not leave it waiting indefinitely. Interrupt
or terminate it to stop its reviewers and servers. Preserve the run directory.

Other flags: `-n` agent count (default 6), `--task FILE` to replace the task,
`--keep` to leave the servers up, `--root DIR` to choose where it all lands.

Exit code is 0 only when every agent completed every step.
Missing or malformed reports, duplicate step IDs, and reviewer process failures
produce a nonzero exit. A new run requires a new or empty directory; existing
transcripts and databases are never overwritten.

## Use a weaker model than you think you need

The strongest models paper over bad design. They guess the right flag, infer
the missing step, and report success, so the tool looks better than it is. Run
the review on a cheaper, less capable model.

Evidence from the runs this harness came out of: fifteen strong-model agents
found the messages good. One weak-model agent, taking a clumsier route, walked
into three real defects nobody else reached, including one that created a
member shadowing the server's own administrator.

## Why each environment is sealed

Every constraint below was earned by a run that went wrong without it.

**One server per agent.** Agents create teams, members and issues. On a shared
server one agent's setup silently changes the next agent's starting conditions,
and the results stop being comparable.

**A fresh `git init`, never a worktree of this repo.** The branch verbs
(`git switch`, branch-inferred ids, `issue pr`) need a real repository, so a
plain directory skips a large part of the surface. A worktree of this checkout
is the wrong repository: it inherits the committed `.lll.toml`, which starts
every agent pre-attached and pointed at the real server, and it writes their
branches into these refs.

**The server is booted as `deployer`, not as the agent.** `lll up` seeds a
member from `$USER` on first boot. Boot as the agent and it arrives already
holding the account that onboarding exists to obtain, which deletes the hardest
part of the test.

**An empty `HOME` per agent.** Config layers. One stray `~/.config/lll/lll.toml`
and the agent is already logged in.

**No source access.** State it in the brief. An agent that reads the code stops
being a stranger and starts being a second author.

## What the task covers

Fourteen ordered steps, each depending on the last, so the step an agent stops
at names the surface that failed: authenticate, attach a repo, create a project
and labels, create issues with priority and label and project, list them, start
one without changing Git, obtain a branch name and explicitly create it with
Git, use the branch to infer the issue for a view and a
comment, assign, change state, close, search, add a colleague, print the board
URL, and emit machine-readable output.

Replace it with `--task FILE` when reviewing a different surface. Keep the
ordering property: independent steps make a failure report much harder to read.

## Reading the output

Read in this order.

1. **First command.** Every agent's opening move is what the design has to
   answer. If most of them start somewhere your error messages do not cover,
   that is the finding, whatever else the run says.
2. **Steps that failed, by count.** One agent failing a step is a story; five
   is a defect.
3. **Messages that misled.** Higher value than the failures, because a message
   that sends someone somewhere useless costs every future user.
4. **Wasted commands.** The blunt number. Track the median across runs.

Each reviewer records every invocation in `transcript.jsonl` using `command`,
`exit_code`, and `output`. Count all invocations, including successful help,
in `total_commands`; count nonzero exits in `wasted_commands`. Mark sandbox-only
denials with `infrastructure: true` and exclude those entries from both totals.
If a server remains unavailable after the permitted retry, stop the run and
repair infrastructure before starting fresh. Do not fold prerequisite failures
from an outage into product friction or rewrite the original transcript.

Reports must omit credentials. Exact colleague login commands belong in a
separate local artifact. Raw transcripts can contain credentials and should
remain in the private run directory.

The standard task and aggregator use exactly 14 numbered steps. A custom task
must keep that numbering for its reports to validate.

A finding reported by one agent is a lead. A finding reported by most of them
is a bug, and the count belongs in the commit message that fixes it.

## Cost

Each server is a full lll process, about 50 MB resident, so memory sets the
ceiling rather than CPU. Fifty ran comfortably on a 32 GB machine. Agent
concurrency is usually the real limit; the script starts all of them at once
and waits.
