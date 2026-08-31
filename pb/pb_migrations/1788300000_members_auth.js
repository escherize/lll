/// <reference path="../pb_data/types.d.ts" />

// TASK-180: members becomes a PocketBase auth collection (ADR-1). Every actor,
// human or agent, is one members record; email is the identity and PocketBase's
// own password auth issues the tokens. The name field and its UNIQUE index
// stay: assignee display and comment authorship resolve by name.
//
// PocketBase refuses type changes on an existing collection ("Collection type
// cannot be changed."), so this cannot go through app.save(). Instead the
// converted definition is first saved as a throwaway EMPTY auth collection,
// which makes PocketBase itself produce the exact fields/options/indexes JSON
// it would write for it; that JSON is then grafted onto the members row and
// the records table is altered and backfilled by hand:
//
//   1. save the template collection (a plain, validated create)
//   2. copy its _collections row onto members (raw UPDATE, id unchanged)
//   3. add the four auth columns, backfill tokenKey/emailVisibility/emails
//   4. create the new UNIQUE indexes, drop the template, reload the cache
//
// Relations (issues.assignee, comments.author) point at the collection id and
// the record ids; neither the id nor a row is touched by the conversion, so
// they survive verbatim. The synthesized email domain is members.invalid
// (RFC 2606 reserved), so a backfilled address can never collide with a real
// one and the down migration can recognize its own output.
//
// Rules stay "" (public) until TASK-181; the auth surface existing does not
// make it public.
migrate(
  (app) => {
    const members = app.findCollectionByNameOrId("members");

    // Idempotent: applying twice (or onto an already-converted database) is a
    // no-op rather than an error.
    if (members.type === "auth") {
      return;
    }

    const tplName = "members_auth_conversion_tpl";

    // The literal keeps the original field ids (via members.fields) so the
    // conversion never drops or renames an existing column. The email field
    // is re-typed in place, keeping its id: same column, now the system email
    // identity (required, unique via the index below).
    const tpl = new Collection({
      type: "auth",
      name: tplName,
      listRule: members.listRule,
      viewRule: members.viewRule,
      createRule: members.createRule,
      updateRule: members.updateRule,
      deleteRule: members.deleteRule,
      fields: members.fields,
      indexes: [
        "CREATE UNIQUE INDEX `idx_tpl_members_name` ON `members` (`name`)",
        "CREATE UNIQUE INDEX `idx_tpl_members_email` ON `members` (`email`)",
      ],
    });

    for (let i = 0; i < tpl.fields.length; i++) {
      if (tpl.fields[i].name !== "email") {
        continue;
      }
      tpl.fields[i] = new EmailField({
        id: tpl.fields[i].id,
        name: "email",
        system: true,
        required: true,
      });
    }

    // A validated create of a NEW auth collection: PocketBase supplies the
    // auth system fields (password, tokenKey, emailVisibility, verified), the
    // tokenKey unique index and the default auth options (password auth on,
    // token durations and per-collection secrets).
    app.save(tpl);

    const tplId = tpl.id;

    // Harvest the JSON PocketBase itself just wrote for the template.
    const tplRow = new DynamicModel({ fields: "", options: "", indexes: "" });
    app
      .db()
      .newQuery(
        "SELECT fields, options, indexes FROM `_collections` WHERE name = {:name}",
      )
      .bind({ name: tplName })
      .one(tplRow);

    // The statements were normalized to the template's table name and its
    // tokenKey index carries the template's collection id; the index names
    // were also prefixed to dodge SQLite's database-global index names (the
    // real idx_members_name already exists on members). Point everything at
    // members' canonical names instead.
    const indexes = tplRow.indexes
      .split("`" + tplName + "`")
      .join("`members`")
      .split(tplId)
      .join(members.id)
      .split("idx_tpl_members_")
      .join("idx_members_");

    // 2. Graft the converted definition onto the members row. The row keeps
    // its id, created and updated, so relations and history survive.
    app
      .db()
      .newQuery(
        "UPDATE `_collections` SET `type` = 'auth', `fields` = {:fields}, `options` = {:options}, `indexes` = {:indexes} WHERE `name` = 'members'",
      )
      .bind({ fields: tplRow.fields, options: tplRow.options, indexes: indexes })
      .execute();

    app.delete(tpl);

    // 3. The four auth columns, with the same definitions PocketBase gives
    // any freshly created auth collection's table (identical to
    // _superusers'), then the row backfill. tokenKey gets a fresh random
    // value per row (30-60 chars, unique); emailVisibility is true so the
    // board and `lll member list` keep showing emails, as they did when the
    // field was plain text; members that never had an email get a
    // deterministic one synthesized from their unique name.
    for (const col of [
      "`password` TEXT DEFAULT '' NOT NULL",
      "`tokenKey` TEXT DEFAULT '' NOT NULL",
      "`emailVisibility` BOOLEAN DEFAULT FALSE NOT NULL",
      "`verified` BOOLEAN DEFAULT FALSE NOT NULL",
    ]) {
      app
        .db()
        .newQuery("ALTER TABLE `members` ADD COLUMN " + col)
        .execute();
    }

    const used = {};
    const rows = arrayOf(
      new DynamicModel({ id: "", name: "", email: "" }),
    );
    app
      .db()
      .newQuery("SELECT id, name, email FROM `members`")
      .all(rows);
    for (const row of rows) {
      let email = row.email || "";
      if (email === "") {
        const slug = row.name
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-+|-+$/g, "");
        let base = (slug || "member") + "@members.invalid";
        email = base;
        for (let n = 2; used[email]; n++) {
          email = base.slice(0, base.indexOf("@")) + "-" + n + "@members.invalid";
        }
      }
      used[email] = true;
      app
        .db()
        .newQuery(
          "UPDATE `members` SET `tokenKey` = {:tokenKey}, `emailVisibility` = TRUE, `email` = {:email} WHERE `id` = {:id}",
        )
        .bind({
          tokenKey: $security.randomString(50),
          email: email,
          id: row.id,
        })
        .execute();
    }

    // 4. The new UNIQUE indexes, straight from the grafted JSON: whatever
    // PocketBase would have created. The name index already exists and keeps
    // its statement.
    const existing = arrayOf(new DynamicModel({ name: "" }));
    app
      .db()
      .newQuery("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'members'")
      .all(existing);
    const have = {};
    for (const idx of existing) {
      have[idx.name] = true;
    }
    for (const stmt of JSON.parse(indexes)) {
      const name = stmt.split("`")[1];
      if (!have[name]) {
        app.db().newQuery(stmt).execute();
      }
    }

    // The raw UPDATE above bypassed the hooks that keep the app's collection
    // cache in sync; reload it so the auth routes and the record API see the
    // converted collection on this very boot.
    app.reloadCachedCollections();
  },
  (app) => {
    const members = app.findCollectionByNameOrId("members");

    // Idempotent: reversing twice (or a base collection) is a no-op.
    if (members.type !== "auth") {
      return;
    }

    // Back to the plain collection: read the current fields JSON from the
    // row (not from the cached model — goja cannot reliably re-serialize
    // Go field objects), drop the auth system fields, restore the email
    // field as plain text with the same id, so again no column is dropped
    // or renamed.
    const row = new DynamicModel({ fields: "" });
    app
      .db()
      .newQuery("SELECT `fields` FROM `_collections` WHERE `name` = 'members'")
      .one(row);

    const fields = [];
    const authOnly = {
      password: true,
      tokenKey: true,
      emailVisibility: true,
      verified: true,
    };
    for (const field of JSON.parse(row.fields)) {
      if (authOnly[field.name]) {
        continue;
      }
      if (field.name === "email") {
        fields.push({
          autogeneratePattern: "",
          help: "",
          hidden: false,
          id: field.id,
          max: 0,
          min: 0,
          name: "email",
          pattern: "",
          presentable: false,
          primaryKey: false,
          required: false,
          system: false,
          type: "text",
        });
        continue;
      }
      fields.push(field);
    }

    app
      .db()
      .newQuery(
        "UPDATE `_collections` SET `type` = 'base', `fields` = {:fields}, `options` = '{}', `indexes` = {:indexes} WHERE `name` = 'members'",
      )
      .bind({
        fields: JSON.stringify(fields),
        indexes: JSON.stringify([
          "CREATE UNIQUE INDEX `idx_members_name` ON `members` (`name`)",
        ]),
      })
      .execute();

    // The emails this migration synthesized are recognizable and go back to
    // empty; anything a user set since stays theirs.
    app
      .db()
      .newQuery(
        "UPDATE `members` SET `email` = '' WHERE `email` LIKE '%@members.invalid'",
      )
      .execute();

    for (const stmt of [
      "DROP INDEX IF EXISTS `idx_members_email`",
      "DROP INDEX IF EXISTS `idx_tokenKey_" + members.id + "`",
      "ALTER TABLE `members` DROP COLUMN `password`",
      "ALTER TABLE `members` DROP COLUMN `tokenKey`",
      "ALTER TABLE `members` DROP COLUMN `emailVisibility`",
      "ALTER TABLE `members` DROP COLUMN `verified`",
    ]) {
      app.db().newQuery(stmt).execute();
    }

    app.reloadCachedCollections();
  },
);
