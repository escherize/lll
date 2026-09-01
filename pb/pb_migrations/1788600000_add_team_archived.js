/// <reference path="../pb_data/types.d.ts" />

// TASK-210: teams get a lifecycle end. `archived` hides a team from the rail
// switcher and default team lists; its board stays readable at /t/KEY/ and
// nothing is deleted. Init covers fresh data dirs; this upgrades existing
// ones (the 1756500000_add_issue_sort.js precedent). Idempotent.
migrate(
  (app) => {
    const teams = app.findCollectionByNameOrId("teams");
    if (!teams.fields.getByName("archived")) {
      teams.fields.add(new BoolField({ name: "archived" }));
      app.save(teams);
    }
  },
  (app) => {
    const teams = app.findCollectionByNameOrId("teams");
    if (teams.fields.getByName("archived")) {
      teams.fields.removeByName("archived");
      app.save(teams);
    }
  },
);
