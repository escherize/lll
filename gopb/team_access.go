package gopb

import (
	"github.com/pocketbase/pocketbase/core"
	"slices"
)

// access preserves legacy all/future-team grants while expressing a finite
// Editor subset. rw is a uniform write grant, never "can write somewhere".
// Authorize content with writes(team). editors grants no visibility by itself.
type access struct {
	all     bool
	teams   []string
	rw      bool
	editors []string
}

func ownAccess(m *core.Record) access {
	return access{all: m.GetString("scope") == "all", teams: m.GetStringSlice("teams"), rw: m.GetString("mode") == "rw"}
}
func (a access) sees(team string) bool { return a.all || slices.Contains(a.teams, team) }
func (a access) writes(team string) bool {
	return a.sees(team) && (a.rw || slices.Contains(a.editors, team))
}

// within intersects authority per team and preserves future-team semantics.
func (a access) within(b access) access {
	out := access{all: a.all && b.all, rw: a.rw && b.rw}
	switch {
	case a.all:
		out.teams = slices.Clone(b.teams)
	case b.all:
		out.teams = slices.Clone(a.teams)
	default:
		for _, team := range a.teams {
			if slices.Contains(b.teams, team) {
				out.teams = append(out.teams, team)
			}
		}
	}
	if !out.rw {
		for _, candidates := range [][]string{a.editors, b.editors} {
			for _, team := range candidates {
				if a.writes(team) && b.writes(team) && !slices.Contains(out.editors, team) {
					out.editors = append(out.editors, team)
				}
			}
		}
	}
	return out
}

// covers compares data authority, never workspace administration. A finite
// Editor list cannot cover an all-team Editor grant, including future teams.
func (a access) covers(b access) bool {
	if b.all && !a.all {
		return false
	}
	// Keep legacy mode constraints for an empty scope as well.
	if b.rw && !a.rw && (b.all || len(b.teams) == 0) {
		return false
	}
	for _, team := range b.teams {
		if !a.sees(team) || (b.writes(team) && !a.writes(team)) {
			return false
		}
	}
	for _, team := range b.editors {
		if b.writes(team) && !a.writes(team) {
			return false
		}
	}
	return true
}
