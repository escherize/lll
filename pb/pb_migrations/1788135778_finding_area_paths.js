/// <reference path="../pb_data/types.d.ts" />

// Adds docs.area and docs.paths (TASK-103): the two plain-text fields that
// make finding retrieval a FILTER instead of a search.
//
//   area  — one short workspace area, conventionally the NAME of an existing
//           label ("pb", "web"). An issue surfaces a finding when its labels
//           contain the finding's area, so a doc is authored once and
//           surfaces on every issue working in that area.
//   paths — comma-separated file or directory paths the finding is about
//           ("src/pb, pb/pb_migrations"). `lll finding near <path>` matches
//           by directory containment, both directions: asking about a file
//           finds the finding filed on its directory, and asking about a
//           directory finds findings filed on files inside it. The matching
//           itself is a prefix comparison in lll, not a PocketBase filter —
//           no SQL LIKE hack can express "under or above this directory"
//           without substring luck, which is exactly what AC#2 rules out.
//
// No new collection: a finding is still a doc with kind=finding. Both fields
// are optional plain text — docs written before this migration retrieve
// fine, they just match nothing until someone sets area or paths.

migrate(
  (app) => {
    const docs = app.findCollectionByNameOrId("docs");
    let changed = false;
    if (!docs.fields.getByName("area")) {
      docs.fields.add(new TextField({ name: "area", max: 80 }));
      changed = true;
    }
    if (!docs.fields.getByName("paths")) {
      // Room for a few dozen paths at typical repo depth.
      docs.fields.add(new TextField({ name: "paths", max: 2000 }));
      changed = true;
    }
    if (changed) {
      app.save(docs);
    }
  },
  (app) => {
    const docs = app.findCollectionByNameOrId("docs");
    let changed = false;
    if (docs.fields.getByName("area")) {
      docs.fields.removeByName("area");
      changed = true;
    }
    if (docs.fields.getByName("paths")) {
      docs.fields.removeByName("paths");
      changed = true;
    }
    if (changed) {
      app.save(docs);
    }
  },
);
