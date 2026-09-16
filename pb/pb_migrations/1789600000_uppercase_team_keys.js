/// <reference path="../pb_data/types.d.ts" />

// LLL-235: team keys are uppercase. They were stored as typed, so a server
// could hold 'eng' and 'ENG' as two teams the unique index was happy with and
// prose could not tell apart, while every other surface - the derived issue
// key, the rail, the docs - assumed uppercase. The rule is enforced on write
// in gopb (OnRecordCreate/OnRecordUpdate for teams); this upgrades the rows
// that were written before it.
//
// A row whose uppercase form is ALREADY TAKEN is left alone rather than
// merged: the two teams own separate issues, and picking a survivor here
// would silently move work between them. It stays as it is and remains
// renameable by hand - `lll team rename eng -k ENGINEERING`. The alternative,
// throwing, would refuse to boot a server that is merely untidy.
//
// Irreversible by design: the down migration cannot know which keys were
// lowercase before, and guessing would be worse than leaving them uppercase.
migrate(
  (app) => {
    const teams = app.findAllRecords("teams");
    const keys = new Set(teams.map((t) => t.getString("key")));
    for (const team of teams) {
      const key = team.getString("key");
      const upper = key.toUpperCase();
      if (key === upper || keys.has(upper)) continue;
      team.set("key", upper);
      app.save(team);
      keys.delete(key);
      keys.add(upper);
    }
  },
  (app) => {
    // Nothing to undo: see above.
  },
);
