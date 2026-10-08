/// <reference path="../pb_data/types.d.ts" />

// Issue numbers are never reused (LLL-678). Until now the next number was one
// past the team's highest LIVE issue, so deleting the top issue handed its
// number, and its key, to the next issue created.
//
// issue_counters holds, per team, the highest number the team has issued.
// gopb owns it (gopb/issue_numbers.go): it moves the counter inside every
// issue create's transaction and refuses any request that touches it. Every
// rule is null and every field hidden, so no member can read or probe it.
//
//   team   the team; unique, and deleting the team deletes its counter
//   last   the highest number issued so far
//
// A superuser repairs a counter through POST /api/lll/teams/{team}/issue-counter
// (logged, with a reason); nothing else lowers one.
//
// Backfill: each team starts at its highest live number. A number deleted
// before this migration ran cannot be recovered from the data, so the next
// issue may still reuse one of those; from here on none is reused. Issues
// whose team no longer exists are skipped (the relation would not save), and
// gopb takes the larger of the counter and the live maximum anyway, so a team
// the backfill missed only starts from its live maximum, as before.
//
// Numbers stay far below 2^53, where JSON and float64 stop counting exactly
// (gopb maxIssueNumber). issues.number gets the same ceiling; no existing
// row is rewritten, and a team already past the ceiling (only a forged
// number gets there) starts its counter at the ceiling rather than failing
// the boot.
const MAX_NUMBER = 999999999;

migrate(
  (app) => {
    const issues = app.findCollectionByNameOrId("issues");
    const number = issues.fields.getByName("number");
    number.max = MAX_NUMBER;
    app.save(issues);

    const teams = app.findCollectionByNameOrId("teams");
    const counters = new Collection({
      type: "base",
      name: "issue_counters",
      listRule: null,
      viewRule: null,
      createRule: null,
      updateRule: null,
      deleteRule: null,
      fields: [
        { name: "team", type: "relation", collectionId: teams.id, maxSelect: 1, required: true, cascadeDelete: true, hidden: true },
        { name: "last", type: "number", onlyInt: true, min: 0, max: MAX_NUMBER, hidden: true },
      ],
      indexes: ["CREATE UNIQUE INDEX `idx_issue_counters_team` ON `issue_counters` (`team`)"],
    });
    app.save(counters);

    const rows = arrayOf(new DynamicModel({ team: "", last: 0 }));
    app
      .db()
      .newQuery(
        "SELECT issues.team AS team, MAX(issues.number) AS last FROM issues " +
          "JOIN teams ON teams.id = issues.team GROUP BY issues.team",
      )
      .all(rows);
    for (const row of rows) {
      const counter = new Record(counters);
      counter.set("team", row.team);
      // Clamped both ways: before this release a member could create an
      // issue numbered below zero, and a counter below 0 fails the boot.
      counter.set("last", Math.max(0, Math.min(row.last, MAX_NUMBER)));
      app.save(counter);
    }
  },
  (app) => {
    app.delete(app.findCollectionByNameOrId("issue_counters"));
    const issues = app.findCollectionByNameOrId("issues");
    issues.fields.getByName("number").max = null;
    app.save(issues);
  },
);
