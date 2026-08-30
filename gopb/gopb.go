// Package gopb embeds PocketBase behind a single function so that Lisette's
// bindgen only has to bind this tiny surface. Binding PocketBase directly
// fails on lis 0.7.0: transitive typedefs for golang.org/x/crypto/acme
// (references the GOEXPERIMENT-only encoding/json/jsontext package) and
// github.com/dop251/goja/parser (Go-style \uXXXX escapes in const strings)
// do not parse, and fixes would live in the gitignored target/ cache.
package gopb

import (
	"math"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/plugins/jsvm"
	"github.com/pocketbase/pocketbase/plugins/migratecmd"
)

// Serve runs PocketBase in-process and blocks until shutdown (an interrupt
// signal triggers PB's own graceful shutdown, after which Serve returns).
// It mirrors the prebuilt binary's `serve` command: jsvm hooks + JS
// migrations are registered, and migrations auto-apply before the server
// starts listening. The superuser is upserted right before listening, same
// semantics as `pocketbase superuser upsert` followed by `serve`.
func Serve(dataDir, addr, migrationsDir, adminEmail, adminPassword string) error {
	app := pocketbase.NewWithConfig(pocketbase.Config{
		DefaultDataDir: dataDir,
		// lll prints its own admin/board summary; PocketBase's three-line
		// "Server started at" banner would duplicate it. Only the banner is
		// suppressed -- startup errors still reach stdout.
		HideStartBanner: true,
	})

	// jsvm is what applies pb_migrations/*.js -- without it the database boots
	// with no collections. It also loads JS hooks, but there are none: the two
	// issue-create hooks are Go, below.
	jsvm.MustRegister(app, jsvm.Config{
		MigrationsDir: migrationsDir,
	})

	app.OnRecordCreate("issues").BindFunc(func(e *core.RecordEvent) error {
		if err := issueDefaults(e.App, e.Record); err != nil {
			return err
		}
		return e.Next()
	})

	migratecmd.MustRegister(app, app.RootCmd, migratecmd.Config{
		Dir:          migrationsDir,
		TemplateLang: migratecmd.TemplateLangJS,
	})

	app.OnServe().BindFunc(func(e *core.ServeEvent) error {
		if err := upsertSuperuser(e.App, adminEmail, adminPassword); err != nil {
			return err
		}
		return e.Next()
	})

	// Bootstrap explicitly: Execute()'s skipBootstrap() sniffs os.Args, which
	// hold lll's arguments ("up" is not a PB command), so it would wrongly
	// skip bootstrapping.
	if err := app.Bootstrap(); err != nil {
		return err
	}

	// Route through the real serve command (not apis.Serve directly) so we
	// inherit its exact behavior, including RunAllMigrations before listening.
	app.RootCmd.SetArgs([]string{"serve", "--http", addr})
	return app.Start()
}

// issueDefaults assigns the per-team issue number and the default board
// position on create. Both were JavaScript in pb_hooks/main.pb.js until the
// gopb commit-pin loop went away and Go became the cheaper place to put them.
//
// Each only fires when the client sent nothing, which is load-bearing in both
// cases: it lets the unique (team, number) index reject a forged duplicate
// rather than silently renumbering it, and it lets a drag-to-reorder PATCH keep
// the explicit fractional sort it computed.
func issueDefaults(app core.App, record *core.Record) error {
	if record.GetInt("number") == 0 {
		last, err := app.FindRecordsByFilter(
			"issues", "team = {:team}", "-number", 1, 0,
			dbx.Params{"team": record.GetString("team")},
		)
		if err != nil {
			return err
		}
		next := 1
		if len(last) > 0 {
			next = last[0].GetInt("number") + 1
		}
		record.Set("number", next)
	}

	if record.GetFloat("sort") == 0 {
		top, err := app.FindRecordsByFilter("issues", "id != ''", "-sort", 1, 0)
		if err != nil {
			return err
		}
		next := 1.0
		if len(top) > 0 {
			next = math.Floor(top[0].GetFloat("sort")) + 1
		}
		record.Set("sort", next)
	}

	return nil
}

// upsertSuperuser mirrors `pocketbase superuser upsert <email> <password>`.
func upsertSuperuser(app core.App, email, password string) error {
	superusers, err := app.FindCachedCollectionByNameOrId(core.CollectionNameSuperusers)
	if err != nil {
		return err
	}

	record, err := app.FindAuthRecordByEmail(superusers, email)
	if err != nil {
		record = core.NewRecord(superusers)
	}

	record.SetEmail(email)
	record.SetPassword(password)

	return app.Save(record)
}
