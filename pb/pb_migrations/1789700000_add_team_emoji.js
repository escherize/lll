/// Adds teams.emoji: one optional glyph per team, shown beside the key in the
/// rail's switcher and used as the tab icon's mark. A team's visual identity
/// was its accent colour plus a letter derived from the key, so two teams whose
/// keys share an initial were distinguishable only by hue (LLL-427, phase 2 of
/// LLL-387).
///
/// Empty means today's rendering exactly: the derived letter, and no glyph in
/// the rail. Text rather than a relation for the same reason issues.emoji is:
/// the marker is chosen, not shared taxonomy. Max matches issues.emoji, because
/// one "emoji" can be a long ZWJ sequence. Idempotent.
migrate(
  (app) => {
    const teams = app.findCollectionByNameOrId("teams");
    if (!teams.fields.getByName("emoji")) {
      teams.fields.add(new TextField({ name: "emoji", max: 32 }));
      app.save(teams);
    }
  },
  (app) => {
    const teams = app.findCollectionByNameOrId("teams");
    if (teams.fields.getByName("emoji")) {
      teams.fields.removeByName("emoji");
      app.save(teams);
    }
  },
);
