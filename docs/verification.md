# How lll is verified

Agents exercise the CLI. An independent reviewer compares their reports with
captured calls and the board’s actual records. Scripted tests separately probe
concurrency, access boundaries and upgrade recovery.

## Recent published releases

Checked 11 November 2026. These are the retained release checks for 1.4.1,
1.5.0 and 1.6.0, run on 6–9 November. They are a bounded sample, not a lifetime
total or a rerun of the older 200-agent research replay.

| Release | Fresh agents, all attempts | Audited CLI calls | Exact board artifacts | Tool-owned failed calls |
| --- | ---: | ---: | ---: | ---: |
| [1.4.1](https://github.com/escherize/lll/releases/tag/v1.4.1) | 5 | 40 | 3/3 | 0 |
| [1.5.0](https://github.com/escherize/lll/releases/tag/v1.5.0) | 7 | 74 | 4/5 | 0 |
| [1.6.0](https://github.com/escherize/lll/releases/tag/v1.6.0) | 5 | 94 | 4/4 | 0 |
| **All attempts** | **17** | **208** | **11/12** | **0** |

A pair shares one board, so agents and board artifacts have different
denominators. The workers were fresh `gpt-6-luna` agents, with at most three
active at once, followed by a fresh reviewer using the parent model.

The failed 1.5.0 paired edit included a terminal newline where the checker
required exactly three lines. A fresh pair passed on the same binary after the
brief was clarified. Both attempts remain in the totals. The final selected
cohorts were 15 workers, 186 calls and 11/11 board artifacts; the table above
also includes the original failed pair.

Across all attempts there were **12 nonzero exits**: 11 expected controls
(expired or retired credentials and stale writes) and one worker-owned
refusal after a duplicate bot-create command. Zero were classified as caused
by lll. A successful command can still leave the wrong artifact; that is why
the board is checked independently. Reported call counts and ordering were
occasionally wrong; the totals come from the controller’s audits.

## Hardening checks

These are executable regression checks, separate from the real-agent counts.
The figures below were read from successful full gates on 11 November 2026;
they describe that source revision, not every future build.

| Failure being tested | What the check exercises |
| --- | --- |
| A hostile page sends a write with a valid cookie | **434 refused requests across 31 write routes**, varying origin headers and cookie identity. Same-origin writes still succeed. |
| An agent retries after a timeout | **24 issue-create calls** and **12 comment calls**, each group racing on one idempotency key; matching retries reuse the record, conflicting payloads refuse, and lost responses do not duplicate writes. |
| The checker accepts the wrong result | **20 scripted task scenarios**, each with a correct worker that must pass and a deliberately wrong worker that must fail. These are not fresh agents. |
| A client or server is upgraded first | Four baseline/candidate client-server pairs, preserved records and a stopped pre-upgrade backup restored with its matching old binary. Missing capabilities refuse before writes when the tested baseline lacks them. |
| CI passes but the installed package is wrong | Release downloads checked outside the checkout; native behavior rerun; actual Homebrew path, version and binary bytes checked, then authenticated hosted reads. Linux assets are hash-verified, with a separate Linux container/browser gate; they were not executed locally on the Mac. |

The release checks include recovery, not just a green version banner. They do
not establish safe database downgrades or turn a finite test run into a claim
that the product has no defects.

## Follow a run

1. Freeze the source commit and binary hash.
2. Give each fresh agent an isolated board, identity and CLI wrapper.
3. Capture calls outside the worker’s writable files.
4. Judge exact records, attribution and unexpected writes on the server.
5. Have a fresh reviewer reconcile every report, audit and result.
6. Stop owned servers, remove temporary credentials and retain sanitized evidence.

[Run the approved cases](agent-dx-fleet/how-to-run.md) or read the
[release checklist](release-checklist.md). The initial research runs, including
aborted or incomplete instrumentation, remain in the
[historical results](agent-dx-fleet/results.md); they are not added to these totals.

## Sources

[Machine-readable release counts](verification-counts.json) record the exact
cuts, audit hashes, checker totals and retained bundle hashes. Complete raw
reports, audited calls, server snapshots, reviewer classifications and cleanup
receipts are attached to the corresponding release issues on the project’s
board (sign-in required):

- [LLL-755: 1.4.1 evidence](https://escherize-lll.fly.dev/issue/LLL-755)
- [LLL-773: 1.5.0 evidence](https://escherize-lll.fly.dev/issue/LLL-773)
- [LLL-779: 1.6.0 evidence](https://escherize-lll.fly.dev/issue/LLL-779)

Executable sources: [board origin](https://github.com/escherize/lll/blob/530e3a1e6705d540ccb3d221cda9b2a620fa87a7/scripts/test_board_origin.py),
[issue retries](https://github.com/escherize/lll/blob/530e3a1e6705d540ccb3d221cda9b2a620fa87a7/scripts/test_issue_idempotency.py),
[comment retries](https://github.com/escherize/lll/blob/530e3a1e6705d540ccb3d221cda9b2a620fa87a7/scripts/test_comment_idempotency.py),
[fleet controls](https://github.com/escherize/lll/blob/530e3a1e6705d540ccb3d221cda9b2a620fa87a7/scripts/test_agent_dx_fleet.py),
and [upgrade rehearsal](https://github.com/escherize/lll/blob/530e3a1e6705d540ccb3d221cda9b2a620fa87a7/scripts/rehearse_upgrade.py).
