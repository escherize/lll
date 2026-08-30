/// <reference path="../pb_data/types.d.ts" />

// Adds `docs` (TASK-86): long-form writing the board can link to — wiki
// pages, findings, decisions, PRDs. ONE collection, `kind` distinguishes
// them; splitting wiki/finding/decision into three collections would
// triplicate every verb and filter for a field's worth of difference.
// `issues` relates a doc to issues (maxSelect many), so the back-reference
// ("every doc linked to this issue") is one `issues.id ?= 'x'` filter — no
// join table, no polymorphism. With cascadeDelete false, deleting an issue
// only unsets its id from docs.issues (core/record_model.go
// deleteRefRecords); the doc itself must survive.
//
// Idempotent, shaped after 1756718431_add_favorites.js.
migrate(
  (app) => {
    try {
      app.findCollectionByNameOrId("docs");
      return;
    } catch (_) {
      // not created yet
    }
    const issues = app.findCollectionByNameOrId("issues");
    const docs = new Collection({
      type: "base",
      name: "docs",
      listRule: "",
      viewRule: "",
      createRule: "",
      updateRule: "",
      deleteRule: "",
      fields: [
        { name: "slug", type: "text", required: true, min: 1, max: 80 },
        { name: "title", type: "text", required: true, min: 1, max: 300 },
        // wiki | finding | decision | prd; "" is allowed so a kind can be
        // minted later without a backfill.
        { name: "kind", type: "text", max: 40 },
        // Long-form prose: raised past PocketBase's default 5000 like
        // issues.description (1756612347_raise_text_limits.js).
        { name: "body", type: "text", max: 100000 },
        {
          name: "issues",
          type: "relation",
          collectionId: issues.id,
          maxSelect: 99,
          cascadeDelete: false,
        },
        { name: "created", type: "autodate", onCreate: true },
        { name: "updated", type: "autodate", onCreate: true, onUpdate: true },
      ],
      indexes: [
        "CREATE UNIQUE INDEX `idx_docs_slug` ON `docs` (`slug`)",
      ],
    });
    app.save(docs);
  },
  (app) => {
    try {
      app.delete(app.findCollectionByNameOrId("docs"));
    } catch (_) {
      // already gone
    }
  },
);
