/// <reference path="../pb_data/types.d.ts" />

// Carries team scoping past issues (TASK-173). One server holds many
// projects; teams are the tenancy boundary, and issues have honoured it since
// the walking skeleton (`team` required, `UNIQUE (team, number)`). Docs,
// projects and labels did not.
//
// Three changes, one migration, because they are one rule:
//
//   1. docs.team — a NEW required relation, and `UNIQUE (team, slug)` in
//      place of the global `idx_docs_slug`. Without it two projects cannot
//      both hold a doc slugged "index", "architecture" or "readme": the
//      second create fails on the unique index. Docs are wiki pages,
//      decisions, findings and PRDs, so that is a hard block on the second
//      project writing anything at all.
//
//   2. projects.team and labels.team — already present, now required. An
//      unset team meant "workspace-wide", which every call site that filters
//      by team reads as "belongs to every team". Same defect as (1), leaking
//      instead of failing.
//
//   3. The backfill both of those need. Marking a field required does not
//      rewrite the rows already there; it makes every teamless one
//      unwritable the next time PocketBase validates it.
//
// Backfill target: the earliest-created team, which on any board that has
// ever had exactly one team IS that team. A board with no teams at all can
// only hold teamless rows if something wrote them without one, so the
// migration says which rows and stops rather than inventing a tenant.
//
// Order matters. Backfill, then add the field, then swap the index, then
// mark required: PocketBase validates on save, and the composite index
// cannot be built while `team` does not exist yet.
//
// Idempotent, shaped after 1788135778_finding_area_paths.js.

/** The team every teamless row is adopted by, or "" when there are none. */
function oldestTeamId(app) {
  const teams = app.findRecordsByFilter("teams", "id != ''", "created", 1, 0);
  return teams.length > 0 ? teams[0].id : "";
}

/** Ids of the rows in `collection` that name no team. */
function teamlessIds(app, collection) {
  const out = [];
  const rows = app.findRecordsByFilter(collection, "team = ''", "created", 0, 0);
  for (let i = 0; i < rows.length; i++) out.push(rows[i].id);
  return out;
}

/**
 * Give every teamless row in `collections` the oldest team, or explain why
 * that is impossible. Raw UPDATE rather than a record save: these rows are
 * being repaired, and a save runs the very validation the repair exists to
 * satisfy.
 */
function backfill(app, collections) {
  const pending = [];
  let total = 0;
  for (const name of collections) {
    const ids = teamlessIds(app, name);
    total += ids.length;
    pending.push({ name, ids });
  }
  if (total === 0) return;

  const teamId = oldestTeamId(app);
  if (teamId === "") {
    const named = pending
      .filter((p) => p.ids.length > 0)
      .map((p) => `${p.name} (${p.ids.length})`)
      .join(", ");
    throw new Error(
      `cannot make team required: ${named} hold rows with no team and this ` +
        `database has no team to adopt them. Create one with ` +
        `'lll team create -k KEY -n "Name"' and rerun.`,
    );
  }

  for (const { name, ids } of pending) {
    for (const id of ids) {
      app
        .db()
        .newQuery(`UPDATE \`${name}\` SET team = {:team} WHERE id = {:id}`)
        .bind({ team: teamId, id: id })
        .execute();
    }
  }
}

/** `collection.indexes` as a plain array, without `drop`, plus `add`. */
function reindex(collection, drop, add) {
  const out = [];
  let present = false;
  for (let i = 0; i < collection.indexes.length; i++) {
    const idx = collection.indexes[i];
    if (idx.includes(drop)) continue;
    if (idx.includes(add.name)) present = true;
    out.push(idx);
  }
  if (!present) out.push(add.sql);
  collection.indexes = out;
}

/** Flip `team` between required and optional on one collection. */
function setTeamRequired(app, name, required) {
  const collection = app.findCollectionByNameOrId(name);
  const team = collection.fields.getByName("team");
  if (!team || team.required === required) return;
  team.required = required;
  app.save(collection);
}

migrate(
  (app) => {
    const teams = app.findCollectionByNameOrId("teams");
    const docs = app.findCollectionByNameOrId("docs");

    if (!docs.fields.getByName("team")) {
      docs.fields.add(
        new RelationField({
          name: "team",
          collectionId: teams.id,
          maxSelect: 1,
          // A team is never deleted out from under its docs today (`lll team`
          // has no delete); if that changes, docs must outlive it the way
          // issues do.
          cascadeDelete: false,
        }),
      );
      app.save(docs);
    }

    // Docs written before this migration carry no team of their own, so they
    // are adopted alongside the projects and labels that carry an empty one.
    backfill(app, ["docs", "projects", "labels"]);

    // The whole point: two teams, one `index` each, no collision.
    reindex(docs, "idx_docs_slug", {
      name: "idx_docs_team_slug",
      sql: "CREATE UNIQUE INDEX `idx_docs_team_slug` ON `docs` (`team`, `slug`)",
    });
    app.save(docs);

    setTeamRequired(app, "docs", true);
    setTeamRequired(app, "projects", true);
    setTeamRequired(app, "labels", true);
  },
  (app) => {
    setTeamRequired(app, "labels", false);
    setTeamRequired(app, "projects", false);

    const docs = app.findCollectionByNameOrId("docs");
    // The global unique slug comes back, so this only applies cleanly to a
    // database whose slugs are still globally unique — which is exactly the
    // one the up migration ran on.
    reindex(docs, "idx_docs_team_slug", {
      name: "idx_docs_slug",
      sql: "CREATE UNIQUE INDEX `idx_docs_slug` ON `docs` (`slug`)",
    });
    if (docs.fields.getByName("team")) docs.fields.removeByName("team");
    app.save(docs);
  },
);
