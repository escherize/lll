# Running the approved lll DX cases

## Choose the run scope

For a release, follow `docs/release-checklist.md`: five fresh workers across
the cases touched by that release, with at most three active workers. Record
the chosen cases and worker count on the release issue before provisioning.
Pair cases need even counts; the total can mix independent and paired cases.
The older ten-worker case01/case06 runs in `plan.md` are a research baseline,
not the size or case restriction for every release. Explicit user scope wins.

Use fresh agents, not follow-up tasks that have already learned the CLI.
Use the configured cheap worker model when available; otherwise record an
available equivalent before launching, never claim the unavailable model ran.
A new parent-model reviewer reads every raw report, call audit and REST result.
Keep release evidence on its release issue; historical research evidence
belongs to its original issue.

Build the intended source revision and record the commit and binary SHA256.
Run `python3 scripts/test_agent_dx_fleet.py` and `mise run fleet-test` before
provisioning: the second runs every case's seed and judge against scratch
boards with a scripted correct worker (must pass) and a scripted wrong worker
(must fail for the named reason). Start
`scripts/agent_dx_fleet.py` with `--root` pointing to an absent temporary
path, `--binary` pointing to the built binary, and its exact `--commit` and
`--sha256`. Keep this process alive; it owns all children. It copies the
binary and wrapper/startup code and records their fingerprints before accepting
JSON lines on stdin. Worktree edits cannot change code beneath live workers.

Send `{"action":"provision","case":"01","run":1}` (`"workers"` defaults to 10).
Launch workers only after the controller reports them all ready. Give each
worker only its case rules (`docs/agent-dx-fleet/rules/NN-<slug>.md`, named in
the provision reply), number, directory and `lll` wrapper path. In the pair
cases (16, 17, 18) workers 01+02, 03+04 and so on share one board, each with
its own bot and wrapper; also give each worker its partner's number. The odd
worker is role A, the even worker role B. Workers invoke that wrapper from
their own directory. It supplies the isolated environment and audits exact
arguments, exit status and redacted output under the controller, outside worker
directories. Workers never create/edit `calls.jsonl`; their deliverables are
report.json and report.md. Never print `conn.txt` or paste a
token into a prompt. The wrapper permits the CLI only; task rules prohibit
source, raw HTTP, the UI, identity changes and server/config operations.

After every worker has written report.json and report.md, send
`{"action":"judge"}`. It validates and publishes the authoritative audits into
worker evidence directories, preserving any worker-supplied file separately.
Missing/malformed instrumentation means unavailable counts and a fresh rerun,
not reconstruction from worker claims. The controller snapshots every member-writable
collection, invites and issue counters over REST, compares every seeded record, counts every new record
and verifies the exact expected author/creator, fields and relations. Any
change the case does not name fails it. Read-only cases also check the
`answer` object in report.json; case 13 checks the worker's script, case 14 its
saved config, case 15 its env files (then redacts them), case 18 role A's
watch log. Pair cases are judged per board. In case 20 a missing
`error_rating` is reported but does not fail the artifact.
Durable snapshots redact webhook secrets. A fresh reviewer writes review.json,
review.md and summaries.json. Assemble run.json with summaries, review,
checker results and fingerprint, then run the shared tally.py and save stdout.
The owner uses the audits and ground truth, not worker done claims.

Pass requires every provisioned artifact and fewer than two workers with a tool-owned
failed invocation. Repeated tool failure classes get their own claimed issue
and verified fix. Then stop the old case and rerun the same case with fresh
instances and agents before advancing. Record harness/task-design corrections
separately. A new binary requires a new controller and fresh root; never replace
the binary beneath live workers. Repeat the chosen release cases on the final build if the binary changes.

Send `{"action":"stop"}` after review, then `{"action":"exit"}` when changing
builds or finishing. Stop waits/reaps owned children, verifies every owned
listener is gone, removes connections and private controller data. Scan
sanitized evidence for credentials, remove disposable worker HOME/cache, and
retain only reports, audits, snapshots, reviews, tally, fingerprints and cleanup
receipts. Attach the evidence bundle and closing table to the run’s tracking issue.

## Wrapper modes

Most cases use the default wrapper: URL, token and team from conn.txt. Four
cases differ. Case 12 gets no team, so a command without `--team` must be
refused. Case 14 gets nothing from conn.txt: the CLI reads a seeded, broken
config (wrong URL, expired token) in the worker's HOME, which the worker
repairs. Cases 15 and 19 honour a worker-set `LLL_TOKEN` or `LLL_CONFIG_HOME`
(inside the worker directory) so a worker can act as a second identity; the
URL always comes from conn.txt. Case 15's worker is a person, not a bot,
because a bot cannot own a bot.
