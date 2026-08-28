# PocketBase

Stock PocketBase, pinned at **v0.40.1**. Running lll needs no PocketBase
install — `lll up` embeds it in-process (see `gopb/`). Only `scripts/e2e.sh`
uses an external binary: install with `brew install pocketbase`, or download
the v0.40.1 release from
https://github.com/pocketbase/pocketbase/releases and place it here as
`pb/pocketbase` (gitignored).

- `pb_migrations/` — schema as code, applied automatically on `serve`.
- `pb_hooks/main.pb.js` — per-team issue numbering.

Run locally:

```sh
pocketbase serve --dir pb/pb_data \
  --migrationsDir pb/pb_migrations --hooksDir pb/pb_hooks
```
