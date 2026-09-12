## Your task: Rotate credentials and hand off automation access

Work through all 14 outcomes. Use only the CLI, its help and messages for product discovery; ordinary shell, Git and JSON tools may prepare inputs and verify results. Do not read implementation or other reviews. Record honest failures and continue independent outcomes. All data, credentials and destructive actions are confined to your assigned disposable environment.

1. Authenticate as AGENT with email AGENT@example.com against the supplied server.
2. Attach the supplied repository to a new team with key DX.
3. Create a colleague COLLEAGUE with email COLLEAGUE@example.com and a password they can use.
4. Authenticate the colleague in a separate empty HOME and verify authenticated identity.
5. Create a shared issue and verify the colleague can read it.
6. Using explicit administrator authority, set a replacement password for the colleague.
7. In another empty HOME, verify the old password fails and the replacement succeeds; do not expose either in the report.
8. Create an automation member and mint a short-lived static token for that member using administrator authority.
9. Use that token in a separate environment to read the issue; verify authenticated identity is the automation member.
10. Without administrator credentials, attempt to mint another static token; verify a truthful refusal.
11. Log the colleague out and verify a fresh process in that HOME no longer has a saved login credential.
12. Log the colleague in again with the replacement password and verify access is restored.
13. Switch authentication in the original HOME to the colleague and assess guidance about any retained comment-author override; deliberately set the intended author and verify a comment.
14. Preserve exact tested handoff commands in a separate private artifact, and verify no credential entered repository config or the public report.
