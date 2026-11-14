package gopb

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/hook"
)

// Native rules have admitted the request before this barrier. Commit a
// revocation there, then resume: no departed preflight decision may write.
func TestNativeRecordWriteRechecksAuthorityAfterPreflight(t *testing.T) {
	for _, operation := range []string{"create", "update", "delete"} {
		for _, change := range []string{"unchanged", "viewer", "hidden", "retired", "owner", "source_viewer", "destination_viewer", "moved_source"} {
			t.Run(operation+"/"+change, func(t *testing.T) {
				f := newCreatorFixture(t)
				f.members.Fields.Add(&core.RelationField{Name: "editor_teams", CollectionId: mustTeamCollection(t, f.app), MaxSelect: 99})
				if err := f.app.Save(f.members); err != nil {
					t.Fatal(err)
				}
				c := core.NewBaseCollection("issues")
				c.Fields.Add(&core.TextField{Name: "title"}, &core.TextField{Name: "team"})
				rule := `@request.auth.id != ""`
				c.CreateRule = &rule
				c.UpdateRule = &rule
				c.DeleteRule = &rule
				if err := f.app.Save(c); err != nil {
					t.Fatal(err)
				}
				record := core.NewRecord(c)
				record.Set("title", "preserved")
				record.Set("team", f.alpha)
				if err := f.app.Save(record); err != nil {
					t.Fatal(err)
				}
				caller := f.human
				if change == "owner" {
					caller = f.coord
				}
				token, err := caller.NewAuthToken()
				if err != nil {
					t.Fatal(err)
				}
				entered, resume := make(chan struct{}), make(chan struct{})
				wait := func(e *core.RecordRequestEvent) error { close(entered); <-resume; return e.Next() }
				handler := &hook.Handler[*core.RecordRequestEvent]{Id: "pause-after-preflight", Func: wait}
				switch operation {
				case "create":
					f.app.OnRecordCreateRequest("issues").Bind(handler)
				case "update":
					f.app.OnRecordUpdateRequest("issues").Bind(handler)
				case "delete":
					f.app.OnRecordDeleteRequest("issues").Bind(handler)
				}
				registerArchivedTeamGuard(f.app)
				routes, err := apis.NewRouter(f.app)
				if err != nil {
					t.Fatal(err)
				}
				mux, err := routes.BuildMux()
				if err != nil {
					t.Fatal(err)
				}
				method, path := http.MethodPatch, "/api/collections/issues/records/"+record.Id
				if operation == "create" {
					method = http.MethodPost
					path = "/api/collections/issues/records"
				}
				if operation == "delete" {
					method = http.MethodDelete
				}
				destination := f.alpha
				if change == "source_viewer" || change == "destination_viewer" {
					destination = f.beta
				}
				request := httptest.NewRequest(method, path, strings.NewReader(`{"title":"changed","team":"`+destination+`"}`))
				request.Header.Set("Content-Type", "application/json")
				request.Header.Set("Authorization", "Bearer "+token)
				result := make(chan *httptest.ResponseRecorder, 1)
				go func() { out := httptest.NewRecorder(); mux.ServeHTTP(out, request); result <- out }()
				select {
				case <-entered:
				case out := <-result:
					t.Fatalf("did not reach preflight barrier: %d %s", out.Code, out.Body)
				case <-time.After(5 * time.Second):
					t.Fatal("did not reach preflight barrier")
				}
				switch change {
				case "viewer", "owner":
					f.human.Set("mode", "ro")
				case "hidden":
					f.human.Set("scope", "teams")
					f.human.Set("teams", []string{})
				case "retired":
					f.human.RefreshTokenKey()
				case "source_viewer", "destination_viewer":
					f.human.Set("scope", "teams")
					f.human.Set("mode", "ro")
					f.human.Set("teams", []string{f.alpha, f.beta})
					editor := f.alpha
					if change == "source_viewer" {
						editor = f.beta
					}
					f.human.Set("editor_teams", []string{editor})
				case "moved_source":
					if operation == "create" {
						f.human.Set("scope", "teams")
						f.human.Set("teams", []string{f.beta})
					} else {
						record.Set("team", f.beta)
						if err := f.app.Save(record); err != nil {
							close(resume)
							t.Fatal(err)
						}
						f.human.Set("scope", "teams")
						f.human.Set("teams", []string{f.alpha})
					}
				}
				if err := f.app.Save(f.human); err != nil {
					close(resume)
					t.Fatal(err)
				}
				close(resume)
				var out *httptest.ResponseRecorder
				select {
				case out = <-result:
				case <-time.After(5 * time.Second):
					t.Fatal("write never resumed")
				}
				if change == "unchanged" || (operation == "delete" && change == "destination_viewer") || (operation == "create" && change == "source_viewer") {
					if out.Code >= 300 {
						t.Fatalf("allowed control: %d %s", out.Code, out.Body)
					}
					return
				}
				want := http.StatusForbidden
				if change == "hidden" || change == "moved_source" {
					want = http.StatusNotFound
				}
				if change == "retired" {
					want = http.StatusUnauthorized
				}
				if out.Code != want {
					t.Errorf("departed authority returned %d, want %d: %s", out.Code, want, out.Body)
				}
				rows, err := f.app.FindAllRecords(c)
				if err != nil {
					t.Fatal(err)
				}
				if len(rows) != 1 || rows[0].GetString("title") != "preserved" {
					t.Fatal("revoked native request committed a mutation")
				}
			})
		}
	}
}

func mustTeamCollection(t *testing.T, app core.App) string {
	t.Helper()
	c, err := app.FindCollectionByNameOrId("teams")
	if err != nil {
		t.Fatal(err)
	}
	return c.Id
}
