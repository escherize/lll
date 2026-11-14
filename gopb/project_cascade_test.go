package gopb

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
)

type cascadeFixture struct {
	creatorFixture
	project *core.Record
	issues  []*core.Record
}

func newCascadeFixture(t *testing.T, count int) cascadeFixture {
	t.Helper()
	f := cascadeFixture{creatorFixture: newCreatorFixture(t)}
	projects := core.NewBaseCollection("projects")
	projects.Fields.Add(&core.TextField{Name: "name"}, &core.TextField{Name: "team"})
	if err := f.app.Save(projects); err != nil {
		t.Fatal(err)
	}
	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(&core.TextField{Name: "team"}, &core.TextField{Name: "title"}, &core.TextField{Name: "description"}, &core.NumberField{Name: "number"}, &core.RelationField{Name: "project", CollectionId: projects.Id, MaxSelect: 1})
	if err := f.app.Save(issues); err != nil {
		t.Fatal(err)
	}
	issues.Fields.Add(&core.RelationField{Name: "parent", CollectionId: issues.Id, MaxSelect: 1}, &core.RelationField{Name: "blocked_by", CollectionId: issues.Id, MaxSelect: 999})
	if err := f.app.Save(issues); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"comments", "claims", "favorites"} {
		c := core.NewBaseCollection(name)
		c.Fields.Add(&core.RelationField{Name: "issue", CollectionId: issues.Id, MaxSelect: 1, CascadeDelete: true}, &core.TextField{Name: "body"})
		if err := f.app.Save(c); err != nil {
			t.Fatal(err)
		}
	}
	docs := core.NewBaseCollection("docs")
	docs.Fields.Add(&core.RelationField{Name: "issues", CollectionId: issues.Id, MaxSelect: 999})
	if err := f.app.Save(docs); err != nil {
		t.Fatal(err)
	}
	hooks := core.NewBaseCollection("webhooks")
	hooks.Fields.Add(&core.RelationField{Name: "project", CollectionId: projects.Id, MaxSelect: 1})
	if err := f.app.Save(hooks); err != nil {
		t.Fatal(err)
	}
	f.project = core.NewRecord(projects)
	f.project.Set("name", "Disposable")
	f.project.Set("team", f.alpha)
	if err := f.app.Save(f.project); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < count; i++ {
		r := core.NewRecord(issues)
		r.Set("team", f.alpha)
		r.Set("project", f.project.Id)
		r.Set("title", fmt.Sprintf("Card %d", i))
		r.Set("number", i+1)
		if err := f.app.Save(r); err != nil {
			t.Fatal(err)
		}
		f.issues = append(f.issues, r)
	}
	return f
}
func cascadeHTTP(t *testing.T, f cascadeFixture) func(*core.Record, string, map[string]any) (int, map[string]any) {
	t.Helper()
	routes, err := apis.NewRouter(f.app)
	if err != nil {
		t.Fatal(err)
	}
	registerProjectCascadeRoutes(routes)
	mux, err := routes.BuildMux()
	if err != nil {
		t.Fatal(err)
	}
	return func(actor *core.Record, method string, body map[string]any) (int, map[string]any) {
		raw, _ := json.Marshal(body)
		req := httptest.NewRequest(method, "/api/lll/projects/"+f.project.Id+"/cascade", strings.NewReader(string(raw)))
		req.Header.Set("Content-Type", "application/json")
		if actor != nil {
			token, err := actor.NewStaticAuthToken(time.Hour)
			if err != nil {
				t.Fatal(err)
			}
			req.Header.Set("Authorization", "Bearer "+token)
		}
		out := httptest.NewRecorder()
		mux.ServeHTTP(out, req)
		var data map[string]any
		if err := json.Unmarshal(out.Body.Bytes(), &data); err != nil {
			t.Fatal(err)
		}
		return out.Code, data
	}
}
func (f cascadeFixture) ref(t *testing.T, collection, field string, value any) *core.Record {
	t.Helper()
	c, err := f.app.FindCollectionByNameOrId(collection)
	if err != nil {
		t.Fatal(err)
	}
	r := core.NewRecord(c)
	r.Set(field, value)
	if collection == "issues" {
		r.Set("team", f.alpha)
	}
	if err := f.app.Save(r); err != nil {
		t.Fatal(err)
	}
	return r
}
func TestProjectCascadePreviewIsReadOnlyAndIncludesEveryIssue(t *testing.T) {
	f := newCascadeFixture(t, 205)
	request := cascadeHTTP(t, f)
	before, _ := json.Marshal(f.project.PublicExport())
	code, preview := request(f.human, "GET", nil)
	if code != 200 || len(preview["issues"].([]any)) != 205 || len(preview["blockers"].([]any)) != 0 {
		t.Fatalf("preview: %d", code)
	}
	after, _ := f.app.FindRecordById("projects", f.project.Id)
	raw, _ := json.Marshal(after.PublicExport())
	if string(raw) != string(before) {
		t.Fatal("preview changed project")
	}
	code, result := request(f.human, "POST", map[string]any{"revision": preview["revision"]})
	if code != 200 || result["deleted"] != true {
		t.Fatalf("cascade: %d %v", code, result)
	}
	rows, _ := f.app.FindAllRecords("issues")
	if len(rows) != 0 {
		t.Fatal("cascade truncated its issue set")
	}
	if _, err := f.app.FindRecordById("projects", f.project.Id); err == nil {
		t.Fatal("project remains")
	}
}
func TestProjectCascadeRejectsStaleCommentsClaimsAndExternalReferences(t *testing.T) {
	for _, kind := range []string{"comment", "new-issue", "edit", "claim", "child", "blocker", "doc", "webhook"} {
		t.Run(kind, func(t *testing.T) {
			f := newCascadeFixture(t, 2)
			request := cascadeHTTP(t, f)
			_, old := request(f.human, "GET", nil)
			switch kind {
			case "comment":
				f.ref(t, "comments", "issue", f.issues[0].Id)
			case "new-issue":
				f.ref(t, "issues", "project", f.project.Id)
			case "edit":
				f.issues[0].Set("description", "Unseen work")
				if err := f.app.Save(f.issues[0]); err != nil {
					t.Fatal(err)
				}
			case "claim":
				f.ref(t, "claims", "issue", f.issues[0].Id)
			case "child":
				f.ref(t, "issues", "parent", f.issues[0].Id)
			case "blocker":
				f.ref(t, "issues", "blocked_by", []string{f.issues[0].Id})
			case "doc":
				f.ref(t, "docs", "issues", []string{f.issues[0].Id})
			case "webhook":
				f.ref(t, "webhooks", "project", f.project.Id)
			}
			code, _ := request(f.human, "POST", map[string]any{"revision": old["revision"]})
			if code != 409 {
				t.Fatalf("stale %s: %d", kind, code)
			}
			_, fresh := request(f.human, "GET", nil)
			if kind != "comment" && kind != "new-issue" && kind != "edit" {
				code, _ = request(f.human, "POST", map[string]any{"revision": fresh["revision"]})
				if code != 409 {
					t.Fatalf("unresolved %s: %d", kind, code)
				}
			}
			if _, err := f.app.FindRecordById("projects", f.project.Id); err != nil {
				t.Fatal("refusal removed project")
			}
			for _, r := range f.issues {
				if _, err := f.app.FindRecordById("issues", r.Id); err != nil {
					t.Fatal("partial removal")
				}
			}
		})
	}
}
func TestProjectCascadeAuthorizationAndRollback(t *testing.T) {
	f := newCascadeFixture(t, 3)
	request := cascadeHTTP(t, f)
	_, preview := request(f.human, "GET", nil)
	body := map[string]any{"revision": preview["revision"]}
	if code, _ := request(nil, "GET", nil); code != 401 {
		t.Fatal(code)
	}
	f.coord.Set("teams", []string{f.beta})
	if err := f.app.Save(f.coord); err != nil {
		t.Fatal(err)
	}
	for _, method := range []string{"GET", "POST"} {
		if code, _ := request(f.coord, method, body); code != 404 {
			t.Fatalf("hidden project: %d", code)
		}
	}
	f.human.Set("mode", "ro")
	if err := f.app.Save(f.human); err != nil {
		t.Fatal(err)
	}
	if code, _ := request(f.human, "GET", nil); code != 200 {
		t.Fatal("readonly preview refused")
	}
	if code, _ := request(f.human, "POST", body); code != 403 {
		t.Fatal("readonly execution allowed")
	}
	f.human.Set("mode", "rw")
	if err := f.app.Save(f.human); err != nil {
		t.Fatal(err)
	}
	comment := f.ref(t, "comments", "issue", f.issues[0].Id)
	_, preview = request(f.human, "GET", nil)
	body["revision"] = preview["revision"]
	n := 0
	f.app.OnRecordDelete("issues").BindFunc(func(e *core.RecordEvent) error {
		if err := e.Next(); err != nil {
			return err
		}
		n++
		if n == 2 {
			return errors.New("injected second delete failure")
		}
		return nil
	})
	if code, _ := request(f.human, "POST", body); code != 500 {
		t.Fatalf("rollback status %d", code)
	}
	for _, r := range f.issues {
		if _, err := f.app.FindRecordById("issues", r.Id); err != nil {
			t.Fatal("partial deletion committed")
		}
	}
	if _, err := f.app.FindRecordById("comments", comment.Id); err != nil {
		t.Fatal("cascaded comment survived rollback incorrectly")
	}
	if _, err := f.app.FindRecordById("projects", f.project.Id); err != nil {
		t.Fatal("project lost on rollback")
	}
}

