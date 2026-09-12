// Package web carries the board's markup and static assets inside the binary,
// so `lll up` runs from any directory instead of only the lll checkout root.
//
// This file is Go, not Lisette, because `//go:embed` only applies to a
// package-level var and Lisette (still true in 0.12.0) has no package-level var (its @rawgo
// escape hatch is statement-scoped). Lisette consumes the result natively:
// embed.FS satisfies fs.FS, which template.ParseFS and http.FileServerFS take.
package web

import (
	"bytes"
	"embed"
	"fmt"
	"html/template"
	"io/fs"
	"sync"
)

//go:embed templates static
var assets embed.FS

// Assets holds the board's files under their repo paths: "templates/board.html",
// "static/theme.css". Request paths line up with the static half, so
// http.FileServerFS(Assets()) serves /static/ with no prefix surgery.
func Assets() fs.FS { return assets }

// Embedded templates cannot change during the process lifetime. Keep the
// parsed set private so callers cannot mutate it while requests execute it.
var templates = sync.OnceValues(func() (*template.Template, error) {
	return template.ParseFS(assets, "templates/*.html")
})

// Render executes a cached template into a request-owned buffer. Startup uses
// this same path to validate page models before accepting connections.
func Render(name string, data any) (string, error) {
	tmpl, err := templates()
	if err != nil {
		return "", fmt.Errorf("parsing web/templates: %w", err)
	}
	var buf bytes.Buffer
	if err := tmpl.ExecuteTemplate(&buf, name, data); err != nil {
		return "", fmt.Errorf("rendering %s: %w", name, err)
	}
	return buf.String(), nil
}
