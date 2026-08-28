/// <reference path="../pb_data/types.d.ts" />

// Initial schema: teams and issues. API rules are open (no auth in v1).
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
        { name: "created", type: "autodate", onCreate: true },
        { name: "updated", type: "autodate", onCreate: true, onUpdate: true },
      ],
      indexes: [
        "CREATE UNIQUE INDEX `idx_issues_team_number` ON `issues` (`team`, `number`)",
      ],
    });
    app.save(issues);
  },
  (app) => {
    app.delete(app.findCollectionByNameOrId("issues"));
    app.delete(app.findCollectionByNameOrId("teams"));
  }
);
