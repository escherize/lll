package gopb

import (
	"slices"
	"testing"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
)

// A team link's reader is one read-only record per team, scoped to exactly
// that team, and asking twice returns the same record (LLL-658).
func TestLinkViewerIsOneReadOnlyRecordPerTeam(t *testing.T) {
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Cleanup)
	teams := core.NewBaseCollection("teams")
	teams.Fields.Add(&core.TextField{Name: "key"})
	if err := app.Save(teams); err != nil {
		t.Fatal(err)
	}
	viewers := core.NewAuthCollection(linkViewers)
	viewers.Fields.Add(&core.RelationField{Name: "teams", CollectionId: teams.Id, MaxSelect: 999},
		&core.TextField{Name: "scope"}, &core.TextField{Name: "mode"}, &core.TextField{Name: "link_team"})
	if err := app.Save(viewers); err != nil {
		t.Fatal(err)
	}
	alpha, beta := core.NewRecord(teams), core.NewRecord(teams)
	alpha.Set("key", "ALPHA")
	beta.Set("key", "BETA")
	for _, r := range []*core.Record{alpha, beta} {
		if err := app.Save(r); err != nil {
			t.Fatal(err)
		}
	}
	first, err := linkViewer(app, alpha.Id)
	if err != nil {
		t.Fatal(err)
	}
	again, err := linkViewer(app, alpha.Id)
	if err != nil {
		t.Fatal(err)
	}
	if first.Id == alpha.Id || again.Id != first.Id || again.GetString("link_team") != alpha.Id {
		t.Fatalf("link viewer ids %q, %q for team %q; want one record, not keyed by the team id", first.Id, again.Id, alpha.Id)
	}
	acc := effectiveAccess(app, again)
	if acc.all || acc.rw || !slices.Equal(acc.teams, []string{alpha.Id}) {
		t.Fatalf("link viewer access %+v; want read-only, team ALPHA only", acc)
	}
	if acc.sees(beta.Id) {
		t.Fatal("a link viewer for ALPHA sees BETA")
	}
	if n, _ := app.CountRecords(linkViewers); n != 1 {
		t.Fatalf("%d link viewers after two asks for one team; want 1", n)
	}
}
