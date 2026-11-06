/// <reference path="../pb_data/types.d.ts" />

// LLL-177: lightweight work breakdown, independent of projects and blockers.
// An optional parent; deleting it detaches children rather than deleting them.
// Go model hooks enforce same-team acyclic trees for every writer.
migrate(
  (app) => {
    const issues = app.findCollectionByNameOrId("issues");
    if (!issues.fields.getByName("parent")) {
      issues.fields.add(new RelationField({
        name: "parent",
        collectionId: issues.id,
        maxSelect: 1,
        cascadeDelete: false,
      }));
    }
    issues.addIndex("idx_issues_parent", false, "parent", "");
    app.save(issues);
  },
  (app) => {
    const issues = app.findCollectionByNameOrId("issues");
    issues.fields.removeByName("parent");
    issues.removeIndex("idx_issues_parent");
    app.save(issues);
  },
);
