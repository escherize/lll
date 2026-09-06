## Your task: Reorganize labels and projects

Work through all 14 outcomes. Use only the CLI, its help and messages for product discovery; ordinary shell, Git and JSON tools may prepare inputs and verify results. Do not read implementation or other reviews. Record honest failures and continue independent outcomes. All data, credentials and destructive actions are confined to your assigned disposable environment.

1. Authenticate as AGENT with email AGENT@example.com against the supplied server.
2. Attach the supplied repository to a new team with key DX.
3. Create labels old-bug and keep-me, and a project named Old release.
4. Create two issues belonging to Old release, each carrying both labels.
5. Rename old-bug to regression and change its color to #e08040.
6. Verify both issues retained the renamed label and keep-me.
7. Rename Old release to Current release, replace its description, and set its status to started.
8. Verify both issue links survived the project rename.
9. Attempt to delete the in-use regression label without authorizing removal from issues; verify refusal and unchanged links.
10. Explicitly authorize deletion of regression and its removal from issues; verify keep-me survives on both.
11. Attempt to delete the in-use Current release project without authorizing detachment; verify refusal and unchanged links.
12. Explicitly authorize project deletion and detachment; verify both issues survive without that project.
13. Create and delete an unused label and an unused project, verifying their absence.
14. Verify final issue titles, states and keep-me labels, and parse their JSON output.
