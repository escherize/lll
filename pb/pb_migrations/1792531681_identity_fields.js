/// <reference path="../pb_data/types.d.ts" />

// Who made or owns a record is the server's word, not the caller's (LLL-681).
//
// - issues.creator and origin: gopb sets the creator from the caller's token
//   on create (provenance.go) and the CLI records where it ran in origin.
//   Nothing changes either afterwards, but the update rule did not say so:
//   any read-write member could re-attribute an issue to another member or
//   rewrite where it came from.
// - members.owner and kind on create: a full member could create a bot owned
//   by someone else, an ownerless bot (which reads as a superuser's), or a
//   person with an owner, which signs in with a password and shows as that
//   owner's. A member's bot is its own; a person has no owner. LLL-616 closed
//   the update path; this closes create.
// - favorites.member and views.member: a full member could star an issue or
//   save a view in another member's name, move one between members, or
//   rewrite one another member owns. A full member may still create and edit
//   one with no member, the workspace's (the board's star and saved views
//   do), and still reads and deletes anyone's.
//
// A superuser bypasses every rule, so it keeps setting these: repairing
// attribution and `lll import dir` both need it, and its credentials already
// own the database. The create rules name record fields, which on create
// hold the submitted values (with defaults for what was left out), so a
// missing `kind` or `member` reads as "" rather than as an unset body key.
const rules = require(`${__migrations}/lib/rules.js`);

const CLAUSES = [
  ["issues", "updateRule", "@request.body.creator:isset = false"],
  ["issues", "updateRule", "@request.body.origin:isset = false"],
  ["members", "createRule", '(kind = "bot" && owner = @request.auth.id) || (kind != "bot" && owner = "")'],
  ["favorites", "createRule", 'member = "" || member = @request.auth.id'],
  ["views", "createRule", 'member = "" || member = @request.auth.id'],
  // Editing another member's favorite or view rewrites what it says under
  // that member's name. A full member still deletes anyone's.
  ["favorites", "updateRule", 'member = "" || member = @request.auth.id'],
  ["views", "updateRule", 'member = "" || member = @request.auth.id'],
];

// The update clause a full member passed (1791700000_bot_owner_scope.js
// keepsOwner), replaced by one nobody but a superuser passes.
const FULL =
  '(@request.auth.scope = "all" && (@request.auth.owner = "" || @request.auth.owner.scope = "all"))' +
  ' && (@request.auth.mode = "rw" && (@request.auth.owner = "" || @request.auth.owner.mode = "rw"))';
const MEMBER_BY_FULL = `(${FULL}) || @request.body.member:isset = false`;
const MEMBER_FIXED = "@request.body.member:isset = false";

migrate(
  (app) => {
    for (const [name, rule, clause] of CLAUSES) rules.addClause(app, name, rule, clause);
    for (const name of ["favorites", "views"]) {
      rules.removeClause(app, name, "updateRule", MEMBER_BY_FULL);
      rules.addClause(app, name, "updateRule", MEMBER_FIXED);
    }
  },
  (app) => {
    for (const [name, rule, clause] of CLAUSES) rules.removeClause(app, name, rule, clause);
    for (const name of ["favorites", "views"]) {
      rules.removeClause(app, name, "updateRule", MEMBER_FIXED);
      rules.addClause(app, name, "updateRule", MEMBER_BY_FULL);
    }
  },
);
