# lll case 05: create an issue (tier 2)

Use the same isolation, reporting and credential rules as case 01. The controller
provides a fresh board and existing bot for this case; no prior-case residue.

Using only the controller-provided lll wrapper, create exactly one issue in team
FLEET with title `Repair flaky upload retry (worker NN)`, description
`Retry a dropped upload once and preserve the saved attachment.`, state `todo`,
priority 2, label `bug`, and project `Fleet sandbox`. Replace NN with your worker
number. Discover command forms through the CLI's help; no source or raw HTTP.

Read the complete resulting issue back and check all six fields and your bot
creator identity. If a write fails, inspect before retrying. Leave seeded issues,
labels, projects and members unchanged. Do not create a second copy or a new
project/label to satisfy lookup failures.

The independently checked artifact is exactly one worker-title issue with the
specified fields and the existing bot as creator. Write `report.json` and
`report.md` using case 01's schema and complete invocation/failure/guess log.
Three failures on one operation means stop and record blocked. Report success
only after read-back.
