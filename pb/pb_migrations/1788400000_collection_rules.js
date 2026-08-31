/// <reference path="../pb_data/types.d.ts" />

// TASK-181: every collection rule moves from "" (PUBLIC — anything that can
// reach the port can read, edit and DELETE everything) to
// "@request.auth.id != \"\"" (any authenticated member, per ADR-1: everyone
// is a member, members see everything, no per-record ACLs). lll is hosted on
// a public *.fly.dev hostname, so this is the difference between a tracker
// and one anyone on the internet can empty.
//
// PocketBase rule semantics (verified against v0.40.1 apis/record_crud.go):
// "" = anyone, null = superuser only, a filter string is applied per request
// (a guest listing an auth-only collection gets 200 with zero items, a guest
// viewing/updating/deleting gets 404, a guest creating gets 400 — the rule
// is a filter, deliberately, so responses cannot leak existence).
//
// Two deviations from "flip every rule on every collection", both deliberate:
//
// 1. claims.updateRule stays null (superuser only, set by TASK-175). A claim
//    is created or deleted, never edited: flipping updateRule to the auth
//    rule would WEAKEN it — any member could PATCH the winning row's
//    `member` to itself and steal the hold, the exact second door the null
//    rule exists to close. Superuser-only is stricter than authenticated;
//    the public hole is closed either way.
//
// 2. _superusers is PocketBase's own collection and is not touched here. Its
//    rules are already null (superuser only).
//
// 3. PocketBase's stock `users` collection (every fresh install gets one;
//    lll never reads or writes it) ships with createRule "" — a standing
//    public self-registration nobody asked for. It goes to null: nothing in
//    lll authenticates as a users record, so even members have no business
//    in it. The down migration restores the stock rules verbatim.
//
// Members: createRule flips too — NO public self-registration exception.
// First-boot seeding does not need it: `lll up` authenticates as the
// superuser (the same credentials gopb.Serve upserted) before it seeds the
// team and the first member (src/commands/up.lis), so the boot's member
// create is authenticated. Verified by a fresh boot with these rules
// applied (scripts/e2e_up.sh first-boot section).
//
// Web board handoff (TASK-182): the board's server-side PocketBase client
// still needs a token, and browsers cannot authenticate yet. `lll up`
// defaults the process-wide LLL_TOKEN to the superuser token, so pages keep
// rendering and acting; TASK-182 replaces that with per-session member
// tokens.
//
// Idempotent (re-applying writes the same rules) and reversible: the down
// migration restores the exact pre-TASK-181 state — "" everywhere except
// claims.updateRule (null) and `users` (PocketBase's stock rules).
const AUTH = "@request.auth.id != \"\"";

// name -> [listRule, viewRule, createRule, updateRule, deleteRule]
const RULES = {
  teams: [AUTH, AUTH, AUTH, AUTH, AUTH],
  members: [AUTH, AUTH, AUTH, AUTH, AUTH],
  projects: [AUTH, AUTH, AUTH, AUTH, AUTH],
  labels: [AUTH, AUTH, AUTH, AUTH, AUTH],
  issues: [AUTH, AUTH, AUTH, AUTH, AUTH],
  comments: [AUTH, AUTH, AUTH, AUTH, AUTH],
  docs: [AUTH, AUTH, AUTH, AUTH, AUTH],
  views: [AUTH, AUTH, AUTH, AUTH, AUTH],
  favorites: [AUTH, AUTH, AUTH, AUTH, AUTH],
  claims: [AUTH, AUTH, AUTH, null, AUTH],
};

// Superuser only: lll does not use this collection, so nobody else should.
const USERS_RULES = [null, null, null, null, null];

// PocketBase's stock rules for `users`, restored verbatim by the down
// migration (the stock create is public — the hole being closed here).
const USERS_STOCK = [
  "id = @request.auth.id",
  "id = @request.auth.id",
  "",
  "id = @request.auth.id",
  "id = @request.auth.id",
];

// The pre-TASK-181 state, restored verbatim by the down migration.
const PUBLIC = "";
const BEFORE = {
  teams: [PUBLIC, PUBLIC, PUBLIC, PUBLIC, PUBLIC],
  members: [PUBLIC, PUBLIC, PUBLIC, PUBLIC, PUBLIC],
  projects: [PUBLIC, PUBLIC, PUBLIC, PUBLIC, PUBLIC],
  labels: [PUBLIC, PUBLIC, PUBLIC, PUBLIC, PUBLIC],
  issues: [PUBLIC, PUBLIC, PUBLIC, PUBLIC, PUBLIC],
  comments: [PUBLIC, PUBLIC, PUBLIC, PUBLIC, PUBLIC],
  docs: [PUBLIC, PUBLIC, PUBLIC, PUBLIC, PUBLIC],
  views: [PUBLIC, PUBLIC, PUBLIC, PUBLIC, PUBLIC],
  favorites: [PUBLIC, PUBLIC, PUBLIC, PUBLIC, PUBLIC],
  claims: [PUBLIC, PUBLIC, PUBLIC, null, PUBLIC],
};

migrate(
  (app) => {
    for (const name of Object.keys(RULES)) {
      const c = app.findCollectionByNameOrId(name);
      c.listRule = RULES[name][0];
      c.viewRule = RULES[name][1];
      c.createRule = RULES[name][2];
      c.updateRule = RULES[name][3];
      c.deleteRule = RULES[name][4];
      app.save(c);
    }
    try {
      const users = app.findCollectionByNameOrId("users");
      users.listRule = USERS_RULES[0];
      users.viewRule = USERS_RULES[1];
      users.createRule = USERS_RULES[2];
      users.updateRule = USERS_RULES[3];
      users.deleteRule = USERS_RULES[4];
      app.save(users);
    } catch (_) {
      // no stock users collection on this database; nothing to lock
    }
  },
  (app) => {
    for (const name of Object.keys(BEFORE)) {
      const c = app.findCollectionByNameOrId(name);
      c.listRule = BEFORE[name][0];
      c.viewRule = BEFORE[name][1];
      c.createRule = BEFORE[name][2];
      c.updateRule = BEFORE[name][3];
      c.deleteRule = BEFORE[name][4];
      app.save(c);
    }
    try {
      const users = app.findCollectionByNameOrId("users");
      users.listRule = USERS_STOCK[0];
      users.viewRule = USERS_STOCK[1];
      users.createRule = USERS_STOCK[2];
      users.updateRule = USERS_STOCK[3];
      users.deleteRule = USERS_STOCK[4];
      app.save(users);
    } catch (_) {
      // no stock users collection on this database; nothing to restore
    }
  },
);
