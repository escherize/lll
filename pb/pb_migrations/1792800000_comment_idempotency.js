// Comment retries keep one comment per issue/key. The key is scoped per issue,
// so the same key on another issue makes a separate comment. Unkeyed historical
// and ordinary comments are excluded from the unique index (LLL-700).
migrate((app) => {
  const comments = app.findCollectionByNameOrId("comments");
  comments.fields.add(new TextField({name: "idempotency_key", hidden: true}));
  comments.fields.add(new TextField({name: "idempotency_fingerprint", hidden: true, max: 64}));
  comments.indexes.push("CREATE UNIQUE INDEX idx_comments_idempotency ON comments (issue, idempotency_key) WHERE idempotency_key != ''");
  app.save(comments);
}, (app) => {
  const comments = app.findCollectionByNameOrId("comments");
  comments.indexes = comments.indexes.filter((index) => !index.includes("idx_comments_idempotency"));
  comments.fields.removeByName("idempotency_key");
  comments.fields.removeByName("idempotency_fingerprint");
  app.save(comments);
});
