/// <reference path="../pb_data/types.d.ts" />

// Assign per-team issue numbers: number = max(number for team) + 1.
// Only when the client did not send a number, so the unique (team, number)
// index can reject forged duplicates and backstop races.
onRecordCreate((e) => {
  if (e.record.getInt("number") === 0) {
    const teamId = e.record.getString("team");
    const last = e.app.findRecordsByFilter(
      "issues",
      "team = {:team}",
      "-number",
      1,
      0,
      { team: teamId }
    );
    const next = last.length > 0 ? last[0].getInt("number") + 1 : 1;
    e.record.set("number", next);
  }
  // Default manual board position: strictly above every existing sort, so a
  // new issue lands at the end of its column. Only when the client did not
  // send a sort (reorders PATCH explicit fractional values).
  if (e.record.getFloat("sort") === 0) {
    const top = e.app.findRecordsByFilter("issues", "id != ''", "-sort", 1, 0);
    const next = top.length > 0 ? Math.floor(top[0].getFloat("sort")) + 1 : 1;
    e.record.set("sort", next);
  }
  e.next();
}, "issues");
