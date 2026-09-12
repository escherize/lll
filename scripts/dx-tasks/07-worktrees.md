## Your task: Hand work between branches and worktrees

Work through all 14 outcomes. Use only the CLI, its help and messages for product discovery; ordinary shell, Git and JSON tools may prepare inputs and verify results. Do not read implementation or other reviews. Record honest failures and continue independent outcomes. All data, credentials and destructive actions are confined to your assigned disposable environment.

1. Authenticate as AGENT with email AGENT@example.com against the supplied server.
2. Attach the supplied repository to a new team with key DX.
3. Create an issue titled Repair worktree handoff and record its state and current work location.
4. Obtain a suggested branch name without changing issue state, Git branches, refs or files.
5. Explicitly create the suggested Git branch yourself and begin work on the issue.
6. Verify the recorded branch, host and path match the current repository.
7. From a nested directory, view the issue without naming it; verify inference and the recorded repository-root path.
8. Using Git yourself, create a second worktree on a distinct branch that still identifies the same issue. Carry over only the intended shared team configuration.
9. Begin work from the second worktree and verify the current recorded path and branch now match it.
10. Verify a history comment records the work-location handoff.
11. Repeat start in the same worktree; verify no duplicate move comment and no Git mutations.
12. From an unrelated branch, explicitly start the same issue; verify the unrelated branch is not falsely recorded as its work location.
13. Close the issue and verify the last valid location remains visible.
14. Parse the final JSON, verify only deliberate Git commands changed Git, and clean up the extra worktree using Git yourself.
