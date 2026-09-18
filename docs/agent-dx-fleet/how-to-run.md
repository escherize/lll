# Running the approved lll DX cases

The approved scope is case 01 followed by case 05, ten fresh workers per case,
with at most three active workers. Use fresh agents, not follow-up tasks to
agents that have learned the CLI. Worker model: gpt-5.6-luna. Each run gets a
new parent-model reviewer reading every raw report, call audit and REST result.

Build the intended source revision and record the commit and binary SHA256.
Run `python3 scripts/test_agent_dx_fleet.py` before provisioning. Start
`scripts/agent_dx_fleet.py` with `--root` pointing to an absent temporary
path, `--binary` pointing to the built binary, and its exact `--commit` and
`--sha256`. Keep this process alive; it owns all children. It copies the
binary and records its fingerprint before accepting JSON lines on stdin.

Send `{"action":"provision","case":"01","run":1}`. Launch workers only after
the controller reports all ten ready. Give each worker only its case rules,
number, directory and `lll` wrapper path. Workers invoke that wrapper from
their own directory. It supplies the isolated environment and audits exact
arguments, exit status and redacted output. Never print `conn.txt` or paste a
token into a prompt. The wrapper permits the CLI only; task rules prohibit
source, raw HTTP, the UI, identity changes and server/config operations.

After every worker has written report.json and report.md, send
`{"action":"judge"}`. The controller snapshots all eleven member-writable
collections over REST, compares every seeded record, counts every new record
and verifies the exact expected author/creator, fields and relations.
Durable snapshots redact webhook secrets. A fresh reviewer writes review.json,
review.md and summaries.json. Assemble run.json with summaries, review,
checker results and fingerprint, then run the shared tally.py and save stdout.
The owner uses the audits and ground truth, not worker done claims.

Pass requires ten exact artifacts and fewer than two workers with a tool-owned
failed invocation. Repeated tool failure classes get their own claimed issue
and verified fix. Then stop the old case and rerun the same case with fresh
instances and agents before advancing. Record harness/task-design corrections
separately. A new binary requires a new controller and fresh root; never replace
the binary beneath live workers. Replay both approved cases on the final build.

Send `{"action":"stop"}` after review, then `{"action":"exit"}` when changing
builds or finishing. Stop waits/reaps owned children, verifies all twenty
listeners are gone, removes connections and private controller data. Scan
sanitized evidence for credentials, remove disposable worker HOME/cache, and
retain only reports, audits, snapshots, reviews, tally, fingerprints and cleanup
receipts. Attach the evidence bundle and closing table to LLL-402.
