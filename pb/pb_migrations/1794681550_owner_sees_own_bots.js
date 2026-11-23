/// <reference path="../pb_data/types.d.ts" />
// LLL-798: an owner can always list and view the bots they own.
//
// The roster rule (LLL-551) shows a member narrower than every team itself,
// full-access people and members sharing a team. `lll bot disable` leaves a
// bot with no teams, so a team-scoped owner's bot left their own roster the
// moment they disabled it: `lll member access bot-NAME` answered "no member
// named", while `lll bot rotate` and `lll bot remove`, which resolve the bot
// through their own route, still found it.
//
// The owner relation is server-owned and names a human (a worker created by
// a bot keeps that human owner), so the added alternative shows a caller only
// identities already bounded by the caller's own access. roster.go still
// strips emails and hidden team ids from what a narrow caller reads.
const rules = require(`${__migrations}/lib/rules.js`);

const ALL = '(@request.auth.scope = "all" && (@request.auth.owner = "" || @request.auth.owner.scope = "all"))';
const SHARED = '((@request.auth.scope = "all" || teams.id ?= @request.auth.teams.id) && ' +
  '(@request.auth.owner = "" || @request.auth.owner.scope = "all" || teams.id ?= @request.auth.owner.teams.id))';
const OLD_WHO = `${ALL} || id = @request.auth.id || (scope = "all" && kind != "bot") || ${SHARED}`;
const NEW_WHO = `${ALL} || id = @request.auth.id || owner = @request.auth.id || (scope = "all" && kind != "bot") || ${SHARED}`;

migrate(
  (app) => {
    for (const rule of ["listRule", "viewRule"]) {
      rules.removeClause(app, "members", rule, OLD_WHO);
      rules.addClause(app, "members", rule, NEW_WHO);
    }
  },
  (app) => {
    for (const rule of ["listRule", "viewRule"]) {
      rules.removeClause(app, "members", rule, NEW_WHO);
      rules.addClause(app, "members", rule, OLD_WHO);
    }
  },
);
