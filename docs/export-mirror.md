# Markdown export mirror

`bin/lll-export [DIRECTORY]` generates local issue and document Markdown using
the configured `lll` CLI. It requires Python 3 on Unix. It uses the checkout's
built binary when present, otherwise `lll` on PATH; `LLL_BIN` selects another
binary. Normal CLI URL, team, token and HOME configuration applies.

```sh
bin/lll-export mirror
rg 'regression' mirror/issues mirror/docs
```

The default is `mirror/` under the current directory. Every issue page is read;
`lll issue list --json --page 2` exposes explicit page access for other consumers.
`--limit` sets that command's page size (default 200; server maximum 500).
Sorting includes an ID tie-breaker so tied fields have a stable page order.

Each mirror contains `issues/KEY-N.md`, `docs/SLUG.md`, and a generated
`.lll-export.json` manifest. The export is one-way: edit the record in lll,
then regenerate. Deleted records disappear from the next successful export.
Files can be searched without a live server after export.

A refresh stages all reads before publication. If any enumeration or record
read fails, the previous mirror remains intact. The exporter checks its manifest
and refuses edited output, extra files, unmanaged directories and symlinks.
Use a new destination for an older unmarked mirror; retain the old directory
for comparison and remove it deliberately when no longer needed. There is no
implicit adoption or force-delete option.

For Git history, put the generated directory *inside* a repository. Do not
point the exporter at the repository root or put `.git` inside the mirror.
The sibling `.DIRECTORY.lll-export.lock` is a persistent advisory lock for
cooperating exporters; it can be ignored by Git. Removing the lock while an
export runs defeats coordination. Publication retains `.DIRECTORY.lll-previous`
until the new tree is installed. The next invocation recovers that previous
mirror if publication was interrupted. Readers can briefly see an absent target
during the two directory renames; this utility is not an atomic reader API.

This is a text projection over several requests, not a transactional snapshot.
A changing issue count or duplicate record across pages makes it fail rather
than publish a known incomplete inventory. It does not download attachment
bytes, preserve all database metadata, schedule itself, or push Git. Use the
[hosted recovery procedure](hosted-recovery.md) for a restorable backup.
