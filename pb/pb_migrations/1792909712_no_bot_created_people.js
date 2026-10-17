/// <reference path="../pb_data/types.d.ts" />

// An owned bot's access must stay bounded by its human owner. Minting an
// ownerless person would evade future narrowing, revocation and rotation.
// Add an independent clause so bot-creation permissions can evolve without
// reopening person creation (including for bots provisioned by a superuser).
const rules = require(`${__migrations}/lib/rules.js`);
const NO_BOT_CREATED_PERSON = '(@request.auth.kind != "bot" && @request.auth.owner = "") || kind = "bot"';

migrate(
  (app) => rules.addClause(app, "members", "createRule", NO_BOT_CREATED_PERSON),
  (app) => rules.removeClause(app, "members", "createRule", NO_BOT_CREATED_PERSON),
);
