/// <reference path="../pb_data/types.d.ts" />

// The audit log (LLL-609, owner decision 2026-10-14). One row per write to
// an issue, comment or claim, saved by gopb (audit.go) in the transaction
// that makes the write: who (member, agent label, origin host), what
// (collection, record, action) and the changed fields before and after.
//
// Append-only: no member may create, update or delete a row (null rules),
// and gopb refuses an update from anyone, a superuser included. Retention is
// a superuser delete. Rows are readable per team under the same scope rule
// as issues. `team`, `issue`, `project` and `actor` are plain ids, not
// relations: a relation would be rewritten (an update) when its target is
// deleted, and the log must outlive what it describes. No name is stored:
// a reader resolves `actor` through the members roster, which hides members
// a scoped reader may not see (LLL-551). `number` is the issue's, so a reader
// derives the key from the team's current key, as every other surface does.
//
// `seq` is the cursor. Writes are serialized (one SQLite writer) and gopb
// assigns max(seq)+1 inside the write's transaction, so a reader that has
// seen seq N has seen every row below it; `created` alone cannot promise that.
// The issues read rule as it stands after 1791700000_bot_owner_scope.js: a
// bot reads no wider than its owner.
const READ = '@request.auth.id != "" && (@request.auth.scope = "all" || @request.auth.teams.id ?= team) && ' +
  '(@request.auth.owner = "" || @request.auth.owner.scope = "all" || @request.auth.owner.teams.id ?= team)';

migrate((app) => {
  const events = new Collection({
    type: "base",
    name: "audit_events",
    listRule: READ,
    viewRule: READ,
    createRule: null,
    updateRule: null,
    deleteRule: null,
    fields: [
      { name: "seq", type: "number", required: true, onlyInt: true, min: 1 },
      { name: "collection", type: "select", required: true, maxSelect: 1, values: ["issues", "comments", "claims"] },
      { name: "record", type: "text", required: true },
      { name: "action", type: "select", required: true, maxSelect: 1, values: ["create", "update", "delete"] },
      { name: "team", type: "text" },
      { name: "issue", type: "text" },
      { name: "number", type: "number", onlyInt: true },
      { name: "project", type: "text" },
      { name: "actor", type: "text" },
      { name: "actor_kind", type: "select", required: true, maxSelect: 1, values: ["person", "bot", "superuser", "system"] },
      { name: "agent", type: "text", max: 64 },
      { name: "origin_host", type: "text", max: 255 },
      { name: "changes", type: "json", maxSize: 4 << 20 },
      { name: "created", type: "autodate", onCreate: true, onUpdate: false },
    ],
    indexes: [
      "CREATE UNIQUE INDEX idx_audit_events_seq ON audit_events (seq)",
      "CREATE INDEX idx_audit_events_team_seq ON audit_events (team, seq)",
      "CREATE INDEX idx_audit_events_issue_seq ON audit_events (issue, seq)",
    ],
  });
  app.save(events);
}, (app) => {
  app.delete(app.findCollectionByNameOrId("audit_events"));
});
