/// <reference path="../pb_data/types.d.ts" />

// TASK-205: the work-site slot — where an issue's branch is checked out
// RIGHT NOW. Three plain text fields, written together by `lll issue start`
// after the branch exists: the branch name, the machine (os.Hostname), and
// the worktree root path. The slot holds the current site only; a start
// from a different site overwrites it and an auto-comment keeps the trail.
// Nothing ever clears it — a done issue keeps which branch shipped it, and
// views render a stale site as "(last seen)" instead.
//
// Init covers fresh data dirs; this upgrades existing ones (the
// 1756500000_add_issue_sort.js precedent). Idempotent.
migrate(
  (app) => {
    const issues = app.findCollectionByNameOrId("issues");
    let changed = false;
    for (const name of ["work_branch", "work_host", "work_path"]) {
      if (!issues.fields.getByName(name)) {
        issues.fields.add(new TextField({ name }));
        changed = true;
      }
    }
    if (changed) app.save(issues);
  },
  (app) => {
    const issues = app.findCollectionByNameOrId("issues");
    let changed = false;
    for (const name of ["work_branch", "work_host", "work_path"]) {
      if (issues.fields.getByName(name)) {
        issues.fields.removeByName(name);
        changed = true;
      }
    }
    if (changed) app.save(issues);
  },
);
