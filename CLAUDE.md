
<!-- private-sync pointer -->
## Project knowledge lives in .private/

Sidecar git repo (gitignored, own remote, synced via plain git). Use the
`private-sync` skill for full conventions. Quick map:

- `.private/wiki/` - current truth, start at wiki/index.md
- `.private/decisions/` - ADRs, immutable, supersede-only
- `.private/findings/<agent>/` - things learned the hard way, append-only
- `.private/worklogs/<agent>/` - session logs, append-only
- `.private/backlog/` - tasks, via the backlog CLI only

**Before writing any code for nontrivial work: claim a task.** Find or create
it (`backlog task create "..."`), then
`backlog task edit <id> -a @<agent-id> -s "In Progress"` and push the sidecar
immediately. Work nobody claimed gets duplicated; a claim nobody pushed
protects no one. When the work lands: `-s Done`, worklog, push.

Be noisy: file every issue you pass (`backlog task create "..."`) instead of
fixing or ignoring it, then return to your claimed task. Deal-with-later is
the point; silent discoveries are lost.

Before starting: read `.private/wiki/index.md`, then
`git -C .private log --oneline -20`. Commit and push sidecar changes
separately: `git -C .private add -A && git -C .private commit && git -C .private push`.
If `.private/` is missing: `git clone "$(cat .private-remote)" .private`.
Never commit `.private/` contents or secret values to the public repo.
<!-- /private-sync pointer -->
