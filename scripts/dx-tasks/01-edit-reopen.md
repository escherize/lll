## Your task: Edit and reopen an issue

Work through all 14 outcomes. Use only the CLI, its help and messages for product discovery; ordinary shell, Git and JSON tools may prepare inputs and verify results. Do not read implementation or other reviews. Record honest failures and continue independent outcomes. All data, credentials and destructive actions are confined to your assigned disposable environment.

1. Authenticate as AGENT with email AGENT@example.com against the supplied server.
2. Attach the supplied repository to a new team with key DX.
3. Create a label named regression and a project named Release polish.
4. Create an issue titled Retry login with a two-line description, high priority, the regression label and the Release polish project.
5. Read the issue and verify every supplied field.
6. Change only its title to Retry login after timeout. Verify the description, priority, label and project remain intact.
7. Replace the description with multiline Markdown read from a local file through standard input. Verify the exact text round-trips.
8. Add a multiline comment through standard input, including literal quotes and a dollar sign. Verify its body and author.
9. Move the issue to in-review, then close it; verify both transitions.
10. Reopen the issue into todo. Verify its description, labels, project and comment survived.
11. Change priority to low and verify it.
12. Attempt to set an invalid state; verify a nonzero exit, useful guidance and no changes to the issue.
13. Export the issue as JSON and parse it with a standard tool. Assert its final title and todo state.
14. Read the issue as plain Markdown, then verify the repository branch, refs and tracked files stayed unchanged throughout the issue edits.
