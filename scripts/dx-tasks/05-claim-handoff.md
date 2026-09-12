## Your task: Coordinate exclusive claims and handoffs

Work through all 14 outcomes. Use only the CLI, its help and messages for product discovery; ordinary shell, Git and JSON tools may prepare inputs and verify results. Do not read implementation or other reviews. Record honest failures and continue independent outcomes. All data, credentials and destructive actions are confined to your assigned disposable environment.

1. Authenticate as AGENT with email AGENT@example.com against the supplied server.
2. Attach the supplied repository to a new team with key DX.
3. Create a colleague COLLEAGUE with email COLLEAGUE@example.com who can authenticate independently.
4. Create one shared issue and prepare a separate local HOME for the colleague. Authenticate each identity in its own HOME and ensure comments use the intended author.
5. As AGENT, claim the issue and verify claimant and assignee.
6. As COLLEAGUE, attempt to claim the held issue. Verify nonzero refusal and unchanged claimant/assignee.
7. As AGENT, repeat the claim and assess whether the response accurately describes current ownership.
8. As AGENT, add a handoff comment with next steps, then release the claim.
9. As COLLEAGUE, claim the released issue and verify ownership and assignment.
10. As COLLEAGUE, add an acknowledgement; verify both comments have the expected authors.
11. As COLLEAGUE, start work and verify ownership is retained and Git unchanged.
12. As COLLEAGUE, move the issue to review, close it and inspect whether the claim remains; record the observed lifecycle accurately.
13. If still claimed, explicitly release it. Verify no claim remains.
14. From both identities, parse the final issue JSON and verify state, assignment and comments agree.
