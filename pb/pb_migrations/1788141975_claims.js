/// <reference path="../pb_data/types.d.ts" />

// Adds `claims` (TASK-175): one exclusive hold on an issue, so
// claim-before-work stops being a convention everyone has to remember.
//
// The UNIQUE index on `issue` is the whole mechanism. Claiming is an INSERT,
// not a read-then-write, so two agents racing on the same issue both send the
// row and SQLite admits exactly one -- the loser is told, which is the part
// `lll issue update --assignee` (a last-write-wins PATCH) could never do.
// Same trick the issues collection already leans on: `issueDefaults` in
// gopb.go only assigns a number when the client sent none, precisely so the
// unique (team, number) index rejects a forged duplicate.
//
// `created` is the claim's age, which is what a later expiry sweep needs
// (follow-on, not built here): a claim older than N hours is stale.
//
// updateRule is null (superuser only) while every other rule is "" (anyone).
// A claim is created or deleted, never edited -- lll issues no PATCH here,
// and leaving it open would hand a loser a second door: PATCH the winning
// row's `member` to itself, which an index on `issue` alone would not stop.
//
// Idempotent.
migrate(
  (app) => {
    try {
      app.findCollectionByNameOrId("claims");
      return;
    } catch (_) {
      // not created yet
    }
    const issues = app.findCollectionByNameOrId("issues");
    const members = app.findCollectionByNameOrId("members");
    const claims = new Collection({
      type: "base",
      name: "claims",
      listRule: "",
      viewRule: "",
      createRule: "",
      updateRule: null,
      deleteRule: "",
      fields: [
        {
          name: "issue",
          type: "relation",
          required: true,
          collectionId: issues.id,
          maxSelect: 1,
          // A deleted issue must not leave an unreleasable claim behind.
          cascadeDelete: true,
        },
        // Required, unlike favorites.member: an unheld claim is not a claim.
        {
          name: "member",
          type: "relation",
          required: true,
          collectionId: members.id,
          maxSelect: 1,
          // A deleted member releases what they held.
          cascadeDelete: true,
        },
        { name: "created", type: "autodate", onCreate: true },
      ],
      indexes: [
        "CREATE UNIQUE INDEX `idx_claims_issue` ON `claims` (`issue`)",
      ],
    });
    app.save(claims);
  },
  (app) => {
    try {
      app.delete(app.findCollectionByNameOrId("claims"));
    } catch (_) {
      // already gone
    }
  },
);
