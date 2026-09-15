/// <reference path="../pb_data/types.d.ts" />

// Bot members (LLL-407, after Vikunja's bot users): automation identities
// alongside the humans they serve, not a second account model. Two fields on
// the members auth collection:
//
//   kind  — select, person | bot. A bot is token-only: the gopb member guards
//           refuse it password auth, and the reserved bot- name prefix is
//           enforced there on every members write, where no client can skip
//           it. PocketBase selects have no schema-level default, so this
//           migration backfills every existing member to person and the CLI
//           sets kind explicitly on every create.
//
//   owner — relation to the human member who created the bot. Attribution,
//           not lifecycle: cascadeDelete stays false because member deletion
//           is a deliberate superuser act (LLL-341), and a cascade here would
//           let one member delete silently delete auth records as a side
//           effect. Removing an owner blanks the field; the bot survives.
//
// LLL-374 owns the wider kind taxonomy (agent, run, ...); this migration
// ships only the two values this issue needs, and adding a value later is a
// one-line select change.
migrate((app) => {
  const members = app.findCollectionByNameOrId("members");
  members.fields.add(new SelectField({ name: "kind", maxSelect: 1, values: ["person", "bot"] }));
  members.fields.add(new RelationField({ name: "owner", collectionId: members.id, maxSelect: 1, cascadeDelete: false }));
  app.save(members);
  app
    .db()
    .newQuery("UPDATE `members` SET `kind` = 'person' WHERE `kind` = '' OR `kind` IS NULL")
    .execute();
}, (app) => {
  const members = app.findCollectionByNameOrId("members");
  for (const name of ["kind", "owner"]) members.fields.removeByName(name);
  app.save(members);
});
