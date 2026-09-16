/// <reference path="../pb_data/types.d.ts" />

// Findings carry a confidence (LLL-396, after blackboard hypotheses): a
// finding is asserted by default, and today nothing marks a guess, so
// downstream agents read suspected findings as fact. Two fields on docs —
// findings are docs with kind=finding, and decisions benefit from the same
// marking for free.
//
//   confidence       — select: suspected | confirmed | refuted. Everything
//                      written before this migration was asserted without
//                      qualification, so the backfill is 'confirmed', which
//                      keeps today's semantics as the default (the issue's
//                      own default). PocketBase selects have no schema-level
//                      default, so the CLI sets confidence explicitly on
//                      every create, the same bargain member kind struck.
//   confidence_note  — the why a refutation carries ('finding refute SLUG
//                      -b why'). Empty unless someone refuted or confirmed
//                      with a note; confirming clears it.
migrate(
  (app) => {
    const docs = app.findCollectionByNameOrId("docs");
    let changed = false;
    if (!docs.fields.getByName("confidence")) {
      docs.fields.add(
        new SelectField({ name: "confidence", maxSelect: 1, values: ["suspected", "confirmed", "refuted"] }),
      );
      changed = true;
    }
    if (!docs.fields.getByName("confidence_note")) {
      docs.fields.add(new TextField({ name: "confidence_note", max: 1000 }));
      changed = true;
    }
    if (changed) {
      app.save(docs);
    }
    app
      .db()
      .newQuery("UPDATE `docs` SET `confidence` = 'confirmed' WHERE `confidence` = '' OR `confidence` IS NULL")
      .execute();
  },
  (app) => {
    const docs = app.findCollectionByNameOrId("docs");
    let changed = false;
    if (docs.fields.getByName("confidence")) {
      docs.fields.removeByName("confidence");
      changed = true;
    }
    if (docs.fields.getByName("confidence_note")) {
      docs.fields.removeByName("confidence_note");
      changed = true;
    }
    if (changed) {
      app.save(docs);
    }
  },
);
