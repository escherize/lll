/// Adds teams.accent: one hex colour (#rrggbb) per team. The web board derives
/// its four --accent tokens and its SVG favicon from it, so two boards open
/// side by side are instantly distinguishable. Empty means DESIGN.md's
/// canonical ember orange #f0883e, which stays the default and the only
/// value the shipped tokens hard-code. Idempotent.
migrate(
  (app) => {
    const teams = app.findCollectionByNameOrId("teams");
    if (!teams.fields.getByName("accent")) {
      teams.fields.add(new TextField({ name: "accent", max: 7 }));
      app.save(teams);
    }
  },
  (app) => {
    const teams = app.findCollectionByNameOrId("teams");
    if (teams.fields.getByName("accent")) {
      teams.fields.removeByName("accent");
      app.save(teams);
    }
  },
);
