/// <reference path="../pb_data/types.d.ts" />

// The members roster (LLL-551, decision option b; doc scoped-access-invites).
//
// Until now members.listRule/viewRule were plain AUTH, so a guest scoped to
// one team listed every person and bot on the server, with emails, scope,
// mode and team ids. Bot names alone name side projects.
//
// A member whose EFFECTIVE access is every team (its own scope "all", and
// its owner's too for an owned bot; 1791700000_bot_owner_scope.js) keeps
// today's view. Anyone narrower sees exactly:
//
//   1. itself;
//   2. every member that shares a team with it: a team in that member's own
//      `teams` that the caller effectively sees (its teams, within its
//      owner's for a bot);
//   3. every person (not a bot) whose scope is "all".
//
// A bot is visible only through (1) or (2): a full-access bot names a side
// project and shares no team. The `teams.id` join is one alias in the whole
// rule, so the owner clause tests the SAME team as the caller clause.
//
// Emails: every member is stored with emailVisibility false from here on
// (gopb/roster.go keeps it false on every save). PocketBase then shows an
// email to the member itself and to superusers, and the gopb enrich hook
// shows them again to a full-access caller. A narrower caller cannot read or
// filter anyone else's email. gopb also drops team ids the caller cannot
// see from a visible member, and refuses relation filters into members.
const AUTH = '@request.auth.id != ""';
const NO_OWNER = '@request.auth.owner = ""';
const ALL = `(@request.auth.scope = "all" && (${NO_OWNER} || @request.auth.owner.scope = "all"))`;
const SHARES =
  `((@request.auth.scope = "all" || teams.id ?= @request.auth.teams.id)` +
  ` && (${NO_OWNER} || @request.auth.owner.scope = "all" || teams.id ?= @request.auth.owner.teams.id))`;
const ROSTER = `${AUTH} && (${ALL} || id = @request.auth.id || (scope = "all" && kind != "bot") || ${SHARES})`;

migrate((app) => {
  const members = app.findCollectionByNameOrId("members");
  members.listRule = ROSTER;
  members.viewRule = ROSTER;
  app.save(members);
  app.db().newQuery("UPDATE `members` SET `emailVisibility` = FALSE").execute();
}, (app) => {
  const members = app.findCollectionByNameOrId("members");
  members.listRule = AUTH;
  members.viewRule = AUTH;
  app.save(members);
  app.db().newQuery("UPDATE `members` SET `emailVisibility` = TRUE").execute();
});
