/// <reference path="../pb_data/types.d.ts" />

// Adds `favorites`: the starred issues pinned into the app shell's rail.
//
// A collection rather than localStorage because the rail is server-rendered
// and Datastar v1 has no client-side loop — a stored array cannot become <a>
// elements.
//
// `member` is present but optional, and auth is deferred (TASK-32), so every
// row written today has member="" and means "starred for the whole
// workspace". The field is here now so per-user favorites are additive: a
// later migration only has to backfill and mark it required. The unique index
// is on (issue, member), so it already reads as "one star per issue per
// member" with "" as the workspace member.
//
// Idempotent.
migrate(
  (app) => {
    try {
      app.findCollectionByNameOrId("favorites");
      return;
    } catch (_) {
      // not created yet
    }
    const issues = app.findCollectionByNameOrId("issues");
    const members = app.findCollectionByNameOrId("members");
    const favorites = new Collection({
      type: "base",
      name: "favorites",
      listRule: "",
      viewRule: "",
      createRule: "",
      updateRule: "",
      deleteRule: "",
      fields: [
        {
          name: "issue",
          type: "relation",
          required: true,
          collectionId: issues.id,
          maxSelect: 1,
          // A deleted issue must not leave a dead row in the rail.
          cascadeDelete: true,
        },
        // Empty until auth lands: "" is the workspace, not a person.
        {
          name: "member",
          type: "relation",
          collectionId: members.id,
          maxSelect: 1,
          cascadeDelete: true,
        },
        { name: "created", type: "autodate", onCreate: true },
        { name: "updated", type: "autodate", onCreate: true, onUpdate: true },
      ],
      indexes: [
        "CREATE UNIQUE INDEX `idx_favorites_issue_member` ON `favorites` (`issue`, `member`)",
      ],
    });
    app.save(favorites);
  },
  (app) => {
    try {
      app.delete(app.findCollectionByNameOrId("favorites"));
    } catch (_) {
      // already gone
    }
  },
);
