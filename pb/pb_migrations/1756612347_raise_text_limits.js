/// <reference path="../pb_data/types.d.ts" />

// A text field with max unset gets PocketBase's default limit of 5000
// characters (core/field_text.go: `if max == 0 { max = 5000 }`), which is a
// default rather than a decision. Real long-form content already exceeds it:
// importing the notes corpus hit validation_max_text_constraint and had to
// truncate. 100000 fits long-form prose while keeping the field bounded, so a
// runaway client still gets a clean 400 instead of writing a novel to SQLite.
//
// Applies to the two long-form fields only. Titles, names and
// projects.description stay at the default on purpose.
const MAX = 100000;

migrate(
  (app) => {
    for (const [name, field] of [["issues", "description"], ["comments", "body"]]) {
      const c = app.findCollectionByNameOrId(name);
      c.fields.getByName(field).max = MAX;
      app.save(c);
    }
  },
  (app) => {
    for (const [name, field] of [["issues", "description"], ["comments", "body"]]) {
      const c = app.findCollectionByNameOrId(name);
      c.fields.getByName(field).max = 0; // back to PocketBase's default 5000
      app.save(c);
    }
  },
);
