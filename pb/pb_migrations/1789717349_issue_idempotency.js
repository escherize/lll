// Creation retries keep one issue per team/key. Unkeyed historical and
// ordinary creates are excluded from the unique index (LLL-438).
migrate((app) => {
  const issues = app.findCollectionByNameOrId("issues");
  issues.fields.add(new TextField({name: "idempotency_key", hidden: true}));
  issues.fields.add(new TextField({name: "idempotency_fingerprint", hidden: true, max: 64}));
  issues.indexes.push("CREATE UNIQUE INDEX idx_issues_idempotency ON issues (team, idempotency_key) WHERE idempotency_key != ''");
  app.save(issues);
}, (app) => {
  const issues = app.findCollectionByNameOrId("issues");
  issues.indexes = issues.indexes.filter((index) => !index.includes("idx_issues_idempotency"));
  issues.fields.removeByName("idempotency_key");
  issues.fields.removeByName("idempotency_fingerprint");
  app.save(issues);
});
