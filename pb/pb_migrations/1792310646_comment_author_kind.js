/// <reference path="../pb_data/types.d.ts" />

// comments.author_kind (LLL-654): "system" marks a comment the server wrote
// on its own, with no member behind it; empty is a person's or an agent's.
// Today that is only the claim-expiry announcement (gopb/claim_expiry.go
// announceExpiry). It has no author, and tools that treat an authorless
// comment as the human's woke a coordinator for it. A forced-release comment
// is not system: it embeds the releaser's reason and stays the releaser's.
//
// Only the server sets the field: gopb's registerSystemCommentGuard refuses
// it in any create or update request, and refuses edits to a system comment.
//
// Existing rows are NOT backfilled. Before this release a member could post
// a comment with no author, or in another member's name, so no stored row
// proves the server wrote it: an authorless comment that reads like an
// expiry note may be a member's. Historical notes stay unmarked.
migrate(
  (app) => {
    const comments = app.findCollectionByNameOrId("comments");
    if (!comments.fields.getByName("author_kind")) {
      comments.fields.add(new SelectField({ name: "author_kind", maxSelect: 1, values: ["system"] }));
      app.save(comments);
    }
  },
  (app) => {
    const comments = app.findCollectionByNameOrId("comments");
    if (comments.fields.getByName("author_kind")) {
      comments.fields.removeByName("author_kind");
      app.save(comments);
    }
  },
);
