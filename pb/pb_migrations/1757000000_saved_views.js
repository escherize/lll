/// <reference path="../pb_data/types.d.ts" />

// Adds `views`: saved board views (TASK-94, half two). A view is a NAME plus
// a QUERY STRING, nothing more — once the board's filters and hidden lanes
// live in the URL, "save this view" stores the URL and the rail navigates
// back to it.
//
// Workspace-wide like favorites (auth is deferred, TASK-32): every row
// written today has member="" and a view belongs to everyone here. The
// `member` relation is present but optional so per-user views are additive:
// a later migration only has to backfill and mark it required. The unique
// index is on (name, member), so it already reads as "one name per member"
// with "" as the workspace member.
//
// Idempotent, and shaped after 1756718431_add_favorites.js.
migrate(
  (app) => {
    try {
      app.findCollectionByNameOrId("views");
      return;
    } catch (_) {
      // not created yet
    }
    const members = app.findCollectionByNameOrId("members");
    const views = new Collection({
      type: "base",
      name: "views",
      listRule: "",
      viewRule: "",
      createRule: "",
      updateRule: "",
      deleteRule: "",
      fields: [
        { name: "name", type: "text", required: true, min: 1, max: 80 },
        // The query string the view stands for, without the leading "?" —
        // "" is a valid view: the board with nothing filtered.
        { name: "query", type: "text", required: true, max: 500 },
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
        "CREATE UNIQUE INDEX `idx_views_name_member` ON `views` (`name`, `member`)",
      ],
    });
    app.save(views);
  },
  (app) => {
    try {
      app.delete(app.findCollectionByNameOrId("views"));
    } catch (_) {
      // already gone
    }
  },
);
