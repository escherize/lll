/// <reference path="../pb_data/types.d.ts" />

// Bots inherit their owner's access (LLL-543; doc scoped-access-invites,
// "a bot never exceeds its owner").
//
// A bot with an `owner` holds the intersection of its own access (scope,
// teams, mode) and its owner's current access. The rules read the owner
// through the relation on every request, so narrowing the owner narrows its
// bots at once, with no change to the bot records, and a read-only owner
// makes its bots read-only. A member with no owner (every person, and bots a
// superuser minted) keeps exactly its own access, as before.
//
// Only one hop is resolved: gopb refuses ownership chains (team_scope.go
// checkOwner), so the owner is always a member with no owner of its own. gopb applies the same intersection to the custom
// /api/lll routes (effectiveAccess).
//
// The rule shapes are those of 1789900000_member_teams.js (claims create
// stays null per 1791265600_claim_create_admin.js; owner and kind stay
// superuser-only per 1791500000_member_owner_kind_admin.js), built from an
// access model. Two changes besides the owner clause: a scoped read-write
// person may create a bot it owns (fleet case 09: a guest could not set up
// its own bot), and gopb defaults that bot to its owner's access.

const AUTH = '@request.auth.id != ""';
const NO_OWNER = '@request.auth.owner = ""';

// What the caller may do. `all` and `rw` are whole conditions; `sees(team)`
// is the condition that the caller sees the team named by the expression.
const EFFECTIVE = {
  all: `(@request.auth.scope = "all" && (${NO_OWNER} || @request.auth.owner.scope = "all"))`,
  rw: `(@request.auth.mode = "rw" && (${NO_OWNER} || @request.auth.owner.mode = "rw"))`,
  sees: (team) =>
    `(@request.auth.scope = "all" || @request.auth.teams.id ?= ${team})` +
    ` && (${NO_OWNER} || @request.auth.owner.scope = "all" || @request.auth.owner.teams.id ?= ${team})`,
};
// The previous model, for the down migration: own fields only.
const OWN = {
  all: '@request.auth.scope = "all"',
  rw: '@request.auth.mode = "rw"',
  sees: (team) => `(@request.auth.scope = "all" || @request.auth.teams.id ?= ${team})`,
};

const ADMIN_ONLY_FIELDS = ["teams", "scope", "mode", "owner", "kind"]
  .map((f) => `@request.body.${f}:isset = false`)
  .join(" && ");

// name -> [listRule, viewRule, createRule, updateRule, deleteRule]
function rulesFor(acc, botsBySelf) {
  const read = (field) => `${AUTH} && ${acc.sees(field)}`;
  const write = (field) => `${read(field)} && ${acc.rw}`;
  // An update must not move a row into a team the member cannot see.
  const keepsTeam = (field) =>
    `${write(field)} && (@request.body.${field}:isset = false || (${acc.sees(`@request.body.${field}`)}))`;
  // Rows that follow their issue: a scoped member may not re-point them.
  const keepsIssue = (rule) => `${rule} && (${acc.all} || @request.body.issue:isset = false)`;
  const FULL = `${acc.all} && ${acc.rw}`;
  const ONLY_FULL = `${AUTH} && ${FULL}`;
  // Favorites and saved views are a member's own unless it is full.
  const own = (rule) => `${rule} && ((${FULL}) || member = @request.auth.id)`;
  const ownCreate = (rule) => `${rule} && ((${FULL}) || @request.body.member = @request.auth.id)`;
  const keepsOwner = (rule) => `${own(rule)} && ((${FULL}) || @request.body.member:isset = false)`;
  const fav = read("issue.team");
  const team = (f) => [read(f), read(f), write(f), keepsTeam(f), write(f)];
  // A read-write member creates a bot it owns; gopb checks the bot's access
  // stays within the owner's.
  const ownBot = `(@request.body.kind = "bot" && @request.body.owner = @request.auth.id && ${acc.rw})`;
  return {
    teams: [read("id"), read("id"), ONLY_FULL, ONLY_FULL, ONLY_FULL],
    projects: team("team"),
    labels: team("team"),
    issues: team("team"),
    docs: team("team"),
    webhooks: team("team"),
    comments: [read("issue.team"), read("issue.team"), write("issue.team"), keepsIssue(write("issue.team")), write("issue.team")],
    favorites: [own(fav), own(fav), ownCreate(fav), keepsOwner(keepsIssue(fav)), own(fav)],
    views: [own(AUTH), own(AUTH), ownCreate(AUTH), keepsOwner(AUTH), own(AUTH)],
    claims: [read("issue.team"), read("issue.team"), null, null, null],
    members: [
      AUTH,
      AUTH,
      botsBySelf ? `${AUTH} && ((${FULL}) || ${ownBot})` : ONLY_FULL,
      `${AUTH} && ${ADMIN_ONLY_FIELDS} && ((${FULL}) || id = @request.auth.id)`,
      null,
    ],
  };
}
const NAMES = ["listRule", "viewRule", "createRule", "updateRule", "deleteRule"];

function apply(app, rules) {
  for (const [name, list] of Object.entries(rules)) {
    const c = app.findCollectionByNameOrId(name);
    NAMES.forEach((rule, i) => { c[rule] = list[i]; });
    app.save(c);
  }
}

migrate((app) => apply(app, rulesFor(EFFECTIVE, true)), (app) => apply(app, rulesFor(OWN, false)));
