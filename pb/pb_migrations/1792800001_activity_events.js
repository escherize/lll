// Server-owned attribution for live claim events. Existing claims have an
// unknown actor until a new operation; never backfill it from the holder.
migrate((app) => {
  const claims = app.findCollectionByNameOrId("claims");
  const members = app.findCollectionByNameOrId("members");
  claims.fields.add(new RelationField({name: "event_actor", collectionId: members.id, maxSelect: 1, cascadeDelete: false}));
  claims.fields.add(new TextField({name: "event_agent", max: 64}));
  claims.fields.add(new TextField({name: "event_source", max: 16}));
  app.save(claims);
  const webhooks = app.findCollectionByNameOrId("webhooks");
  webhooks.fields.add(new BoolField({name: "activity"}));
  app.save(webhooks);
}, (app) => {
  const webhooks = app.findCollectionByNameOrId("webhooks");
  webhooks.fields.removeByName("activity");
  app.save(webhooks);
  const claims = app.findCollectionByNameOrId("claims");
  for (const name of ["event_actor", "event_agent", "event_source"]) claims.fields.removeByName(name);
  app.save(claims);
});
