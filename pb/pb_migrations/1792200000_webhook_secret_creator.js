/// <reference path="../pb_data/types.d.ts" />

// Webhook secrets are write-only, and deliveries follow their creator's
// access (LLL-661).
//
// `secret` becomes a hidden field. PocketBase leaves a hidden field out of
// every API response, realtime event and expansion for a member, and refuses
// it in a member's filter or sort, so a team's read-only guest can no longer
// read the secret that lets a receiver trust a delivery. gopb
// (webhooks.go) also hides it from superuser responses, and reads it from
// the create body itself, because PocketBase drops hidden fields from a
// member's request body.
//
// `secret_set` is what a reader may know instead: gopb derives it from
// `secret` on every save. Existing rows are backfilled here.
//
// `creator` is the member that registered the webhook, set by gopb from the
// caller on create; a body value is ignored. Delivery skips a webhook whose
// creator no longer reads its team. Rows that predate this migration, and
// rows a superuser creates, have no creator and deliver while their team
// exists. Deleting the creator deletes its webhooks: an empty creator would
// otherwise read as one of those rows and keep delivering.
//
// `updateRule` becomes superuser-only. A member who could PATCH another
// member's webhook could point its url at a listener of its own and read the
// secret from the delivery header, or keep the original creator's access
// for a url it chose. Change a webhook by removing and adding it.
migrate(
  (app) => {
    const webhooks = app.findCollectionByNameOrId("webhooks");
    const members = app.findCollectionByNameOrId("members");
    webhooks.fields.getByName("secret").hidden = true;
    webhooks.fields.add(new BoolField({ name: "secret_set" }));
    webhooks.fields.add(new RelationField({
      name: "creator",
      collectionId: members.id,
      maxSelect: 1,
      cascadeDelete: true,
    }));
    webhooks.updateRule = null;
    app.save(webhooks);
    app.db().newQuery("UPDATE webhooks SET secret_set = (secret != '')").execute();
  },
  (app) => {
    const webhooks = app.findCollectionByNameOrId("webhooks");
    webhooks.fields.getByName("secret").hidden = false;
    webhooks.fields.removeByName("secret_set");
    webhooks.fields.removeByName("creator");
    // The rule 1791700000_bot_owner_scope.js wrote: keepsTeam("team").
    webhooks.updateRule = webhooks.deleteRule +
      ' && (@request.body.team:isset = false || ((@request.auth.scope = "all" || @request.auth.teams.id ?= @request.body.team)' +
      ' && (@request.auth.owner = "" || @request.auth.owner.scope = "all" || @request.auth.owner.teams.id ?= @request.body.team)))';
    app.save(webhooks);
  },
);
