// LLL-512: a claim leaves through POST /api/lll/issues/{id}/release, which
// refuses anyone but the holder unless they force it, and records a forced
// release as a comment. With deleteRule at AUTH, any member could DELETE the
// record directly and skip both, so the holder check would be decorative.
// null is superuser only; the hourly expiry sweep deletes through the Go app,
// which collection rules do not apply to.
// Idempotent: it sets a value, so re-applying writes the same rule.
migrate((app) => {
  const claims = app.findCollectionByNameOrId("claims");
  claims.deleteRule = null;
  app.save(claims);
}, (app) => {
  const claims = app.findCollectionByNameOrId("claims");
  claims.deleteRule = '@request.auth.id != ""';
  app.save(claims);
});
