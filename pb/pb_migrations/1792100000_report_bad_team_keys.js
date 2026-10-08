/// <reference path="../pb_data/types.d.ts" />

// LLL-628: a team key is a letter followed by up to 15 letters, digits, '_'
// or '-' (^[A-Z][A-Z0-9_-]{0,15}$). gopb enforces it on create and on a key
// change; this REPORTS the keys stored before the rule, once, in the server
// log. It rewrites nothing: a key is in every issue key, URL and .lll.toml
// that names the team, so renaming it is the owner's call
// (`lll team rename OLD -k NEW`). An unchanged legacy key still takes
// unrelated edits.
//
// Each key is printed JSON-quoted, so a key holding quotes or control
// characters cannot rewrite the log line it appears in.
migrate(
  (app) => {
    const shape = /^[A-Z][A-Z0-9_-]{0,15}$/;
    const bad = app
      .findAllRecords("teams")
      .filter((t) => !shape.test(t.getString("key")));
    for (const team of bad) {
      console.log(
        `team ${team.id} has key ${JSON.stringify(team.getString("key"))}, which breaks the team key rule ` +
          `^[A-Z][A-Z0-9_-]{0,15}$; rename it with 'lll team rename' (left unchanged)`,
      );
    }
  },
  (app) => {
    // Reports only: nothing to undo.
  },
);
