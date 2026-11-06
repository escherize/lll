package gopb

import (
	"fmt"
	"github.com/pocketbase/pocketbase/apis"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/pocketbase/pocketbase/core"
)

func treeFixture(t *testing.T) teamRefFixture {
	t.Helper()
	f := newTeamRefFixture(t)
	issues, err := f.app.FindCollectionByNameOrId("issues")
	if err != nil {
		t.Fatal(err)
	}
	issues.Fields.Add(&core.RelationField{Name: "parent", CollectionId: issues.Id, MaxSelect: 1}, &core.TextField{Name: "state"})
	if err := f.app.Save(issues); err != nil {
		t.Fatal(err)
	}
	registerIssueTreeGuard(f.app)
	return f
}

func treeIssue(t *testing.T, f teamRefFixture, team, title, parent, state string) *core.Record {
	t.Helper()
	return f.rec(t, "issues", map[string]any{"team": team, "title": title, "parent": parent, "state": state})
}

func TestIssueTreeRejectsCyclesAndCrossTeamParents(t *testing.T) {
	f := treeFixture(t)
	a := treeIssue(t, f, f.alpha.Id, "root", "", "todo")
	b := treeIssue(t, f, f.alpha.Id, "child", a.Id, "todo")
	c := treeIssue(t, f, f.alpha.Id, "grandchild", b.Id, "todo")
	a.Set("parent", c.Id)
	if err := f.app.Save(a); err == nil || !strings.Contains(err.Error(), "cycle") {
		t.Fatalf("ancestor cycle: %v", err)
	}
	a = f.fresh(t, a)
	a.Set("parent", a.Id)
	if err := f.app.Save(a); err == nil {
		t.Fatal("self parent accepted")
	}
	other := treeIssue(t, f, f.beta.Id, "other team", "", "todo")
	b = f.fresh(t, b)
	b.Set("parent", other.Id)
	if err := f.app.Save(b); err == nil {
		t.Fatal("cross-team parent accepted")
	}
}

func TestIssueTreeReparentAndDeleteKeepDescendants(t *testing.T) {
	f := treeFixture(t)
	a := treeIssue(t, f, f.alpha.Id, "root", "", "todo")
	b := treeIssue(t, f, f.alpha.Id, "child", a.Id, "todo")
	c := treeIssue(t, f, f.alpha.Id, "grandchild", b.Id, "todo")
	d := treeIssue(t, f, f.alpha.Id, "new root", "", "todo")
	b.Set("parent", d.Id)
	if err := f.app.Save(b); err != nil {
		t.Fatal(err)
	}
	if f.fresh(t, c).GetString("parent") != b.Id {
		t.Fatal("reparent detached grandchild")
	}
	if err := f.app.Delete(d); err != nil {
		t.Fatal(err)
	}
	if f.fresh(t, b).GetString("parent") != "" || f.fresh(t, c).GetString("parent") != b.Id {
		t.Fatal("parent deletion did not detach only its children")
	}
	// Arbitrary depth is the default: no implicit depth-three cap.
	parent := c.Id
	for n := 0; n < 8; n++ {
		parent = treeIssue(t, f, f.alpha.Id, "deeper", parent, "todo").Id
	}
}

func TestIssueTreeCloseChecksOpenDescendantsAndForce(t *testing.T) {
	f := treeFixture(t)
	a := treeIssue(t, f, f.alpha.Id, "root", "", "todo")
	b := treeIssue(t, f, f.alpha.Id, "closed child", a.Id, "done")
	treeIssue(t, f, f.alpha.Id, "open grandchild", b.Id, "todo")
	for _, state := range []string{"done", "cancelled"} {
		a = f.fresh(t, a)
		a.Set("state", state)
		if err := f.app.Save(a); err == nil {
			t.Fatalf("%s with an open descendant accepted", state)
		}
	}
	a = f.fresh(t, a)
	a.Set("state", "done")
	a.Set(treeForceCloseKey, true)
	if err := f.app.Save(a); err != nil {
		t.Fatal(err)
	}
}

