/// <reference path="../pb_data/types.d.ts" />

// LLL-770: the latest retained issue/comment/claim activity, materialized for
// list readers. Go audit hooks maintain it without changing issue.updated.
// Older deleted activity without an audit row cannot be reconstructed.
migrate((app) => {
  const issues = app.findCollectionByNameOrId("issues");
  issues.fields.add(new DateField({ name: "last_activity" }));
  app.save(issues);
  app.db().newQuery(`
    UPDATE issues SET last_activity = MAX(
      COALESCE(created, ''), COALESCE(updated, ''),
      COALESCE((SELECT MAX(MAX(created, updated)) FROM comments WHERE issue = issues.id), ''),
      COALESCE((SELECT MAX(MAX(created, updated)) FROM claims WHERE issue = issues.id), ''),
      COALESCE((SELECT MAX(created) FROM audit_events WHERE issue = issues.id), '')
    )
  `).execute();
}, (app) => {
  const issues = app.findCollectionByNameOrId("issues");
  issues.fields.removeByName("last_activity");
  app.save(issues);
});
