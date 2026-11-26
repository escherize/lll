/// <reference path="../pb_data/types.d.ts" />

// LLL-799: team lifecycle belongs to people. 1794639100_workspace_authority.js
// let the legacy all-team read-write grant keep creating, renaming, archiving
// and deleting teams, and the clause it kept admitted any member kind: a bot
// under an all-team owner, and a worker that bot created, could archive or
// rename every team on the server. Invitations were already limited to an
// independent person (gopb/invites.go, mayInvite). This adds the same bound
// to the three team write rules. The workspace Admin alternative is a person
// with no owner already, so it is unchanged.
//
// Additive: no record changes. An all-team bot token keeps its data access
// and loses team create, update and delete.
const rules = require(`${__migrations}/lib/rules.js`);
// "Not a bot" rather than "a person", as mayInvite has it: a member created
// through the records API without a kind stores "", and is a person.
const PERSON = '(@request.auth.kind != "bot" && @request.auth.owner = "")';
const WRITES = ["createRule", "updateRule", "deleteRule"];

migrate(
  (app) => { for (const rule of WRITES) rules.addClause(app, "teams", rule, PERSON); },
  (app) => { for (const rule of WRITES) rules.removeClause(app, "teams", rule, PERSON); },
);
