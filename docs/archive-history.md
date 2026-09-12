# Retained sidecar history

New issues, findings, decisions and worklogs belong on the hosted LLL board.
A local `.private` repository is optional, archived history. Fresh checkouts
need not clone it.

If the archive is retained, protect it once:

```sh
mise run archive-protect
```

This removes write permissions from its files and directories, including
`.git`. Contents and read/execute permissions remain intact. The gate checks
protection without changing permissions; `python3 scripts/protect_archive.py
--check` runs that check directly. No archive means the check succeeds without
creating one.

Protection refuses an uncommitted archive, symlinks, special files, entries
owned by another user and writable hard links. Resolve those deliberately
before applying it. Run as the archive owner, not root. This is protection
against ordinary accidental writes, not against an owner deliberately changing
permissions, privileged access, or a descriptor opened for writing earlier.

The original cwd failure is documented on LLL-51. Both `cat >> mise.toml`
from inside `.private` and a Git branch/worktree write now encounter filesystem
permission errors. Reading history still works. Choosing an explicit working
directory remains useful, but `git -C` alone never covered raw file writes.
The hosted decision `protect-archived-sidecar-with-filesystem-permissions`
supersedes that task-21 worklog advice without editing historical evidence.

Routine agents should not re-enable archive writes. Intentional maintenance
requires an explicit permission change by the owner; it does not restore the
old sidecar workflow. The archive's write protection also does not select the
correct public working directory for a command—that remains the tool caller's
responsibility.
