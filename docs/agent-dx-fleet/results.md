# LLL-402: initial approved fleet results

> Historical results from the plan approved on 2026-09-18, recorded before the
> harness PR landed and final-main replay. Pending work below describes that
> snapshot, not current release status. See LLL-402 for subsequent evidence and
> [how to run](how-to-run.md) for current procedure. Original case 05 here is
> current case 06; use [the rules directory](rules/) for the current case index.

Both approved cases passed on rerun. The first case 05 run was aborted because
its call audits were unreliable; its invocation totals remain unavailable.

The user approved case 01 (find/read/comment), then case 05 (create an issue),
with ten fresh `gpt-5.6-luna` workers per case and fresh parent-model reviewers.
Workers ran in batches of at most three on independent local boards and bot
identities. The other eighteen cases in the plan had not been executed at this snapshot.

At this snapshot, both approved cases still required replay against the final
main binary. The final report and sanitized evidence were to be attached to
LLL-402 so recording that replay would not change the binary's embedded Go
revision metadata and require another replay.

| Case | Run | Exact artifacts | Captured calls | Failed calls | Workers with tool failures | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | 1 | 10/10 | 81 | 2 | 2 | FAIL: repeated search scope flag rejection |
| 01 | 2 | 10/10 | 74 | 0 | 0 | PASS: independent reviewer |
| 05 | 1 | 6/10 planned; 6/6 launched | unavailable | unavailable | unavailable | ABORTED: worker-replaced audit files |
| 05 | 2 | 10/10 | 75 | 0 | 0 | PASS: independent reviewer |

Case 01 baseline used main `27009d8df6123ab26ebb360ff0f17443c05477ad`, binary
SHA256 `ab3addad57c1fc4fe06cc4376c8482ba94c3bb06d570b2c69e8cdb88d203a5cb`.
Workers 01 and 03 independently tried `lll search "socket reset" --team FLEET`;
both received the unknown-flag error. LLL-483 repaired the omitted existing
process-scoped override in [PR 150](https://github.com/escherize/lll/pull/150).
The focused actual-CLI regression checks configured/environment/explicit scope,
both flag forms, cache separation, JSON/help, literal query text and unchanged
configuration. Local full gate, PR macOS/Linux gates, main macOS/Linux gates and
Fly deployment passed. The same regression passed against an actual production
Dockerfile artifact outside the checkout.

Both corrected initial cases used fix commit
`9806c0676033f6618515e3a5e93d9c2f1966698d`, binary SHA256
`ab0f28e1e04107d06d060d0f2d9822221e651365df57e2bd53f46b314cfa6752`.
Seven distinct case 01 rerun workers successfully used `search --team`.

The baseline checker omitted webhooks. All ten after-only webhook checks were
empty, but the missing before state cannot be reconstructed; baseline coverage
remains qualified. The recorded reruns captured all eleven member-writable collections,
compared every seeded record, counted every new record, verified exact fields
and author/creator, and rejected unrelated writes and duplicates. Adversarial oracle
tests exercise those rejection paths.

Case 05 run 1 stopped after six workers replaced their local `calls.jsonl` with
manual logs, including malformed and mixed-schema records. Four planned workers
were never launched. All six actual issue artifacts were correct, but exact
invocation/failure totals are unavailable. Raw files remain preserved; no counts
were inferred from worker claims or repaired JSON. The fresh reviewer classified
the run as incomplete harness evidence. Case 01 audits retain the original
wrapper schema and showed no such replacement.

The corrected controller captures primary audits outside worker directories and
publishes them only after workers return. Worker briefs explicitly prohibit
editing instrumentation. Any worker-supplied audit is preserved separately.
Case 05 run 2 had no worker-supplied audit, and every published file matched its
private primary byte for byte. Contract tests verify that worker tampering cannot
change the authoritative calls, publication is repeatable, credentials are
redacted, and only owned children are terminated and reaped.

Prelaunch failures are separate harness events: inherited administrator settings
overrode the person token when minting bots, then REST project seeding omitted a
required status. Both failed before workers launched and were cleaned up.
Independent preflight also led to complete collection coverage, secret
redaction, fresh-path enforcement, constructor cleanup and a self-contained
case 05 brief. The controller pins binary, wrapper and startup-helper code before
launch so later checkout edits cannot alter live workers.

Shared skill corrections landed upstream in
[PR 1](https://github.com/metabase/agent-instructions/pull/1) and
[PR 2](https://github.com/metabase/agent-instructions/pull/2), with both main
CodeQL runs successful. They require owned lifecycle/readiness, independent
ground truth, complete evidence review, private authoritative audits, honest
unavailable-count handling and final-build replays. Legacy shell helpers are
explicitly qualified; this change does not claim to rewrite their lifecycle.

The documented title-only issue-list filter produced navigation papercuts for
seven baseline and five rerun workers, without failed invocations. LLL-484
records the product decision about empty-result guidance. Its filter semantics
were not changed by this audit.

Nine case 05 workers reported reconstructing the issue key from JSON number and
expanded team key. All read-backs succeeded; this is a successful-call papercut,
not a failed invocation class. LLL-485 records the output-contract decision.

Baseline and aborted-run sanitized evidence are attached to LLL-402. Completed
controllers verified all twenty owned listeners gone and removed connections,
private data and worker HOME/cache. At this snapshot, successful-run evidence and final
main replay receipts still needed to be attached before LLL-402 could close.
