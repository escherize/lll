## Your task: Work across two teams safely

Work through all 14 outcomes. Use only the CLI, its help and messages for product discovery; ordinary shell, Git and JSON tools may prepare inputs and verify results. Do not read implementation or other reviews. Record honest failures and continue independent outcomes. All data, credentials and destructive actions are confined to your assigned disposable environment.

1. Authenticate as AGENT with email AGENT@example.com against the supplied server.
2. Attach the supplied repository to a new team with key DX.
3. Create a second team with key OPS.
4. Create a label bug and project Delivery in each team, with deliberately identical names.
5. Create one issue titled DX delivery in DX and one titled OPS delivery in OPS, each linked to its own bug label and Delivery project.
6. List issues separately for each team without rewriting the repository attachment; verify isolation.
7. Create a wiki document with slug index in each team and different bodies; verify scoped reads return the intended content.
8. While DX is the default, read the OPS issue by explicit identifier and verify the correct target.
9. Change only the OPS issue priority through its explicit identifier; verify the DX issue remains unchanged.
10. Rename OPS to OPS2 and verify the issue identifier follows the new team key.
11. Recover any stale configuration using the tool guidance, then verify OPS2 issue and document access.
12. Archive OPS2 and verify ordinary team lists omit it while an explicit archived-inclusive list retains it.
13. Unarchive OPS2 and verify its issue, project, label and document remain.
14. Restore DX as the repository default and verify both teams still have their intended separate data.
