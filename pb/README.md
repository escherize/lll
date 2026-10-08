# PocketBase

lll embeds PocketBase v0.40.1 in-process; `lll up` starts it. There is no
separate PocketBase binary to install or run.

- `pb_migrations/*.js` - the schema: collections, fields, indexes and
  collection rules. `embed.go` compiles them into the binary. On every boot
  gopb unpacks them to `<pb-dir>/pb_migrations` and PocketBase applies the
  ones it has not applied yet, before the server listens.
- `pb_migrations/lib/rules.js` - helpers to add or remove one clause of a
  collection rule. Not a migration: PocketBase loads only the top-level
  files.
- `../gopb/` - every runtime hook, in Go: issue numbering, write guards,
  claims, roster scoping, webhooks. There are no JS hooks.
- `pb_data/` - the local database of `mise run dev`. Gitignored.

## Adding a migration

Name it `<unix time>_<what>.js` with a timestamp no other file uses.
PocketBase records each applied migration by file name, so:

- Never rename or delete a migration that has shipped. A renamed file runs
  again on every existing database.
- Files apply in name order. The three timestamps that two files share
  (1789500000, 1789700000, 1789900000) stay as they are;
  `scripts/test_migration_names.py` fails on a new one.

To change a rule, add or remove one clause instead of assigning the whole
string:

```js
const rules = require(`${__migrations}/lib/rules.js`);
const NO_ASSIGNEE = "@request.body.assignee:isset = false";
migrate(
  (app) => rules.addClause(app, "issues", "createRule", NO_ASSIGNEE),
  (app) => rules.removeClause(app, "issues", "createRule", NO_ASSIGNEE),
);
```

Then run `mise run api-schema`. It boots a fresh database through every
migration and rewrites `src/commands/api_schema.lis` and
`scripts/fixtures/collection_rules.json`. The gate fails when either differs
from what the migrations build, so a dropped rule clause shows up as a changed
line in the snapshot. Review that diff.
