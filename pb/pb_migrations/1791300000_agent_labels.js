/// <reference path="../pb_data/types.d.ts" />

// Agent labels (LLL-521). Several agents often share one member token, and
// then the board cannot tell them apart: a second claim by the same member is
// "already yours", and their comments read as the human's. Each record now
// carries an optional, self-asserted label for the session that wrote it.
//
//   claims.agent    — the holder's session. gopb refuses a claim from the
//                     same member with a different non-empty label.
//   comments.agent  — who among the member's sessions wrote the comment.
//
// Coordination, not auth: any member may write any label.
//
// Named after 1791265600_claim_create_admin.js, the newest migration on main
// when this landed, so fresh and upgraded databases apply it in the same order.
// It writes fields only, never rules: claims rules stay as
// 1789900000_member_teams.js and 1791265600_claim_create_admin.js set them.
//
// The label is rendered into comments and views (markdown), so it has one
// shape: at most 64 of A-Z, a-z, 0-9, '.', '_' and '-'; empty is no label.
// gopb's claim routes and the CLI apply the same rule (agentLabelShape).
const AGENT_LABEL = "^[A-Za-z0-9._-]*$";

migrate(
  (app) => {
    for (const name of ["claims", "comments"]) {
      const collection = app.findCollectionByNameOrId(name);
      if (!collection.fields.getByName("agent")) {
        collection.fields.add(new TextField({ name: "agent", max: 64, pattern: AGENT_LABEL }));
        app.save(collection);
      }
    }
  },
  (app) => {
    for (const name of ["claims", "comments"]) {
      const collection = app.findCollectionByNameOrId(name);
      if (collection.fields.getByName("agent")) {
        collection.fields.removeByName("agent");
        app.save(collection);
      }
    }
  },
);
