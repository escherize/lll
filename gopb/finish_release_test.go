package gopb

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
)

// finishFixture is the native PATCH path of the finish rule: two members,
// one issue alpha holds, and the real record route with
// registerFinishRelease bound, as gopb.Run binds it.
type finishFixture struct {
	app         *tests.TestApp
	issue       string
	alpha, beta string
	alphaToken  string
	betaToken   string
	superToken  string
	serve       http.Handler
}

func newFinishFixture(t *testing.T) finishFixture {
	t.Helper()
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Cleanup)
	save := func(r core.Model) {
		t.Helper()
		if err := app.Save(r); err != nil {
			t.Fatal(err)
		}
	}
	members := core.NewAuthCollection("members")
	members.Fields.Add(&core.TextField{Name: "name"})
	save(members)
	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(
		&core.RelationField{Name: "assignee", CollectionId: members.Id, MaxSelect: 1},
		// Required, so a PATCH that empties it fails at the save: the
		// rollback case.
		&core.TextField{Name: "title", Required: true},
		&core.TextField{Name: "state"},
	)
	open := ""
	issues.UpdateRule = &open
	save(issues)
	claims := core.NewBaseCollection("claims")
	claims.Fields.Add(
		&core.RelationField{Name: "issue", CollectionId: issues.Id, MaxSelect: 1, Required: true},
		&core.RelationField{Name: "member", CollectionId: members.Id, MaxSelect: 1, Required: true},
		&core.TextField{Name: "agent"},
	)
	save(claims)

	member := func(name string) (string, string) {
		m := core.NewRecord(members)
		m.SetEmail(name + "@example.test")
		m.SetPassword("password123")
		m.Set("name", name)
		save(m)
		tok, err := m.NewAuthToken()
		if err != nil {
			t.Fatal(err)
		}
		return m.Id, tok
	}
	f := finishFixture{app: app}
	f.alpha, f.alphaToken = member("Alpha")
	f.beta, f.betaToken = member("Beta")
	supers, err := app.FindCachedCollectionByNameOrId(core.CollectionNameSuperusers)
	if err != nil {
		t.Fatal(err)
	}
	su := core.NewRecord(supers)
	su.SetEmail("su@example.test")
	su.SetPassword("password123")
	save(su)
	if f.superToken, err = su.NewAuthToken(); err != nil {
		t.Fatal(err)
	}

	issue := core.NewRecord(issues)
	issue.Set("title", "work")
	issue.Set("state", "in-progress")
	issue.Set("assignee", f.alpha)
	save(issue)
	f.issue = issue.Id

	registerFinishRelease(app)
	baseRouter, err := apis.NewRouter(app)
	if err != nil {
		t.Fatal(err)
	}
	serveEvent := new(core.ServeEvent)
	serveEvent.App = app
	serveEvent.Router = baseRouter
	if err := app.OnServe().Trigger(serveEvent, func(e *core.ServeEvent) error { return nil }); err != nil {
		t.Fatal(err)
	}
	if f.serve, err = baseRouter.BuildMux(); err != nil {
		t.Fatal(err)
	}
	return f
}

func (f finishFixture) claim(t *testing.T, agent string) {
	t.Helper()
	claims, err := f.app.FindCachedCollectionByNameOrId("claims")
	if err != nil {
		t.Fatal(err)
	}
	c := core.NewRecord(claims)
	c.Set("issue", f.issue)
	c.Set("member", f.alpha)
	c.Set("agent", agent)
	if err := f.app.Save(c); err != nil {
		t.Fatal(err)
	}
}

func (f finishFixture) patch(t *testing.T, token, query, body string) int {
	t.Helper()
	req := httptest.NewRequest(http.MethodPatch, "/api/collections/issues/records/"+f.issue+query, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", token)
	rec := httptest.NewRecorder()
	f.serve.ServeHTTP(rec, req)
	return rec.Code
}

func (f finishFixture) state(t *testing.T) (state string, held bool) {
	t.Helper()
	issue, err := f.app.FindRecordById("issues", f.issue)
	if err != nil {
		t.Fatal(err)
	}
	claim, err := currentClaim(f.app, f.issue)
	if err != nil {
		t.Fatal(err)
	}
	if issue.GetString("assignee") != f.alpha {
		t.Fatalf("the assignee changed: %q", issue.GetString("assignee"))
	}
	return issue.GetString("state"), claim != nil
}

func (f finishFixture) reopen(t *testing.T) {
	t.Helper()
	issue, err := f.app.FindRecordById("issues", f.issue)
	if err != nil {
		t.Fatal(err)
	}
	issue.Set("state", "in-progress")
	if err := f.app.Save(issue); err != nil {
		t.Fatal(err)
	}
}

func TestPatchToATerminalStateReleasesOnlyTheHoldersClaim(t *testing.T) {
	f := newFinishFixture(t)
	f.claim(t, "wt-a")

	// Not a finish: the claim stays.
	if code := f.patch(t, f.alphaToken, "", `{"state":"in-review"}`); code != 200 {
		t.Fatalf("in-review: %d", code)
	}
	if _, held := f.state(t); !held {
		t.Fatal("a move to in-review released the claim")
	}
	f.reopen(t)

	// Anyone else: another member, another agent label, a superuser.
	for _, c := range []struct{ name, token, query string }{
		{"another member", f.betaToken, ""},
		{"another agent label", f.alphaToken, "?agent=wt-b"},
		{"a superuser", f.superToken, ""},
	} {
		if code := f.patch(t, c.token, c.query, `{"state":"done"}`); code != 200 {
			t.Fatalf("%s: %d", c.name, code)
		}
		if _, held := f.state(t); !held {
			t.Fatalf("%s's move to done released the holder's claim", c.name)
		}
		f.reopen(t)
	}

	// The holder opting out.
	if code := f.patch(t, f.alphaToken, "?agent=wt-a&keep_claim=true", `{"state":"done"}`); code != 200 {
		t.Fatalf("keep_claim: %d", code)
	}
	if _, held := f.state(t); !held {
		t.Fatal("keep_claim released the claim")
	}
	f.reopen(t)

	// A failed save rolls the release back.
	if code := f.patch(t, f.alphaToken, "", `{"state":"done","title":""}`); code != 400 {
		t.Fatalf("invalid save: %d", code)
	}
	if state, held := f.state(t); !held || state != "in-progress" {
		t.Fatalf("a refused save still released the claim (state %q, held %v)", state, held)
	}

	// A malformed label is refused.
	if code := f.patch(t, f.alphaToken, "?agent=bad%20label", `{"state":"done"}`); code != 400 {
		t.Fatalf("malformed agent: %d", code)
	}

	// The holder, unlabelled: released, assignee kept (state checks it).
	if code := f.patch(t, f.alphaToken, "", `{"state":"cancelled"}`); code != 200 {
		t.Fatalf("holder: %d", code)
	}
	if state, held := f.state(t); held || state != "cancelled" {
		t.Fatalf("holder's cancel: state %q, held %v", state, held)
	}
}
