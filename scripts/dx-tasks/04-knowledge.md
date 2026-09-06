## Your task: Write and retrieve project knowledge

Work through all 14 outcomes. Use only the CLI, its help and messages for product discovery; ordinary shell, Git and JSON tools may prepare inputs and verify results. Do not read implementation or other reviews. Record honest failures and continue independent outcomes. All data, credentials and destructive actions are confined to your assigned disposable environment.

1. Authenticate as AGENT with email AGENT@example.com against the supplied server.
2. Attach the supplied repository to a new team with key DX.
3. Create label storage and an issue titled Fix cache eviction carrying that label.
4. Create a wiki document with slug index, title Team guide and a multiline Markdown body supplied from stdin.
5. Retrieve its raw body and verify an exact text round-trip.
6. Revise the title and body; verify the same slug identifies the revised document.
7. Create a finding with slug cache-locking, area storage, and paths src/cache, tests/cache, describing a locking constraint.
8. Find that document by its area and verify unrelated areas return no finding.
9. Find it near src/cache/store.lis and near src; verify directory containment works.
10. Link index to the issue; verify the issue and document show the relationship.
11. Verify the storage finding is surfaced when viewing the labeled issue.
12. Unlink index and verify the explicit relationship disappears while the area finding remains.
13. Export documents as JSON and parse the results; verify their kinds and contents.
14. Delete index with explicit authorization, verify cache-locking survives, and verify reading the deleted slug gives useful failure guidance.
