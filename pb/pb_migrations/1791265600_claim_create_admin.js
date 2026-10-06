// LLL-515: members acquire claims through POST /api/lll/issues/{id}/claim,
// which authenticates the holder and writes assignment in the same transaction.
// Direct collection creates bypass both, so reserve them for superuser fixtures.
migrate((app) => {
  const claims = app.findCollectionByNameOrId("claims");
  claims.createRule = null;
  app.save(claims);
}, (app) => {
  const claims = app.findCollectionByNameOrId("claims");
  claims.createRule = '@request.auth.id != ""';
  app.save(claims);
});
