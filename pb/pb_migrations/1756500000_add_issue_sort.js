/// Adds issues.sort for data dirs created before the field joined the init
/// migration (init covers fresh dirs; this upgrades existing ones). Idempotent.
migrate(
  (app) => {
    const issues = app.findCollectionByNameOrId("issues");
    if (!issues.fields.getByName("sort")) {
      issues.fields.add(
        new NumberField({ name: "sort" }),
      );
      app.save(issues);
    }
  },
  (app) => {
    const issues = app.findCollectionByNameOrId("issues");
    if (issues.fields.getByName("sort")) {
      issues.fields.removeByName("sort");
      app.save(issues);
    }
  },
);
