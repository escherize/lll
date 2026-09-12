package gopb

import (
	"fmt"
	"strings"
	"sync"
	"testing"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
)

func TestMergeReferencePreservesExistingText(t *testing.T) {
	before := "linear:ENG-118\tgh#7  "
	duplicate, err := mergeReference(before, "gh#7")
	if err != nil || duplicate.Added || duplicate.Refs != before {
		t.Fatalf("duplicate: %+v %v", duplicate, err)
	}
	added, err := mergeReference(before, "gh#8")
	if err != nil || !added.Added || added.Refs != before+"gh#8" {
		t.Fatalf("append: %+v %v", added, err)
	}
	for _, bad := range []string{"", "two refs", "a\nb", "a\x00b"} {
		if _, err := mergeReference(before, bad); err == nil {
			t.Fatalf("accepted %q", bad)
		}
	}
}

func TestReferenceTransactionConcurrencyAndRollback(t *testing.T) {
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Cleanup)
	teams := core.NewBaseCollection("teams")
	teams.Fields.Add(&core.BoolField{Name: "archived"})
	if err := app.Save(teams); err != nil {
		t.Fatal(err)
	}
	team := core.NewRecord(teams)
	if err := app.Save(team); err != nil {
		t.Fatal(err)
	}
	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(&core.RelationField{Name: "team", CollectionId: teams.Id, MaxSelect: 1}, &core.TextField{Name: "refs", Max: 2000}, &core.TextField{Name: "title"})
	if err := app.Save(issues); err != nil {
		t.Fatal(err)
	}
	issue := core.NewRecord(issues)
	issue.Set("team", team.Id)
	issue.Set("title", "Keep title")
	issue.Set("refs", "linear:ENG-118")
	if err := app.Save(issue); err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	errors := make(chan error, 24)
	for i := range 24 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := appendReference(app, issue.Id, fmt.Sprintf("gh#%d", i+1))
			errors <- err
		}()
	}
	wg.Wait()
	close(errors)
	for err := range errors {
		if err != nil {
			t.Fatal(err)
		}
	}
	saved, err := app.FindRecordById("issues", issue.Id)
	if err != nil {
		t.Fatal(err)
	}
	if len(strings.Fields(saved.GetString("refs"))) != 25 || saved.GetString("title") != "Keep title" {
		t.Fatal(saved.PublicExport())
	}
	before := saved.GetString("refs")
	if _, err := appendReference(app, issue.Id, strings.Repeat("x", 2001)); err == nil {
		t.Fatal("oversize append succeeded")
	}
	team.Set("archived", true)
	if err := app.Save(team); err != nil {
		t.Fatal(err)
	}
	if _, err := appendReference(app, issue.Id, "gh#99"); err == nil {
		t.Fatal("archived append succeeded")
	}
	saved, _ = app.FindRecordById("issues", issue.Id)
	if saved.GetString("refs") != before {
		t.Fatal("failed append changed refs")
	}
}
