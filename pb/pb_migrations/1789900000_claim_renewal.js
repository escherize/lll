/// <reference path="../pb_data/types.d.ts" />

// LLL-535: a claim can be renewed. The expiry sweep (LLL-183) aged a claim by
// `created`, which nothing can move, so a hold that legitimately outlived a day
// - a parent issue waiting on its children - lost its claim with no way to say
// it was still alive.
//
// `updated` is an autodate on create and update. Claims are never edited
// otherwise (updateRule is null and gopb writes them only to create, renew or
// delete), so `updated` is exactly when the holder last vouched for the hold,
// and the sweep ages by it. Existing claims are backfilled from `created`, so
// the first sweep after this migration expires exactly what it would have
// before it.
//
// Idempotent: the field is added only when missing, and the backfill touches
// only rows without a value.
migrate((app) => {
  const claims = app.findCollectionByNameOrId("claims");
  if (!claims.fields.getByName("updated")) {
    claims.fields.add(new AutodateField({ name: "updated", onCreate: true, onUpdate: true }));
    app.save(claims);
  }
  app
    .db()
    .newQuery("UPDATE `claims` SET `updated` = `created` WHERE `updated` = '' OR `updated` IS NULL")
    .execute();
}, (app) => {
  const claims = app.findCollectionByNameOrId("claims");
  claims.fields.removeByName("updated");
  app.save(claims);
});
