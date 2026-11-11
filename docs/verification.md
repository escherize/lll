# How lll is verified

Agents exercise the CLI. An independent reviewer compares their reports with
captured calls and the board’s actual records. Scripted tests separately probe
concurrency, access boundaries and upgrade recovery.

## Research at scale

The original research record documents **2,061 Claude Code agent trials across
145 fleet runs**, plus 36 workers in the first `gpt-5.6-luna` harness. The
landing page rounds the main research count down to **2,000+ agent trials**.
These are worker runs, including retries and failures, not unique people or
2,061 successful outcomes.

This historical aggregate was published in the
[original landing-page PR](https://github.com/escherize/lll/pull/353) and
[12 October 2026 source](https://github.com/escherize/lll/blob/4443c315aeacf4c75b1f68ba28ce6b553d056266/docs/index.html).
It is a reported research total, not a new recount of every historical audit.
We keep it separate from the independently recounted release cohorts below;
we do not add potentially overlapping campaigns into a new lifetime total.

One recorded research replay covered **20 scenarios with 10 fresh workers
each** and reported **196/200 correct agent outcomes**. Paired workers shared
a board: those 200 outcomes are not 200 independent boards. That historical
replay is retained in the landing page’s expandable ledger. It is not a
current-build pass rate.

## Recent published releases

Checked 11 November 2026. These are the retained release checks for 1.4.1,
1.5.0, 1.6.0 and 1.6.1, run on 6–11 November. They are a bounded sample, not a lifetime
total or a rerun of the older 200-agent research replay.

| Release | Fresh agents, all attempts | Audited CLI calls | Exact board artifacts | Tool-owned failed calls |
| --- | ---: | ---: | ---: | ---: |
| [1.4.1](https://github.com/escherize/lll/releases/tag/v1.4.1) | 5 | 40 | 3/3 | 0 |
| [1.5.0](https://github.com/escherize/lll/releases/tag/v1.5.0) | 7 | 74 | 4/5 | 0 |
| [1.6.0](https://github.com/escherize/lll/releases/tag/v1.6.0) | 5 | 94 | 4/4 | 0 |
| [1.6.1](https://github.com/escherize/lll/releases/tag/v1.6.1) | 5 | 36 | 5/5 | 0 |
| **All attempts** | **22** | **244** | **16/17** | **0** |

A pair shares one board, so agents and board artifacts have different
denominators. The workers were fresh `gpt-6-luna` agents, with at most three
active at once, followed by a fresh reviewer using the parent model.

The failed 1.5.0 paired edit included a terminal newline where the checker
required exactly three lines. A fresh pair passed on the same binary after the
brief was clarified. Both attempts remain in the totals. The final selected
cohorts were 20 workers, 222 calls and 16/16 board artifacts; the table above
also includes the original failed pair.

Across all attempts there were **17 nonzero exits**: 16 expected controls
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
- [LLL-781: 1.6.1 evidence](https://escherize-lll.fly.dev/issue/LLL-781)

Executable sources: [board origin](https://github.com/escherize/lll/blob/530e3a1e6705d540ccb3d221cda9b2a620fa87a7/scripts/test_board_origin.py),
[issue retries](https://github.com/escherize/lll/blob/530e3a1e6705d540ccb3d221cda9b2a620fa87a7/scripts/test_issue_idempotency.py),
[comment retries](https://github.com/escherize/lll/blob/530e3a1e6705d540ccb3d221cda9b2a620fa87a7/scripts/test_comment_idempotency.py),
[fleet controls](https://github.com/escherize/lll/blob/530e3a1e6705d540ccb3d221cda9b2a620fa87a7/scripts/test_agent_dx_fleet.py),
and [upgrade rehearsal](https://github.com/escherize/lll/blob/530e3a1e6705d540ccb3d221cda9b2a620fa87a7/scripts/rehearse_upgrade.py).
