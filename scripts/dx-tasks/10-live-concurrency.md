## Your task: Consume live changes from concurrent clients

Work through all 14 outcomes. Use only the CLI, its help and messages for product discovery; ordinary shell, Git and JSON tools may prepare inputs and verify results. Do not read implementation or other reviews. Record honest failures and continue independent outcomes. All data, credentials and destructive actions are confined to your assigned disposable environment.

1. Authenticate as AGENT with email AGENT@example.com against the supplied server.
2. Attach the supplied repository to a new team with key DX.
3. Create labels bug and chore and two issues, one carrying each label.
4. Start a machine-readable live stream for bug issues in a supervised process with captured stdout/stderr; use a bounded timeout and ensure readiness before mutations.
5. From a separate client, create a bug issue and verify a parseable create event arrives.
6. Update that issue title and priority; verify a matching update event arrives.
7. Update the chore issue; verify it is absent from the bug-filtered stream.
8. Start a separate stream for the created issue and its comments; ensure readiness.
9. Add a comment from another client; verify the issue-specific stream receives it.
10. Run two independent clients that each create three uniquely titled bug issues; verify every mutation succeeds and resulting identifiers are unique.
11. Verify the bug stream captured all six creates and every nonempty stdout line parses as JSON.
12. Explicitly delete one of those issues and verify the filtered stream receives its delete event.
13. Interrupt both streams deliberately, reap the processes, and record their actual exit codes separately from product failures in your interpretation; still count every invocation under the transcript rules.
14. Query final server state as JSON, reconcile it with observed events, and verify no watcher processes were left running.
