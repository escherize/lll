package gopb

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
)

func TestClaimRoutesRecheckArchiveAfterWaitingForIssue(t *testing.T) {
	for _, operation := range []string{"claim", "release", "renew", "assignment", "close"} {
		t.Run(operation, func(t *testing.T) {
			f := newCreatorFixture(t)
			teams, err := f.app.FindCollectionByNameOrId("teams")
			if err != nil {
				t.Fatal(err)
			}
			teams.Fields.Add(&core.BoolField{Name: "archived"})
			if err = f.app.Save(teams); err != nil {
				t.Fatal(err)
			}
			issues := core.NewBaseCollection("issues")
			issues.Fields.Add(&core.TextField{Name: "title"}, &core.TextField{Name: "state"}, &core.TextField{Name: "team"}, &core.RelationField{Name: "assignee", CollectionId: f.members.Id, MaxSelect: 1})
			if err = f.app.Save(issues); err != nil {
				t.Fatal(err)
			}
			claims := core.NewBaseCollection("claims")
			claims.Fields.Add(&core.RelationField{Name: "issue", CollectionId: issues.Id, MaxSelect: 1}, &core.RelationField{Name: "member", CollectionId: f.members.Id, MaxSelect: 1}, &core.TextField{Name: "agent"}, &core.AutodateField{Name: "created", OnCreate: true}, &core.AutodateField{Name: "updated", OnCreate: true, OnUpdate: true})
			if err = f.app.Save(claims); err != nil {
				t.Fatal(err)
			}
			issue := core.NewRecord(issues)
			issue.Set("title", "preserve")
			issue.Set("state", "in-progress")
			issue.Set("team", f.alpha)
			if err = f.app.Save(issue); err != nil {
				t.Fatal(err)
			}
			claimID := ""
			if operation != "claim" {
				out, err := acquireClaim(f.app, issue.Id, f.human.Id, "racer")
				if err != nil {
					t.Fatal(err)
				}
				claimID = out.ClaimID
				if _, err = f.app.DB().NewQuery("UPDATE claims SET updated='2000-01-01 00:00:00.000Z'").Execute(); err != nil {
					t.Fatal(err)
				}
			}
			snapshot := func() string {
				row, err := f.app.FindRecordById("issues", issue.Id)
				if err != nil {
					t.Fatal(err)
				}
				held, err := currentClaim(f.app, issue.Id)
				if err != nil {
					t.Fatal(err)
				}
				data := []any{row.PublicExport(), nil}
				if held != nil {
					data[1] = held.PublicExport()
				}
				raw, err := json.Marshal(data)
				if err != nil {
					t.Fatal(err)
				}
				return string(raw)
			}
			before := snapshot()
			token, err := f.human.NewAuthToken()
			if err != nil {
				t.Fatal(err)
			}
			var locks issueWriteLocks
			routes, err := apis.NewRouter(f.app)
			if err != nil {
				t.Fatal(err)
			}
			registerClaimRoutes(routes, &locks)
			mux, err := routes.BuildMux()
			if err != nil {
				t.Fatal(err)
			}
			body := fmt.Sprintf(`{"claim_id":%q,"agent":"racer"}`, claimID)
			if operation == "claim" {
				body = `{"agent":"racer"}`
			}
			if operation == "assignment" {
				body = fmt.Sprintf(`{"claim_id":%q,"agent":"racer","fields":{"assignee":%q,"title":"changed"}}`, claimID, f.human.Id)
			}
			unlock := locks.acquire(issue.Id)
			var once sync.Once
			release := func() { once.Do(unlock) }
			var workers sync.WaitGroup
			t.Cleanup(func() { release(); workers.Wait() })
			result := make(chan int, 1)
			workers.Add(1)
			go func() {
				defer workers.Done()
				req := httptest.NewRequest(http.MethodPost, "/api/lll/issues/"+issue.Id+"/"+operation, strings.NewReader(body))
				req.Header.Set("Content-Type", "application/json")
				req.Header.Set("Authorization", "Bearer "+token)
				out := httptest.NewRecorder()
				mux.ServeHTTP(out, req)
				result <- out.Code
			}()
			deadline := time.Now().Add(5 * time.Second)
			waiting := false
			for time.Now().Before(deadline) {
				locks.mu.Lock()
				entry := locks.entries[issue.Id]
				waiting = entry != nil && entry.refs == 2
				locks.mu.Unlock()
				if waiting {
					break
				}
				select {
				case code := <-result:
					t.Fatalf("request returned before reaching lock: %d", code)
				default:
				}
				runtime.Gosched()
			}
			if !waiting {
				t.Fatal("request never waited on the held issue lock")
			}
			// This commit is definitely after preflight and before the operation.
			team, err := f.app.FindRecordById("teams", f.alpha)
			if err != nil {
				t.Fatal(err)
			}
			team.Set("archived", true)
			if err = f.app.Save(team); err != nil {
				t.Fatal(err)
			}
			release()
			select {
			case code := <-result:
				if code != http.StatusForbidden {
					t.Errorf("write after archive returned %d, want 403", code)
				}
			case <-time.After(5 * time.Second):
				t.Fatal("request never completed")
			}
			if after := snapshot(); after != before {
				t.Fatal("request changed issue or claim after archive completed")
			}
		})
	}
}
