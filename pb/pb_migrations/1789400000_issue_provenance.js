// Creation context stays empty for historical records; do not guess it.
migrate((app) => {
  const issues = app.findCollectionByNameOrId("issues");
  const members = app.findCollectionByNameOrId("members");
  issues.fields.add(new RelationField({name: "creator", collectionId: members.id, maxSelect: 1, cascadeDelete: false}));
  issues.fields.add(new JSONField({name: "origin", maxSize: 16384}));
  issues.fields.add(new TextField({name: "refs", max: 2000}));
  app.save(issues);
}, (app) => {
  const issues = app.findCollectionByNameOrId("issues");
  for (const name of ["creator", "origin", "refs"]) issues.fields.removeByName(name);
  app.save(issues);
});
