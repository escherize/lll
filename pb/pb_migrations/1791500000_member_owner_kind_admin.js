/// <reference path="../pb_data/types.d.ts" />

// A member's `owner` and `kind` change only with superuser credentials
// (LLL-616). Both are set when the member is created (`lll bot` records the
// owner; kind is "person" or "bot") and nothing in lll changes them after.
//
// `owner` gates bot token rotation (gopb/members.go: the owner, or a
// superuser). Under 1789900000_member_teams.js a full read-write member could
// PATCH any member and anyone could PATCH themselves, so a member could make
// itself the owner of any bot, rotate it, receive a working token, and cut
// off the real holder. A bot could also re-own itself. `kind` decides who
// may sign in with a password and how authorship is shown, so it gets the
// same rule.
//
// The rule otherwise matches 1789900000_member_teams.js: a full member edits
// anyone, everyone else edits only itself, and nobody but a superuser
// changes access (teams, scope, mode). Superusers bypass rules.
const AUTH = '@request.auth.id != ""';
const ALL = '@request.auth.scope = "all"';
const RW = '@request.auth.mode = "rw"';
const ADMIN_ONLY_FIELDS = ["teams", "scope", "mode", "owner", "kind"]
  .map((f) => `@request.body.${f}:isset = false`)
  .join(" && ");
const PREVIOUS_ACCESS_FIELDS = ["teams", "scope", "mode"]
  .map((f) => `@request.body.${f}:isset = false`)
  .join(" && ");

migrate((app) => {
  const members = app.findCollectionByNameOrId("members");
  members.updateRule = `${AUTH} && ${ADMIN_ONLY_FIELDS} && ((${ALL} && ${RW}) || id = @request.auth.id)`;
  app.save(members);
}, (app) => {
  const members = app.findCollectionByNameOrId("members");
  members.updateRule = `${AUTH} && ${PREVIOUS_ACCESS_FIELDS} && ((${ALL} && ${RW}) || id = @request.auth.id)`;
  app.save(members);
});
