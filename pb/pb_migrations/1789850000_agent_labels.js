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
migrate(
  (app) => {
    for (const name of ["claims", "comments"]) {
      const collection = app.findCollectionByNameOrId(name);
      if (!collection.fields.getByName("agent")) {
        collection.fields.add(new TextField({ name: "agent", max: 100 }));
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
