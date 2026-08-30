/// Adds issues.emoji: one author-chosen marker per issue, shown on the board
/// card, the issue page and `lll issue list`. Plain text rather than a relation
/// because the marker is personal, not shared taxonomy. Idempotent.
migrate(
  (app) => {
    const issues = app.findCollectionByNameOrId("issues");
    if (!issues.fields.getByName("emoji")) {
      issues.fields.add(new TextField({ name: "emoji", max: 32 }));
      app.save(issues);
    }
  },
  (app) => {
    const issues = app.findCollectionByNameOrId("issues");
    if (issues.fields.getByName("emoji")) {
      issues.fields.removeByName("emoji");
      app.save(issues);
    }
  },
);
