/// <reference path="../pb_data/types.d.ts" />

// comments.author_kind (LLL-654): "system" marks a comment the server wrote,
// empty is a person's or an agent's. Two comments are server-written: the
// forced-release record (gopb/claims.go recordForcedRelease) and the claim
// expiry announcement (gopb/claim_expiry.go announceExpiry). The expiry one
// has no author, and tools that treat an authorless comment as the human's
// woke a coordinator for it.
//
// Only the server sets the field: gopb's registerSystemCommentGuard refuses
// it in any create or update request, and refuses edits to a system comment.
//
// Existing rows are backfilled by the bodies those two writers produce.
migrate(
  (app) => {
    const comments = app.findCollectionByNameOrId("comments");
    if (!comments.fields.getByName("author_kind")) {
      comments.fields.add(new SelectField({ name: "author_kind", maxSelect: 1, values: ["system"] }));
      app.save(comments);
    }
    app.db().newQuery(
      "UPDATE comments SET author_kind = 'system' WHERE " +
        "(author = '' AND body LIKE 'Claim released automatically: %') OR " +
        "body LIKE '% force-released %''s claim.%'",
    ).execute();
  },
  (app) => {
    const comments = app.findCollectionByNameOrId("comments");
    if (comments.fields.getByName("author_kind")) {
      comments.fields.removeByName("author_kind");
      app.save(comments);
    }
  },
);
