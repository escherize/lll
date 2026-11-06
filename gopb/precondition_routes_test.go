package gopb

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
)

// LLL-517: exercise the HTTP boundaries, not direct calls to transaction
// helpers that deliberately do not acquire the router's per-issue lock.
func TestStampedPatchAndClaimRoutesShareTheWriteBoundary(t *testing.T) {
	for _, operation := range []string{"claim", "assignment"} {
		for _, first := range []string{"patch", "custom"} {
			t.Run(operation+"/"+first+"-first", func(t *testing.T) {
				app, issueID, alpha, _ := claimFixture(t)
				issues, err := app.FindCollectionByNameOrId("issues")
				if err != nil {
					t.Fatal(err)
				}
				issues.Fields.Add(&core.AutodateField{Name: "updated", OnCreate: true, OnUpdate: true})
				if err = app.Save(issues); err != nil {
					t.Fatal(err)
				}
				// Make the baseline strictly older without depending on clock sleeps or
				// whether two writes happen within PocketBase's millisecond precision.
				const stamp = "2000-01-01 00:00:00.000Z"
				if _, err = app.DB().NewQuery("UPDATE issues SET updated={:stamp} WHERE id={:id}").Bind(dbx.Params{"stamp": stamp, "id": issueID}).Execute(); err != nil {
					t.Fatal(err)
				}
				supers, err := app.FindCollectionByNameOrId(core.CollectionNameSuperusers)
				if err != nil {
					t.Fatal(err)
				}
				admin := core.NewRecord(supers)
				admin.SetEmail("race@example.test")
				admin.SetPassword("local-race-password")
				if err = app.Save(admin); err != nil {
					t.Fatal(err)
				}
				token, err := admin.NewAuthToken()
				if err != nil {
					t.Fatal(err)
				}

				registerIssuePrecondition(app)
				paused, resume := make(chan struct{}), make(chan struct{})
				var blockOnce, releaseOnce sync.Once
				release := func() { releaseOnce.Do(func() { close(resume) }) }
				block := func() { blockOnce.Do(func() { close(paused); <-resume }) }
				if first == "patch" {
					// This runs after the stamp check and before the native PATCH saves.
					app.OnRecordUpdateRequest("issues").BindFunc(func(e *core.RecordRequestEvent) error { block(); return e.Next() })
				} else {
					// The custom route owns both the issue lock and its transaction here.
					app.OnRecordUpdate("issues").BindFunc(func(e *core.RecordEvent) error { block(); return e.Next() })
				}
				routes, err := apis.NewRouter(app)
				if err != nil {
					t.Fatal(err)
				}
				var locks issueWriteLocks
				registerClaimRoutes(routes, &locks)
				routes.BindFunc(serializeRecordUpdates(&locks))
				mux, err := routes.BuildMux()
				if err != nil {
					t.Fatal(err)
				}
				type result struct {
					code int
					body string
				}
				request := func(patch bool) result {
					method, path, body := http.MethodPost, "/api/lll/issues/"+issueID+"/"+operation, fmt.Sprintf(`{"member":%q,"agent":"racer"}`, alpha)
					if operation == "assignment" {
						body = fmt.Sprintf(`{"claim_id":"","fields":{"assignee":%q}}`, alpha)
					}
					if patch {
						method, path, body = http.MethodPatch, "/api/collections/issues/records/"+issueID, `{"title":"patched"}`
					}
					req := httptest.NewRequest(method, path, strings.NewReader(body))
					req.Header.Set("Content-Type", "application/json")
					req.Header.Set("Authorization", "Bearer "+token)
					if patch {
						req.Header.Set("If-Unmodified-Since", stamp)
					}
					out := httptest.NewRecorder()
					mux.ServeHTTP(out, req)
					return result{out.Code, out.Body.String()}
				}
				var workers sync.WaitGroup
				t.Cleanup(func() { release(); workers.Wait() })
				start := func(patch bool) <-chan result {
					done := make(chan result, 1)
					workers.Add(1)
					go func() { defer workers.Done(); done <- request(patch) }()
					return done
				}
				firstDone := start(first == "patch")
				select {
				case <-paused:
				case r := <-firstDone:
					t.Fatalf("first write did not reach barrier: %+v", r)
				case <-time.After(5 * time.Second):
					t.Fatal("first write never reached barrier")
				}
				secondDone := start(first != "patch")
				// Observe an actual waiter on the same boundary before releasing the
				// first write; a scheduling delay alone is not evidence of exclusion.
				deadline := time.Now().Add(5 * time.Second)
				waiting := false
				for time.Now().Before(deadline) {
					locks.mu.Lock()
					entry := locks.entries[issueID]
					waiting = entry != nil && entry.refs == 2
					locks.mu.Unlock()
					if waiting {
						break
					}
					runtime.Gosched()
				}
				if !waiting {
					t.Fatal("second route did not wait on the same issue lock")
				}
				select {
				case r := <-secondDone:
					t.Fatalf("second write escaped the barrier: %+v", r)
				default:
				}
				release()
				take := func(done <-chan result) result {
					select {
					case r := <-done:
						return r
					case <-time.After(5 * time.Second):
						t.Fatal("write did not complete")
						return result{}
					}
				}
				one, two := take(firstDone), take(secondDone)
				patch, custom := one, two
				if first == "custom" {
					patch, custom = two, one
				}
				wantPatch, wantTitle := http.StatusOK, "patched"
				if first == "custom" {
					wantPatch, wantTitle = http.StatusPreconditionFailed, "preserve title"
				}
				if patch.code != wantPatch || custom.code != http.StatusOK {
					t.Fatalf("patch=%+v custom=%+v", patch, custom)
				}
				saved, err := app.FindRecordById("issues", issueID)
				if err != nil {
					t.Fatal(err)
				}
				if saved.GetString("title") != wantTitle || saved.GetString("assignee") != alpha {
					t.Fatalf("lost write: %v", saved.PublicExport())
				}
				held, err := currentClaim(app, issueID)
				if err != nil {
					t.Fatal(err)
				}
				if operation == "claim" && (held == nil || held.GetString("member") != alpha) {
					t.Fatal("claim was lost")
				}
				if operation == "assignment" && held != nil {
					t.Fatal("assignment invented a claim")
				}
			})
		}
	}
}
