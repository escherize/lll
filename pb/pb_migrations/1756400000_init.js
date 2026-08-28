/// <reference path="../pb_data/types.d.ts" />

// Initial schema: teams, members, issues, comments. API rules are open (no auth in v1).
migrate(
  (app) => {
    const teams = new Collection({
      type: "base",
      name: "teams",
      listRule: "",
      viewRule: "",
      createRule: "",
      updateRule: "",
      deleteRule: "",
      fields: [
        { name: "key", type: "text", required: true },
        { name: "name", type: "text" },
        { name: "created", type: "autodate", onCreate: true },
        { name: "updated", type: "autodate", onCreate: true, onUpdate: true },
      ],
      indexes: ["CREATE UNIQUE INDEX `idx_teams_key` ON `teams` (`key`)"],
    });
    app.save(teams);

    // Plain collection, not PB auth (no auth in v1); honor-system identities.
    const members = new Collection({
      type: "base",
      name: "members",
      listRule: "",
      viewRule: "",
      createRule: "",
      updateRule: "",
      deleteRule: "",
      fields: [
        { name: "name", type: "text", required: true },
        { name: "email", type: "text" },
        { name: "created", type: "autodate", onCreate: true },
        { name: "updated", type: "autodate", onCreate: true, onUpdate: true },
      ],
      indexes: ["CREATE UNIQUE INDEX `idx_members_name` ON `members` (`name`)"],
    });
    app.save(members);

    const issues = new Collection({
      type: "base",
      name: "issues",
      listRule: "",
      viewRule: "",
      createRule: "",
      updateRule: "",
      deleteRule: "",
      fields: [
        {
          name: "team",
          type: "relation",
          required: true,
          collectionId: teams.id,
          maxSelect: 1,
          cascadeDelete: false,
        },
        { name: "number", type: "number", onlyInt: true },
        { name: "title", type: "text", required: true },
        { name: "description", type: "text" },
        {
          name: "state",
          type: "select",
          required: true,
          maxSelect: 1,
          values: ["backlog", "todo", "in-progress", "in-review", "done", "cancelled"],
        },
        // Linear's priority scale: 0 none, 1 urgent, 2 high, 3 medium, 4 low.
        { name: "priority", type: "number", onlyInt: true, min: 0, max: 4 },
        {
          name: "assignee",
          type: "relation",
          collectionId: members.id,
          maxSelect: 1,
          cascadeDelete: false,
        },
        { name: "created", type: "autodate", onCreate: true },
        { name: "updated", type: "autodate", onCreate: true, onUpdate: true },
      ],
      indexes: [
        "CREATE UNIQUE INDEX `idx_issues_team_number` ON `issues` (`team`, `number`)",
      ],
    });
    app.save(issues);

    const comments = new Collection({
      type: "base",
      name: "comments",
      listRule: "",
      viewRule: "",
      createRule: "",
      updateRule: "",
      deleteRule: "",
      fields: [
        {
          name: "issue",
          type: "relation",
          required: true,
          collectionId: issues.id,
          maxSelect: 1,
          cascadeDelete: true,
        },
        {
          name: "author",
          type: "relation",
          collectionId: members.id,
          maxSelect: 1,
          cascadeDelete: false,
        },
        { name: "body", type: "text", required: true },
        { name: "created", type: "autodate", onCreate: true },
        { name: "updated", type: "autodate", onCreate: true, onUpdate: true },
      ],
    });
    app.save(comments);
  },
  (app) => {
    app.delete(app.findCollectionByNameOrId("comments"));
    app.delete(app.findCollectionByNameOrId("issues"));
    app.delete(app.findCollectionByNameOrId("members"));
    app.delete(app.findCollectionByNameOrId("teams"));
  }
);
