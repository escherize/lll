package gopb

import "testing"

func TestTeamAccessSeparatesViewerAndEditor(t *testing.T) {
	a := access{teams: []string{"engineering", "finance"}, editors: []string{"engineering", "hidden"}}
	if !a.sees("finance") || a.writes("finance") || !a.writes("engineering") || a.writes("hidden") || a.rw {
		t.Fatal("mixed membership implied uniform writes or visibility from an Editor id")
	}
}
func TestTeamAccessIntersectionsMatchEveryTeamDecision(t *testing.T) {
	variants := []access{{}, {all: true}, {all: true, rw: true}, {teams: []string{"a"}}, {teams: []string{"a", "b"}, rw: true}, {teams: []string{"a", "b"}, editors: []string{"a"}}, {teams: []string{"a", "b"}, editors: []string{"b"}}, {all: true, editors: []string{"b"}}, {teams: []string{"a"}, editors: []string{"invisible"}}}
	for i, a := range variants {
		for j, b := range variants {
			out := a.within(b)
			for _, team := range []string{"a", "b", "invisible", "future"} {
				if out.sees(team) != (a.sees(team) && b.sees(team)) || out.writes(team) != (a.writes(team) && b.writes(team)) {
					t.Fatalf("intersection %d/%d differs on %s: %#v", i, j, team, out)
				}
			}
		}
	}
}
func TestTeamAccessCoverageIncludesRolesAndFutureTeams(t *testing.T) {
	mixed := access{teams: []string{"a", "b"}, editors: []string{"a"}}
	cases := []struct {
		name           string
		ceiling, grant access
		want           bool
	}{
		{"self", mixed, mixed, true},
		{"viewer cannot grant editor", access{teams: []string{"a", "b"}}, mixed, false},
		{"one team cannot grant other", mixed, access{teams: []string{"c"}}, false},
		{"finite cannot promise future", access{teams: []string{"a", "b"}, rw: true}, access{all: true}, false},
		{"all viewer cannot grant future editor", access{all: true, editors: []string{"a", "b"}}, access{all: true, rw: true}, false},
		{"all editor covers mixed", access{all: true, rw: true}, mixed, true},
		{"finite editors cover finite rw", access{teams: []string{"a", "b"}, editors: []string{"a", "b"}}, access{teams: []string{"a", "b"}, rw: true}, true},
		{"editor in wrong team", mixed, access{teams: []string{"a", "b"}, editors: []string{"b"}}, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := c.ceiling.covers(c.grant); got != c.want {
				t.Fatalf("covers=%v, want %v", got, c.want)
			}
		})
	}
}
