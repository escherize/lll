// Package pb carries PocketBase's JS migrations inside the binary, so `lll up`
// runs from any directory instead of only the lll checkout root (TASK-80).
//
// This file is Go, not Lisette, for the same reason web/embed.go is: `//go:embed`
// only applies to a package-level var and Lisette (still true in 0.12.0) has no
// package-level var. Unlike web/, nothing in Lisette imports this package -- gopb
// does, in Go, because gopb is the only caller that hands the migrations to
// PocketBase. That keeps it out of lisette.toml.
//
// Only pb_migrations is embedded. The sibling pb_data is a live SQLite database
// and pb/README.md is documentation; neither belongs in the binary.
package pb

import (
	"embed"
	"io/fs"
)

//go:embed pb_migrations
var migrations embed.FS

// Migrations holds the JS migration files, rooted so that entries are bare
// filenames ("1756400000_init.js") rather than "pb_migrations/..." -- the shape
// PocketBase's jsvm plugin expects of a migrations directory.
func Migrations() fs.FS {
	sub, err := fs.Sub(migrations, "pb_migrations")
	if err != nil {
		// Unreachable: the path is a compile-time constant that //go:embed
		// already proved exists, so a failure here is a corrupt binary.
		panic(err)
	}
	return sub
}
