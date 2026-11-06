package gopb

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
)

// A request paused after its archive check must exclude a concurrent archive
// until its write commits. Otherwise the archive can finish first and the
// already-checked write subsequently changes a read-only team.
func TestNativeArchiveCheckSharesWriteTransaction(t *testing.T) {
	for _, collection := range archivedGuarded {
		for _, action := range []string{"create", "update", "delete"} {
			t.Run(collection+"/"+action, func(t *testing.T) {
				f := newTeamWritesFixture(t)
				data := fmt.Sprintf(`{"team":%q,"name":"before","title":"before"}`, f.live.Id)
				if collection == "comments" || collection == "claims" {
					issue := f.rec(t, "issues", map[string]any{"team": f.live.Id, "title": "parent"})
					data = fmt.Sprintf(`{"issue":%q,"body":"before"}`, issue.Id)
				}
				supers, err := f.app.FindCollectionByNameOrId(core.CollectionNameSuperusers)
				if err != nil {
					t.Fatal(err)
				}
				admin := core.NewRecord(supers)
				admin.SetEmail("archive-race@example.test")
				admin.SetPassword("archive-race-password")
				if err = f.app.Save(admin); err != nil {
					t.Fatal(err)
				}
				token, err := admin.NewAuthToken()
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
				request := func(method, path, body string) int {
					req := httptest.NewRequest(method, path, strings.NewReader(body))
					req.Header.Set("Content-Type", "application/json")
					req.Header.Set("Authorization", "Bearer "+token)
					out := httptest.NewRecorder()
					mux.ServeHTTP(out, req)
					if out.Code != 200 && out.Code != 204 {
						t.Logf("%s %s: %d %s", method, path, out.Code, out.Body.String())
					}
					return out.Code
				}
				path := "/api/collections/" + collection + "/records"
				method := http.MethodPost
				if action != "create" {
					c, _ := f.app.FindCollectionByNameOrId(collection)
					r := core.NewRecord(c)
					if err = r.UnmarshalJSON([]byte(data)); err != nil {
						t.Fatal(err)
					}
					if err = f.app.Save(r); err != nil {
						t.Fatal(err)
					}
					path += "/" + r.Id
					method = http.MethodPatch
					if action == "delete" {
						method = http.MethodDelete
					}
				}
				paused, resume, entered := make(chan bool, 1), make(chan struct{}), make(chan struct{})
				var releaseOnce sync.Once
				release := func() { releaseOnce.Do(func() { close(resume) }) }
				pause := func(e *core.RecordRequestEvent) error { paused <- e.App.IsTransactional(); <-resume; return e.Next() }
				switch action {
				case "create":
					f.app.OnRecordCreateRequest(collection).BindFunc(pause)
				case "update":
					f.app.OnRecordUpdateRequest(collection).BindFunc(pause)
				case "delete":
					f.app.OnRecordDeleteRequest(collection).BindFunc(pause)
				}
				f.app.OnRecordUpdateRequest("teams").BindFunc(func(e *core.RecordRequestEvent) error { close(entered); return e.Next() })
				var workers sync.WaitGroup
				t.Cleanup(func() { release(); workers.Wait() })
				start := func(fn func() int) <-chan int {
					done := make(chan int, 1)
					workers.Add(1)
					go func() { defer workers.Done(); done <- fn() }()
					return done
				}
				write := start(func() int { return request(method, path, data) })
				var transactional bool
				select {
				case transactional = <-paused:
				case <-time.After(5 * time.Second):
					t.Fatal("write never reached post-check barrier")
				}
				archive := start(func() int {
					return request(http.MethodPatch, "/api/collections/teams/records/"+f.live.Id, `{"archived":true}`)
				})
				select {
				case <-entered:
				case <-time.After(5 * time.Second):
					t.Fatal("archive never entered")
				}
				archiveCode := 0
				if !transactional {
					select {
					case archiveCode = <-archive:
					case <-time.After(5 * time.Second):
						t.Fatal("unprotected archive unexpectedly blocked")
					}
				}
				release()
				var writeCode int
				select {
				case writeCode = <-write:
				case <-time.After(5 * time.Second):
					t.Fatal("write never completed")
				}
				if archiveCode == 0 {
					select {
					case archiveCode = <-archive:
					case <-time.After(5 * time.Second):
						t.Fatal("archive never completed")
					}
				}
				if archiveCode != 200 {
					t.Fatalf("archive: %d", archiveCode)
				}
				if !transactional && (writeCode == 200 || writeCode == 204) {
					t.Fatal("write committed after the team archive had already completed")
				}
				if writeCode != 200 && writeCode != 204 {
					t.Fatalf("write: %d", writeCode)
				}
				team, err := f.app.FindRecordById("teams", f.live.Id)
				if err != nil || !team.GetBool("archived") {
					t.Fatalf("archive was not persisted: %v", err)
				}
			})
		}
	}
}
