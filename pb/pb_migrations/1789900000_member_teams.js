/// <reference path="../pb_data/types.d.ts" />

// Team-scoped members: `members.teams` limits an invited member to the teams
// it names. Empty means unscoped, which is every member that existed before
// this migration, so nobody loses access by upgrading.
//
// ADR-1 ("any authenticated member sees everything",
// 1788400000_collection_rules.js) now holds for unscoped members only. A
// scoped member sees, creates, and edits only rows whose team is one of
// its teams. Rows that have no team field of their own follow their issue.
//
// A scoped member cannot widen its own scope. It cannot write
// `members.teams`, create a member it could sign in as, or touch teams.
// Superusers bypass rules, as before, and the custom /api/lll routes apply
// the same test in Go (gopb/team_scope.go).
const AUTH = '@request.auth.id != ""';
const UNSCOPED = "@request.auth.teams:length = 0";
const inTeam = (field) => `${AUTH} && (${UNSCOPED} || @request.auth.teams.id ?= ${field})`;
// An update must not move a row into a team the member cannot see.
const keepsTeam = (field) =>
  `${inTeam(field)} && (${UNSCOPED} || @request.body.${field}:isset = false || @request.auth.teams.id ?= @request.body.${field})`;
// Rows that follow their issue: a scoped member may not re-point them.
const keepsIssue = `${inTeam("issue.team")} && (${UNSCOPED} || @request.body.issue:isset = false)`;
const ONLY_UNSCOPED = `${AUTH} && ${UNSCOPED}`;

// name -> [listRule, viewRule, createRule, updateRule, deleteRule]
const RULES = {
  teams: [inTeam("id"), inTeam("id"), ONLY_UNSCOPED, ONLY_UNSCOPED, ONLY_UNSCOPED],
  projects: [inTeam("team"), inTeam("team"), inTeam("team"), keepsTeam("team"), inTeam("team")],
  labels: [inTeam("team"), inTeam("team"), inTeam("team"), keepsTeam("team"), inTeam("team")],
  issues: [inTeam("team"), inTeam("team"), inTeam("team"), keepsTeam("team"), inTeam("team")],
  docs: [inTeam("team"), inTeam("team"), inTeam("team"), keepsTeam("team"), inTeam("team")],
  webhooks: [inTeam("team"), inTeam("team"), inTeam("team"), keepsTeam("team"), inTeam("team")],
  comments: [inTeam("issue.team"), inTeam("issue.team"), inTeam("issue.team"), keepsIssue, inTeam("issue.team")],
  favorites: [inTeam("issue.team"), inTeam("issue.team"), inTeam("issue.team"), keepsIssue, inTeam("issue.team")],
  claims: [inTeam("issue.team"), inTeam("issue.team"), inTeam("issue.team"), null, inTeam("issue.team")],
};
const NAMES = ["listRule", "viewRule", "createRule", "updateRule", "deleteRule"];

migrate((app) => {
  const members = app.findCollectionByNameOrId("members");
  const teams = app.findCollectionByNameOrId("teams");
  members.fields.add(new RelationField({ name: "teams", collectionId: teams.id, maxSelect: 999, cascadeDelete: false }));
  members.createRule = ONLY_UNSCOPED;
  // A scoped member may edit itself (name, password) but never its scope.
  members.updateRule = `${AUTH} && (${UNSCOPED} || (id = @request.auth.id && @request.body.teams:isset = false))`;
  app.save(members);
  for (const [name, rules] of Object.entries(RULES)) {
    const c = app.findCollectionByNameOrId(name);
    NAMES.forEach((rule, i) => { c[rule] = rules[i]; });
    app.save(c);
  }
}, (app) => {
  for (const name of Object.keys(RULES)) {
    const c = app.findCollectionByNameOrId(name);
    NAMES.forEach((rule) => { c[rule] = AUTH; });
    if (name === "claims") c.updateRule = null;
    app.save(c);
  }
  const members = app.findCollectionByNameOrId("members");
  members.createRule = AUTH;
  members.updateRule = AUTH;
  members.fields.removeByName("teams");
  app.save(members);
});
