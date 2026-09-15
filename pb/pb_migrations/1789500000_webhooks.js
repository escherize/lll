/// <reference path="../pb_data/types.d.ts" />

// Adds `webhooks` (LLL-409): outbound registrations that the server POSTs
// issue events to, borrowed from Vikunja's project webhooks. Scope is a team
// (all of its issues) narrowed optionally to one project; `project` empty
// means team-wide.
//
// Rules are the house AUTH expression on every verb, per the collection-rules
// convention: any authenticated member sees everything, no per-record ACLs.
// A webhook's secret is therefore readable by other members — the same trust
// level as every other registration in lll, and the secret's job is
// authenticating lll TO the receiver, not hiding the url from the team.
//
// Idempotent.
migrate(
  (app) => {
    try {
      app.findCollectionByNameOrId("webhooks");
      return;
    } catch (_) {
      // not created yet
    }
    const teams = app.findCollectionByNameOrId("teams");
    const projects = app.findCollectionByNameOrId("projects");
    const webhooks = new Collection({
      type: "base",
      name: "webhooks",
      listRule: "@request.auth.id != \"\"",
      viewRule: "@request.auth.id != \"\"",
      createRule: "@request.auth.id != \"\"",
      updateRule: "@request.auth.id != \"\"",
      deleteRule: "@request.auth.id != \"\"",
      fields: [
        {
          name: "team",
          type: "relation",
          required: true,
          collectionId: teams.id,
          maxSelect: 1,
          // A deleted team must not leave a registration that still fires.
          cascadeDelete: true,
        },
        {
          name: "project",
          type: "relation",
          required: false,
          collectionId: projects.id,
          maxSelect: 1,
          cascadeDelete: true,
        },
        { name: "url", type: "text", required: true },
        { name: "secret", type: "text" },
        { name: "created", type: "autodate", onCreate: true },
      ],
      indexes: [
        "CREATE INDEX `idx_webhooks_team` ON `webhooks` (`team`)",
      ],
    });
    app.save(webhooks);
  },
  (app) => {
    try {
      app.delete(app.findCollectionByNameOrId("webhooks"));
    } catch (_) {
      // already gone
    }
  },
);
