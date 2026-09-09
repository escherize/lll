/// <reference path="../pb_data/types.d.ts" />

// LLL-175: dependencies. `blocked_by` is a self-relation on issues: the
// issues that must be done before this one can start. It is the field
// behind 'lll issue block KEY --by OTHER', 'lll issue unblock', the
// "Blocked by:" line in 'issue view', and 'issue list --ready', which lists
// the open issues whose blockers are all done. Ordering used to live only
// as prose ("89 needs 167 first") that no tool could read.
//
// cascadeDelete stays false: deleting a blocker frees the blocked issue
// rather than deleting it. Idempotent and reversible.
migrate(
  (app) => {
    const issues = app.findCollectionByNameOrId("issues");
    if (!issues.fields.getByName("blocked_by")) {
      issues.fields.add(new RelationField({
        name: "blocked_by",
        collectionId: issues.id,
        maxSelect: 999,
        cascadeDelete: false,
      }));
      app.save(issues);
    }
  },
  (app) => {
    const issues = app.findCollectionByNameOrId("issues");
    if (issues.fields.getByName("blocked_by")) {
      issues.fields.removeByName("blocked_by");
      app.save(issues);
    }
  },
);
