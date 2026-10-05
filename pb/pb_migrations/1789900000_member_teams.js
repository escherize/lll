/// <reference path="../pb_data/types.d.ts" />

// Team-scoped members (LLL-522, LLL-542; doc scoped-access-invites).
//
// Scope is explicit. `members.scope` is "all" or "teams", and `members.mode`
// is "rw" or "ro". An empty `teams` list never means "every team": a member
// with scope "teams" and no teams sees nothing. Every member that existed
// before this migration becomes "all" + "rw", so nobody loses access by
// upgrading. A member created without a scope or mode gets its creator's,
// filled in by gopb (team_scope.go); only an "all" + "rw" member or a
// superuser may create members, so that default is "all" + "rw".
//
// ADR-1 ("any authenticated member sees everything",
// 1788400000_collection_rules.js) now holds for scope "all" only. A scoped
// member sees only rows whose team is one of its teams. Rows that have no
// team field of their own follow their issue. An "ro" member reads but
// cannot create, edit or delete, except its own favorites.
//
// A scoped member cannot widen its own scope. It cannot write its own
// `teams`, `scope` or `mode`, create a member, or touch teams. Superusers
// bypass rules, as before, and the custom /api/lll routes apply the same test
// in Go (gopb/team_scope.go).
//
// claims.updateRule and claims.deleteRule stay null: claims move only
// through gopb's transactional routes (1789800000_claim_delete_admin.js,
// LLL-512).
const AUTH = '@request.auth.id != ""';
const ALL = '@request.auth.scope = "all"';
const RW = '@request.auth.mode = "rw"';
const read = (field) => `${AUTH} && (${ALL} || @request.auth.teams.id ?= ${field})`;
const write = (field) => `${read(field)} && ${RW}`;
// An update must not move a row into a team the member cannot see.
const keepsTeam = (field) =>
  `${write(field)} && (${ALL} || @request.body.${field}:isset = false || @request.auth.teams.id ?= @request.body.${field})`;
// Rows that follow their issue: a scoped member may not re-point them.
const keepsIssue = (rule) => `${rule} && (${ALL} || @request.body.issue:isset = false)`;
const ONLY_ALL = `${AUTH} && ${ALL} && ${RW}`;
// Favorites are the viewer's own bookmarks, so a read-only member keeps them.
const fav = read("issue.team");

// name -> [listRule, viewRule, createRule, updateRule, deleteRule]
const RULES = {
  teams: [read("id"), read("id"), ONLY_ALL, ONLY_ALL, ONLY_ALL],
  projects: [read("team"), read("team"), write("team"), keepsTeam("team"), write("team")],
  labels: [read("team"), read("team"), write("team"), keepsTeam("team"), write("team")],
  issues: [read("team"), read("team"), write("team"), keepsTeam("team"), write("team")],
  docs: [read("team"), read("team"), write("team"), keepsTeam("team"), write("team")],
  webhooks: [read("team"), read("team"), write("team"), keepsTeam("team"), write("team")],
  comments: [read("issue.team"), read("issue.team"), write("issue.team"), keepsIssue(write("issue.team")), write("issue.team")],
  favorites: [fav, fav, fav, keepsIssue(fav), fav],
  claims: [read("issue.team"), read("issue.team"), write("issue.team"), null, null],
};
const NAMES = ["listRule", "viewRule", "createRule", "updateRule", "deleteRule"];

migrate((app) => {
  const members = app.findCollectionByNameOrId("members");
  const teams = app.findCollectionByNameOrId("teams");
  members.fields.add(new RelationField({ name: "teams", collectionId: teams.id, maxSelect: 999, cascadeDelete: false }));
  members.fields.add(new SelectField({ name: "scope", values: ["all", "teams"], maxSelect: 1, required: true }));
  members.fields.add(new SelectField({ name: "mode", values: ["rw", "ro"], maxSelect: 1, required: true }));
  members.createRule = ONLY_ALL;
  // A member may edit itself (name, password) but never its own access.
  members.updateRule = `${AUTH} && ((${ALL} && ${RW}) || (id = @request.auth.id && @request.body.teams:isset = false && @request.body.scope:isset = false && @request.body.mode:isset = false))`;
  app.save(members);
  app.db().newQuery("UPDATE members SET scope = 'all', mode = 'rw'").execute();
  for (const [name, rules] of Object.entries(RULES)) {
    const c = app.findCollectionByNameOrId(name);
    NAMES.forEach((rule, i) => { c[rule] = rules[i]; });
    app.save(c);
  }
}, (app) => {
  for (const name of Object.keys(RULES)) {
    const c = app.findCollectionByNameOrId(name);
    NAMES.forEach((rule) => { c[rule] = AUTH; });
    if (name === "claims") {
      c.updateRule = null;
      c.deleteRule = null;
    }
    app.save(c);
  }
  const members = app.findCollectionByNameOrId("members");
  members.createRule = AUTH;
  members.updateRule = AUTH;
  for (const f of ["teams", "scope", "mode"]) members.fields.removeByName(f);
  app.save(members);
});
