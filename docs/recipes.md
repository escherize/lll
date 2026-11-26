# Recipes

A recipe takes one outcome and works it end to end. Each command in a recipe
was run against a real board, and each recipe ends with what was and was not
verified.

## Written

| Recipe | You end up with |
|---|---|
| [Use lll as the tracker for Matt Pocock's skills](recipe-matt-pocock-skills.md) | `to-spec`, `to-tickets`, `triage` and `wayfinder` publishing to an lll board, and workers taking unblocked tickets with a claim |

## Planned

These are not written yet. The middle column names what lll already has for
each; the last names what is missing before the recipe can be written.

| Recipe | lll already has | Missing |
|---|---|---|
| Run Claude Code and Codex on one project | Agent labels, claims, worktrees | A run with Codex |
| Hand an issue back instead of guessing | `outcome:blocked`, the filter in `lll skill get backlog-loop` | Nothing |
| See what eight agents are doing from one board | Claims, agent labels, `lll watch --activity` | A worked run with several sessions |
| Attach verification evidence to the issue | Comments, `lll skill get verify-gate` | Nothing |
| Label an issue and get a pull request back | Labels, `lll issue next --claim`, webhooks, `lll watch --after CURSOR` | A worked run with a runner that starts agents |
| Run a software factory overnight | The six-stage loop in `lll skill get software-factory`, outcome labels | A worked run on a fresh repo |
| Wake a coordinator and resume after a crash | `lll watch --after CURSOR`, since 1.9.0 | Nothing |
| Put a person at the right point in agent review | Comments, `lll issue watch --until`, the `in-review` state | A worked example |
| Measure how often agents finish without help | `outcome:clean`, `outcome:changed` and `outcome:blocked` labels | A shipped report |
| Give a contractor read-only access to one team | Viewer role, since 1.8.0 | Nothing |
| Let a colleague's agents work your backlog | Bot members with a human owner, per-team Viewer and Editor roles, claims, `lll usage` | A run with two people |