func TestProjectCascadeRechecksQueuedIdentity(t *testing.T) {
	f := newCascadeFixture(t, 1)
	captured, err := f.app.FindRecordById("members", f.coord.Id)
	if err != nil {
		t.Fatal(err)
	}
	f.coord.Set("teams", []string{f.beta})
	if err := f.app.Save(f.coord); err != nil {
		t.Fatal(err)
	}
	if _, _, err := prepareProjectCascade(f.app, captured, f.project.Id); err == nil {
		t.Fatal("queued old team grant remained authoritative")
	}
	f.coord.Set("teams", []string{f.alpha})
	f.coord.RefreshTokenKey()
	if err := f.app.Save(f.coord); err != nil {
		t.Fatal(err)
	}
	if _, _, err := prepareProjectCascade(f.app, captured, f.project.Id); err == nil {
		t.Fatal("queued retired token remained authoritative")
	}
}

func TestProjectCascadeAndNewClaimSerializeWithoutUnclaimedDeletion(t *testing.T) {
	for round := 0; round < 8; round++ {
		f := newCascadeFixture(t, 1)
		request := cascadeHTTP(t, f)
		_, preview := request(f.human, "GET", nil)
		start := make(chan struct{})
		claimed := make(chan error, 1)
		deleted := make(chan int, 1)
		go func() {
			<-start
			claimed <- f.app.RunInTransaction(func(tx core.App) error {
				collection, err := tx.FindCollectionByNameOrId("claims")
				if err != nil {
					return err
				}
				record := core.NewRecord(collection)
				record.Set("issue", f.issues[0].Id)
				return tx.Save(record)
			})
		}()
		go func() {
			<-start
			code, _ := request(f.human, "POST", map[string]any{"revision": preview["revision"]})
			deleted <- code
		}()
		close(start)
		claimErr, code := <-claimed, <-deleted
		if claimErr == nil {
			if code != 409 {
				t.Fatalf("claim committed but cascade status %d", code)
			}
			if _, err := f.app.FindRecordById("issues", f.issues[0].Id); err != nil {
				t.Fatal("claimed issue deleted")
			}
		} else if code != 200 {
			t.Fatalf("neither operation committed: cascade %d", code)
		}
	}
}
