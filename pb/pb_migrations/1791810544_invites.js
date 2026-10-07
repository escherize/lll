/// <reference path="../pb_data/types.d.ts" />

// Single-use invite links (LLL-544; doc scoped-access-invites, slice 3).
//
// An invite names teams and a mode. Redeeming it at <board>/join/<code>
// creates a person member with exactly those grants. gopb owns both ends
// (gopb/invites.go): minting checks the creator holds what it grants, and
// redemption is one transaction that kills the code and creates the member.
//
// Every rule is null (superuser only). No member or bot token may list, view,
// filter, expand or subscribe to an invite, and nothing writes one except
// gopb. Every field is also hidden, so a filter from another collection
// cannot probe an invite through a back-relation.
//
// Only a SHA-256 of the code is stored. The code itself is shown once, to
// the creator; a copy of the database cannot redeem anything.
//
//   code_hash   hex SHA-256 of the code; unique, the lookup key
//   teams       the teams the member gets (never empty; checked in gopb,
//               not `required`, which would block deleting a team)
//   mode        "ro" or "rw"
//   expires     7 days after creation (settled, Bryan 2026-10-05)
//   creator     the member that minted it; empty for a superuser
//   superuser   true when a superuser minted it
//   redeemed    when it was redeemed; set means dead. A date, not the
//               relation below: deleting the member clears redeemed_by,
//               and a cleared relation must not revive the code.
//   redeemed_by the member the redemption created
migrate(
  (app) => {
    const teams = app.findCollectionByNameOrId("teams");
    const members = app.findCollectionByNameOrId("members");
    const invites = new Collection({
      type: "base",
      name: "invites",
      listRule: null,
      viewRule: null,
      createRule: null,
      updateRule: null,
      deleteRule: null,
      fields: [
        { name: "code_hash", type: "text", required: true, hidden: true, min: 64, max: 64 },
        { name: "teams", type: "relation", collectionId: teams.id, maxSelect: 999, cascadeDelete: false, hidden: true },
        { name: "mode", type: "select", values: ["ro", "rw"], maxSelect: 1, required: true, hidden: true },
        { name: "expires", type: "date", required: true, hidden: true },
        { name: "creator", type: "relation", collectionId: members.id, maxSelect: 1, cascadeDelete: false, hidden: true },
        { name: "superuser", type: "bool", hidden: true },
        { name: "redeemed", type: "date", hidden: true },
        { name: "redeemed_by", type: "relation", collectionId: members.id, maxSelect: 1, cascadeDelete: false, hidden: true },
        { name: "created", type: "autodate", onCreate: true, hidden: true },
      ],
      indexes: ["CREATE UNIQUE INDEX `idx_invites_code_hash` ON `invites` (`code_hash`)"],
    });
    app.save(invites);
  },
  (app) => {
    app.delete(app.findCollectionByNameOrId("invites"));
  },
);
