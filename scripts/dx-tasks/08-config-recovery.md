## Your task: Diagnose configuration and recover from an outage

Work through all 14 outcomes. Use only the CLI, its help and messages for product discovery; ordinary shell, Git and JSON tools may prepare inputs and verify results. Do not read implementation or other reviews. Record honest failures and continue independent outcomes. All data, credentials and destructive actions are confined to your assigned disposable environment.

1. Authenticate as AGENT with email AGENT@example.com against the supplied server.
2. Attach the supplied repository to a new team with key DX.
3. Persist the supplied board endpoint, then verify it from a new shell without a board-URL environment override.
4. Inspect effective configuration and identify which sources supplied server, team, identity and board URL.
5. Add a different board URL to the local repository config, preserving the team; verify the repository value wins over the home value.
6. For one invocation, set a third board URL through the environment; verify it wins without rewriting either file.
7. Remove the temporary overrides and verify the original persisted board endpoint returns.
8. Override the API endpoint to http://127.0.0.1:1 for one invocation; diagnose the unavailable server and verify a failing exit with truthful guidance.
9. With that unavailable endpoint, attach a new team key OFFLINE; inspect what was saved and whether the message distinguishes local config from server readiness.
10. Restore the real API endpoint and authenticate again. Verify readiness does not falsely claim the missing OFFLINE team exists.
11. Explicitly reconcile the attachment against the real server, then create an issue to prove recovery.
12. Attempt to persist a malformed board endpoint with a query/fragment and verify rejection leaves the previous value intact.
13. Save a comment identity containing a space and an apostrophe, then inspect the effective value to verify configuration escaping.
14. Restore your real identity and DX attachment; verify credentials were never written to the repository config and the live server remains accessible.
