// Package skills carries the portable skills inside the binary, so an agent
// pointed at an lll board gets the conventions that make the board work
// without needing a checkout of lll itself (LLL-404).
//
// The .md files here are a MIRROR. `.claude/skills/` is the editable source;
// scripts/sync_skills.py copies the portable ones in and `--check` fails the
// gate when they drift. The copy is forced rather than chosen: the go tool
// ignores directories whose names begin with ".", so no package can live under
// `.claude/`, and embed patterns may not contain ".." so none can reach in.
//
// This file is Go, not Lisette, for the same reason web/embed.go is: //go:embed
// only applies to a package-level var.
package skills

import (
	"embed"
	"io/fs"
	"sort"
	"strings"
)

//go:embed */SKILL.md
var files embed.FS

// Names lists the shipped skills, sorted, so the CLI's output is stable.
func Names() []string {
	entries, err := fs.ReadDir(files, ".")
	if err != nil {
		return nil
	}
	var out []string
	for _, e := range entries {
		if e.IsDir() {
			out = append(out, e.Name())
		}
	}
	sort.Strings(out)
	return out
}

// Body returns one skill's markdown, frontmatter included. Empty when there is
// no such skill, which the caller reports with the list of the ones there are.
func Body(name string) string {
	// No path separators: the argument names a skill, never a file to reach.
	if name == "" || strings.ContainsAny(name, "/\\.") {
		return ""
	}
	b, err := files.ReadFile(name + "/SKILL.md")
	if err != nil {
		return ""
	}
	return string(b)
}

// Description is the one-line summary from a skill's frontmatter, for `list`.
// Frontmatter is a small fixed shape here - "name:" and "description:" written
// by hand - so this reads the one field it needs rather than taking a YAML
// dependency for it.
func Description(name string) string {
	body := Body(name)
	if !strings.HasPrefix(body, "---\n") {
		return ""
	}
	end := strings.Index(body[4:], "\n---")
	if end < 0 {
		return ""
	}
	for _, line := range strings.Split(body[4:4+end], "\n") {
		if rest, ok := strings.CutPrefix(line, "description:"); ok {
			return strings.TrimSpace(rest)
		}
	}
	return ""
}
