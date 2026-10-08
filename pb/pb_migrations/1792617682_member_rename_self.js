/// <reference path="../pb_data/types.d.ts" />

// Only a superuser or the member itself renames a member (LLL-682).
//
// members.updateRule let any full member PATCH another member's name. A full
// member could rename someone, take the freed name, and then read as them
// in every attribution that shows a name. Now a person renames only itself.
// A bot is renamed by a superuser only, not by its owner and not with its
// own token (which its owner holds): a bot is renamed by recreating it.
//
// A body that repeats the current name is not a rename, so a save that
// resends the name with other fields still passes. A superuser bypasses
// every rule. The existing clauses stay, and registerMemberNameGuard
// (gopb/invites.go) still checks a self-rename against the case-folded
// unique name under its lock.
const rules = require(`${__migrations}/lib/rules.js`);

const RENAME_SELF =
  '@request.body.name:isset = false || @request.body.name = name || (id = @request.auth.id && kind != "bot")';

migrate(
  (app) => rules.addClause(app, "members", "updateRule", RENAME_SELF),
  (app) => rules.removeClause(app, "members", "updateRule", RENAME_SELF),
);
