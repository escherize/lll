// LLL-35: native issue files; private like the issue record itself.
migrate((app) => {
  const issues = app.findCollectionByNameOrId("issues");
  issues.fields.add(new FileField({
    name: "attachments", maxSelect: 20, maxSize: 20 * 1024 * 1024,
    protected: true,
  }));
  app.save(issues);
}, (app) => {
  const issues = app.findCollectionByNameOrId("issues");
  issues.fields.removeByName("attachments");
  app.save(issues);
});
