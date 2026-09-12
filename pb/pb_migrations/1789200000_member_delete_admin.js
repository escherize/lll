// LLL-341: account deletion requires the same administrative authority
// through direct API clients as through the CLI and web confirmation.
migrate((app) => {
  const members = app.findCollectionByNameOrId("members");
  members.deleteRule = null;
  app.save(members);
}, (app) => {
  const members = app.findCollectionByNameOrId("members");
  members.deleteRule = '@request.auth.id != ""';
  app.save(members);
});
