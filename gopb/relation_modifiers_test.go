package gopb

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
)

// TestConcurrentRelationModifiersKeepEveryEdge pins LLL-513: concurrent
// "issues+" and "issues-" PATCHes against one doc all take effect. PocketBase
// resolves a modifier from a record it read before the save, so without
// serializeRecordUpdates this test kept 1-6 of 16 edges.
func TestConcurrentRelationModifiersKeepEveryEdge(t *testing.T) {
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Cleanup)

	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(&core.TextField{Name: "title"})
	if err := app.Save(issues); err != nil {
		t.Fatal(err)
	}
	docs := core.NewBaseCollection("docs")
	docs.Fields.Add(&core.RelationField{Name: "issues", CollectionId: issues.Id, MaxSelect: 999})
	rule := ""
	docs.UpdateRule = &rule
	if err := app.Save(docs); err != nil {
		t.Fatal(err)
	}
	doc := core.NewRecord(docs)
	if err := app.Save(doc); err != nil {
		t.Fatal(err)
	}
	const n = 16
	ids := make([]string, n)
	for i := range ids {
		issue := core.NewRecord(issues)
		issue.Set("title", "x")
		if err := app.Save(issue); err != nil {
			t.Fatal(err)
		}
		ids[i] = issue.Id
	}

	baseRouter, err := apis.NewRouter(app)
	if err != nil {
		t.Fatal(err)
	}
	var locks issueWriteLocks
	baseRouter.BindFunc(serializeRecordUpdates(&locks))
	serveEvent := &core.ServeEvent{App: app, Router: baseRouter}
	if err := app.OnServe().Trigger(serveEvent, func(e *core.ServeEvent) error { return nil }); err != nil {
		t.Fatal(err)
	}
	mux, err := baseRouter.BuildMux()
	if err != nil {
		t.Fatal(err)
	}

	// Every request waits on one channel so they reach the router together.
	concurrently := func(modifier string, ids []string) {
		var wg sync.WaitGroup
		start := make(chan struct{})
		for _, id := range ids {
			wg.Add(1)
			go func(id string) {
				defer wg.Done()
				<-start
				req := httptest.NewRequest(http.MethodPatch, "/api/collections/docs/records/"+doc.Id,
					strings.NewReader(`{"`+modifier+`":["`+id+`"]}`))
				req.Header.Set("Content-Type", "application/json")
				rec := httptest.NewRecorder()
				mux.ServeHTTP(rec, req)
				if rec.Code != http.StatusOK {
					t.Errorf("PATCH %s: %d %s", modifier, rec.Code, rec.Body.String())
				}
			}(id)
		}
		close(start)
		wg.Wait()
	}
	edges := func() []string {
		after, err := app.FindRecordById(docs.Id, doc.Id)
		if err != nil {
			t.Fatal(err)
		}
		return after.GetStringSlice("issues")
	}

	concurrently("issues+", ids)
	if got := len(edges()); got != n {
		t.Fatalf("concurrent issues+ kept %d of %d edges", got, n)
	}
	concurrently("issues-", ids[:n/2])
	got := edges()
	if len(got) != n/2 {
		t.Fatalf("concurrent issues- left %d edges, want %d", len(got), n/2)
	}
	// Appends landed in arrival order, so compare membership, not position.
	removed := map[string]bool{}
	for _, id := range ids[:n/2] {
		removed[id] = true
	}
	for _, id := range got {
		if removed[id] {
			t.Fatalf("after issues-, removed edge %s is still linked", id)
		}
	}
}

// The assignment route carries the other half of 'issue update': an
// --add-label/--remove-label combined with --assignee lands here (LLL-513).
func TestAssignmentAppliesLabelModifiers(t *testing.T) {
	fields, err := parseAssignmentFields([]byte(`{"assignee":"","labels+":["c"],"labels-":["a"]}`))
	if err != nil {
		t.Fatal(err)
	}
	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(
		&core.RelationField{Name: "assignee", CollectionId: "members", MaxSelect: 1},
		&core.RelationField{Name: "labels", CollectionId: "labels", MaxSelect: 999},
	)
	issue := core.NewRecord(issues)
	issue.Set("labels", []string{"a", "b"})
	fields.apply(issue)
	if got := strings.Join(issue.GetStringSlice("labels"), ","); got != "b,c" {
		t.Fatalf("labels after +c -a: %s, want b,c", got)
	}
}