func TestIssueTreeConcurrentReparentsCannotFormCycle(t *testing.T) {
	f := treeFixture(t)
	a := treeIssue(t, f, f.alpha.Id, "A", "", "todo")
	b := treeIssue(t, f, f.alpha.Id, "B", "", "todo")
	a.Set("parent", b.Id)
	b.Set("parent", a.Id)
	start := make(chan struct{})
	outcomes := make(chan error, 2)
	var workers sync.WaitGroup
	for _, record := range []*core.Record{a, b} {
		workers.Add(1)
		go func(r *core.Record) { defer workers.Done(); <-start; outcomes <- f.app.Save(r) }(record)
	}
	close(start)
	workers.Wait()
	close(outcomes)
	accepted := 0
	for err := range outcomes {
		if err == nil {
			accepted++
		}
	}
	if accepted != 1 {
		t.Fatalf("concurrent reciprocal parents: %d writes accepted, want one", accepted)
	}
}

func TestIssueTreeParentHiddenAndMissingRefuseIdentically(t *testing.T) {
	for _, method := range []string{http.MethodPost, http.MethodPatch} {
		t.Run(method, func(t *testing.T) {
			f := newCreatorFixture(t)
			issues := core.NewBaseCollection("issues")
			issues.Fields.Add(&core.TextField{Name: "title"}, &core.TextField{Name: "team"})
			rule := `@request.auth.id != ""`
			issues.CreateRule, issues.UpdateRule, issues.ViewRule = &rule, &rule, &rule
			if err := f.app.Save(issues); err != nil {
				t.Fatal(err)
			}
			issues.Fields.Add(&core.RelationField{Name: "parent", CollectionId: issues.Id, MaxSelect: 1})
			if err := f.app.Save(issues); err != nil {
				t.Fatal(err)
			}
			makeIssue := func(team, title string) *core.Record {
				r := core.NewRecord(issues)
				r.Set("team", team)
				r.Set("title", title)
				if err := f.app.Save(r); err != nil {
					t.Fatal(err)
				}
				return r
			}
			hidden := makeIssue(f.beta, "hidden title")
			valid := makeIssue(f.alpha, "valid parent")
			child := makeIssue(f.alpha, "child")
			registerScopedRefGuard(f.app)
			registerIssueTreeGuard(f.app)
			token, err := f.coord.NewAuthToken()
			if err != nil {
				t.Fatal(err)
			}
			routes, err := apis.NewRouter(f.app)
			if err != nil {
				t.Fatal(err)
			}
			mux, err := routes.BuildMux()
			if err != nil {
				t.Fatal(err)
			}
			send := func(parent string) (int, string) {
				path := "/api/collections/issues/records"
				if method == http.MethodPatch {
					path += "/" + child.Id
				}
				req := httptest.NewRequest(method, path, strings.NewReader(fmt.Sprintf(`{"title":"probe","team":%q,"parent":%q}`, f.alpha, parent)))
				req.Header.Set("Content-Type", "application/json")
				req.Header.Set("Authorization", "Bearer "+token)
				out := httptest.NewRecorder()
				mux.ServeHTTP(out, req)
				return out.Code, out.Body.String()
			}
			hiddenCode, hiddenBody := send(hidden.Id)
			missingCode, missingBody := send("xxxxxxxxxxxxxxx")
			if hiddenCode != 400 || missingCode != 400 || hiddenBody != missingBody {
				t.Fatalf("hidden %d %s; missing %d %s", hiddenCode, hiddenBody, missingCode, missingBody)
			}
			if strings.Contains(hiddenBody, hidden.Id) || strings.Contains(hiddenBody, "hidden title") {
				t.Fatal("hidden parent disclosed")
			}
			if code, body := send(valid.Id); code != 200 {
				t.Fatalf("valid parent refused: %d %s", code, body)
			}
			if code, body := send(""); code != 200 {
				t.Fatalf("parent clear refused: %d %s", code, body)
			}
		})
	}
}
