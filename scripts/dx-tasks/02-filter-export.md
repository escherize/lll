## Your task: Find and export a precise issue subset

Work through all 14 outcomes. Use only the CLI, its help and messages for product discovery; ordinary shell, Git and JSON tools may prepare inputs and verify results. Do not read implementation or other reviews. Record honest failures and continue independent outcomes. All data, credentials and destructive actions are confined to your assigned disposable environment.

1. Authenticate as AGENT with email AGENT@example.com against the supplied server.
2. Attach the supplied repository to a new team with key DX.
3. Create a project named Checkout and labels bug and chore.
4. Create four issues: Checkout timeout (high, bug, Checkout, todo), Checkout copy (low, chore, Checkout, todo), Search timeout (urgent, bug, no project, in-review), and Checkout old timeout (medium, bug, Checkout, done).
5. Assign Checkout timeout to yourself.
6. Find issues with timeout in their titles and verify the exact three matches.
7. Find todo issues in Checkout carrying bug and verify only Checkout timeout matches.
8. Find your assigned issues and verify Checkout timeout is included.
9. List all four by descending number and verify the ordering.
10. Limit the ordered list to two results and verify the exact two newest issues.
11. Export the filtered todo/Checkout/bug query as JSON, parse stdout directly, and verify exactly one match.
12. Run a query with no matches; verify successful, valid empty JSON.
13. Attempt an invalid sort and invalid limit, recording each exit and whether guidance permits correction.
14. Confirm failed reads changed no issues, and verify successful JSON stays on stdout while an invalid query error stays on stderr.
