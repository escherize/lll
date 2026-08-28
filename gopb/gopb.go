// Package gopb embeds PocketBase behind a single function so that Lisette's
// bindgen only has to bind this tiny surface. Binding PocketBase directly
// fails on lis 0.7.0: transitive typedefs for golang.org/x/crypto/acme
// (references the GOEXPERIMENT-only encoding/json/jsontext package) and
// github.com/dop251/goja/parser (Go-style \uXXXX escapes in const strings)
// do not parse, and fixes would live in the gitignored target/ cache.
package gopb

import (
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
func Serve(dataDir, addr, migrationsDir, hooksDir, adminEmail, adminPassword string) error {
	app := pocketbase.NewWithConfig(pocketbase.Config{
		DefaultDataDir: dataDir,
	})

	jsvm.MustRegister(app, jsvm.Config{
		MigrationsDir: migrationsDir,
		HooksDir:      hooksDir,
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
