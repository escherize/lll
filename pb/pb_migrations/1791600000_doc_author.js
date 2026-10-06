/// <reference path="../pb_data/types.d.ts" />

// Docs record who wrote them (LLL-618), so a doc can show its author's kind
// and a bot's owner the way comments do (LLL-610).
//
//   docs.author — relation to members, cascadeDelete false like
//                 issues.creator: deleting a member must not delete its
//                 decisions and findings.
//
// The author is the authenticated caller, never what the client says. gopb
// sets it on create from the member token (provenance.go), which covers every
// write path at once: `lll doc create`, `lll finding create`, the board and
// the raw API. A superuser has no member identity, so its writes stay
// authorless unless it names an author explicitly; superusers bypass rules.
//
// A member may not send `author` at all, on create or update: on create the
// server fills it, and after create it is immutable. Without the update
// clause any writer on the team could re-attribute a decision to someone
// else. Same shape as members owner/kind (1791500000_member_owner_kind_admin.js).
//
// Existing docs keep an empty author. Nothing records who wrote them, and a
// guess would be a lie the board repeats.
//
// The rules are otherwise exactly 1789900000_member_teams.js's team-scoped
// docs rules; this adds one clause and widens nothing.
const AUTH = '@request.auth.id != ""';
const ALL = '@request.auth.scope = "all"';
const RW = '@request.auth.mode = "rw"';
const read = (field) => `${AUTH} && (${ALL} || @request.auth.teams.id ?= ${field})`;
const write = (field) => `${read(field)} && ${RW}`;
const keepsTeam = (field) =>
  `${write(field)} && (${ALL} || @request.body.${field}:isset = false || @request.auth.teams.id ?= @request.body.${field})`;
const NO_AUTHOR = "@request.body.author:isset = false";

migrate(
  (app) => {
    const docs = app.findCollectionByNameOrId("docs");
    const members = app.findCollectionByNameOrId("members");
    if (!docs.fields.getByName("author")) {
      docs.fields.add(new RelationField({ name: "author", collectionId: members.id, maxSelect: 1, cascadeDelete: false }));
    }
    docs.createRule = `${write("team")} && ${NO_AUTHOR}`;
    docs.updateRule = `${keepsTeam("team")} && ${NO_AUTHOR}`;
    app.save(docs);
  },
  (app) => {
    const docs = app.findCollectionByNameOrId("docs");
    docs.createRule = write("team");
    docs.updateRule = keepsTeam("team");
    docs.fields.removeByName("author");
    app.save(docs);
  },
);
