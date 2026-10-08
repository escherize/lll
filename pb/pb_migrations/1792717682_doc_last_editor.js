/// <reference path="../pb_data/types.d.ts" />

// Docs record who last edited them (LLL-682 part 2).
//
// Docs stay shared team pages: any writer on the team may edit any doc, and
// the author stays the member who created it. Until now an edit left no
// trace, so a decision could change under its author's name. last_editor
// names the member whose token made the latest write.
//
//   docs.last_editor - relation to members, cascadeDelete false like
//                      docs.author: deleting a member must not delete docs.
//
// The server sets it from the caller (gopb/provenance.go): on create it is
// the author, on every member update it is the caller. A member may not send
// `last_editor` at all, on create or update, so nobody can sign an edit with
// another member's name. A superuser bypasses the rules and has no member
// identity: its create still gets last_editor = author, and its update keeps
// the stored editor unless it names one, as imports and repairs need.
//
// Backfill: an existing doc's last editor is its author. Nothing recorded
// later edits, so "edited by" appears only after the next edit. An authorless
// doc stays without an editor.
const rules = require(`${__migrations}/lib/rules.js`);

const NO_LAST_EDITOR = "@request.body.last_editor:isset = false";

migrate(
  (app) => {
    const docs = app.findCollectionByNameOrId("docs");
    const members = app.findCollectionByNameOrId("members");
    docs.fields.add(new RelationField({ name: "last_editor", collectionId: members.id, maxSelect: 1, cascadeDelete: false }));
    app.save(docs);
    app.db().newQuery("UPDATE `docs` SET `last_editor` = `author` WHERE `author` != '' AND `last_editor` = ''").execute();
    rules.addClause(app, "docs", "createRule", NO_LAST_EDITOR);
    rules.addClause(app, "docs", "updateRule", NO_LAST_EDITOR);
  },
  (app) => {
    rules.removeClause(app, "docs", "createRule", NO_LAST_EDITOR);
    rules.removeClause(app, "docs", "updateRule", NO_LAST_EDITOR);
    const docs = app.findCollectionByNameOrId("docs");
    docs.fields.removeByName("last_editor");
    app.save(docs);
  },
);
