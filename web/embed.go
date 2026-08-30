// Package web carries the board's markup and static assets inside the binary,
// so `lll up` runs from any directory instead of only the lll checkout root.
//
// This file is Go, not Lisette, because `//go:embed` only applies to a
// package-level var and Lisette 0.11.3 has no package-level var (its @rawgo
// escape hatch is statement-scoped). Lisette consumes the result natively:
// embed.FS satisfies fs.FS, which template.ParseFS and http.FileServerFS take.
package web

import (
	"embed"
	"io/fs"
)

//go:embed templates static
var assets embed.FS

// Assets holds the board's files under their repo paths: "templates/board.html",
// "static/theme.css". Request paths line up with the static half, so
// http.FileServerFS(Assets()) serves /static/ with no prefix surgery.
func Assets() fs.FS { return assets }
