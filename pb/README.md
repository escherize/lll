# PocketBase

Stock PocketBase, pinned at **v0.40.1**. The binary is gitignored — install it
with `brew install pocketbase` or download the v0.40.1 release from
https://github.com/pocketbase/pocketbase/releases and place it here as
`pb/pocketbase`.

- `pb_migrations/` — schema as code, applied automatically on `serve`.
- `pb_hooks/main.pb.js` — per-team issue numbering.

Run locally:

```sh
pocketbase serve --dir pb/pb_data \
  --migrationsDir pb/pb_migrations --hooksDir pb/pb_hooks
```
