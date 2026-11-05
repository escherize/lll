/// <reference path="../pb_data/types.d.ts" />

// LLL-668: auth.teams source and destination tests otherwise reuse one SQL
// join, requiring the same team row to equal both IDs. Resolve destination
// access through a separately aliased member. Both member and owner must
// still see the source (the unchanged clauses) AND the destination.
// ?= on the aliased id is intentional: = requires every joined member to
// match, rather than selecting the authenticated member from the collection.
// Bind the alias outside the optional team clause so unchanged-team writes
// still resolve only this actor, rather than an unbounded collection product.
const rules = require(`${__migrations}/lib/rules.js`);
const OLD_DESTINATION = '(@request.body.team:isset = false || ((@request.auth.scope = "all" || @request.auth.teams.id ?= @request.body.team) && (@request.auth.owner = "" || @request.auth.owner.scope = "all" || @request.auth.owner.teams.id ?= @request.body.team)))';
const NEW_DESTINATION =
  '@collection.members:lll_move_member.id ?= @request.auth.id && (' +
  '@request.body.team:isset = false || (' +
  '(@request.auth.scope = "all" || ' +
  '@collection.members:lll_move_member.teams.id ?= @request.body.team) && ' +
  '(@request.auth.owner = "" || @request.auth.owner.scope = "all" || ' +
  '@collection.members:lll_move_member.owner.teams.id ?= @request.body.team)))';
const COLLECTIONS = ["issues", "docs", "labels", "projects"];

function replace(app, before, after) {
  for (const name of COLLECTIONS) {
    rules.removeClause(app, name, "updateRule", before);
    rules.addClause(app, name, "updateRule", after);
  }
}

migrate(
  (app) => replace(app, OLD_DESTINATION, NEW_DESTINATION),
  (app) => replace(app, NEW_DESTINATION, OLD_DESTINATION),
);
