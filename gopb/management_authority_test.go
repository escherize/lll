package gopb

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
)

func TestNativeManagementRefusesDepartedAuthority(t *testing.T) {
	for _, operation := range []string{"team-create", "team-update", "team-delete", "person-create", "profile-update"} {
		for _, change := range []string{"unchanged", "retired", "admin-demoted", "legacy-narrowed"} {
			if operation == "profile-update" && change != "retired" && change != "unchanged" {
				continue
			}
			t.Run(operation+"/"+change, func(t *testing.T) {
				f := newCreatorFixture(t)
				f.members.Fields.Add(&core.TextField{Name: "workspace_role"})
				rule := `@request.auth.id != ""`
				f.members.CreateRule = &rule
				f.members.UpdateRule = &rule
				if err := f.app.Save(f.members); err != nil {
					t.Fatal(err)
				}
				actor := f.reload(t, f.human)
				if change != "legacy-narrowed" {
					actor.Set("scope", "teams")
					actor.Set("teams", []string{})
					actor.Set("mode", "ro")
					actor.Set("workspace_role", "admin")
				}
				if err := f.app.Save(actor); err != nil {
					t.Fatal(err)
				}
				teams, err := f.app.FindCollectionByNameOrId("teams")
				if err != nil {
					t.Fatal(err)
				}
				teams.CreateRule = &rule
				teams.UpdateRule = &rule
				teams.DeleteRule = &rule
				if err := f.app.Save(teams); err != nil {
					t.Fatal(err)
				}
				entered, resume := make(chan struct{}), make(chan struct{})
				pause := func(e *core.RecordRequestEvent) error { close(entered); <-resume; return e.Next() }
				switch operation {
				case "team-create":
					f.app.OnRecordCreateRequest("teams").BindFunc(pause)
				case "team-update":
					f.app.OnRecordUpdateRequest("teams").BindFunc(pause)
				case "team-delete":
					f.app.OnRecordDeleteRequest("teams").BindFunc(pause)
				case "person-create":
					f.app.OnRecordCreateRequest("members").BindFunc(pause)
				case "profile-update":
					f.app.OnRecordUpdateRequest("members").BindFunc(pause)
				}
				registerMemberUpdateTx(f.app)
				registerArchivedTeamGuard(f.app)
				token, err := actor.NewAuthToken()
				if err != nil {
					t.Fatal(err)
				}
				method, path, body := http.MethodPost, "/api/collections/teams/records", `{"key":"NEW"}`
				switch operation {
				case "team-update":
					method = http.MethodPatch
					path += "/" + f.alpha
					body = `{"key":"CHANGED"}`
				case "team-delete":
					method = http.MethodDelete
					path += "/" + f.alpha
				case "person-create":
					path = "/api/collections/members/records"
					body = `{"name":"newperson","kind":"person","email":"new@testing.invalid","password":"pw12345678","passwordConfirm":"pw12345678"}`
				case "profile-update":
					method = http.MethodPatch
					path = "/api/collections/members/records/" + actor.Id
					body = `{"emailVisibility":true}`
				}
				routes, err := apis.NewRouter(f.app)
				if err != nil {
					t.Fatal(err)
				}
				mux, err := routes.BuildMux()
				if err != nil {
					t.Fatal(err)
				}
				request := httptest.NewRequest(method, path, strings.NewReader(body))
				request.Header.Set("Content-Type", "application/json")
				request.Header.Set("Authorization", "Bearer "+token)
				result := make(chan *httptest.ResponseRecorder, 1)
				go func() { out := httptest.NewRecorder(); mux.ServeHTTP(out, request); result <- out }()
				select {
				case <-entered:
				case out := <-result:
					t.Fatalf("preflight refused %d %s", out.Code, out.Body)
				case <-time.After(5 * time.Second):
					t.Fatal("no preflight barrier")
				}
				switch change {
				case "retired":
					actor.RefreshTokenKey()
				case "admin-demoted":
					actor.Set("workspace_role", "member")
				case "legacy-narrowed":
					actor.Set("scope", "teams")
					actor.Set("teams", []string{})
				}
				if err := f.app.Save(actor); err != nil {
					close(resume)
					t.Fatal(err)
				}
				close(resume)
				var out *httptest.ResponseRecorder
				select {
				case out = <-result:
				case <-time.After(5 * time.Second):
					t.Fatal("request did not resume")
				}
				want := http.StatusForbidden
				if change == "unchanged" {
					want = http.StatusOK
				}
				if change == "unchanged" && operation == "team-delete" {
					want = http.StatusNoContent
				}
				if change == "retired" {
					want = http.StatusUnauthorized
				}
				if out.Code != want {
					t.Fatalf("%d want%d: %s", out.Code, want, out.Body)
				}
				if change != "unchanged" {
					row, err := f.app.FindRecordById("teams", f.alpha)
					if err != nil || row.GetString("key") != "ALPHA" {
						t.Fatalf("revoked team change persisted: %v", err)
					}
					rows, err := f.app.FindRecordsByFilter("members", `name="newperson"`, "", 0, 0)
					if err != nil || len(rows) > 0 {
						t.Fatalf("revoked person provisioning persisted: %v", err)
					}
				}
			})
		}
	}
}

func TestRetiredOwnerCannotRotateBotCredential(t *testing.T) {
	f := newCreatorFixture(t)
	bot := f.save(t, "bot-rotation", botKind, f.human.Id, "", nil)
	stale := f.reload(t, f.human)
	f.human.RefreshTokenKey()
	if err := f.app.Save(f.human); err != nil {
		t.Fatal(err)
	}
	if token, _, err := rotateBot(f.app, stale, bot.GetString("name"), 3600); err == nil || token != "" {
		t.Fatal("retired owner minted credential")
	}
	fresh := f.reload(t, bot)
	if fresh.TokenKey() != bot.TokenKey() {
		t.Fatal(fmt.Sprintf("refused rotation changed token key for %s", bot.Id))
	}
}

func TestRetainedBotGrantsCanShrinkWithoutBypassingItsBounds(t *testing.T) {
	f := newCreatorFixture(t)
	// Retained raw grants can outlive an owner narrowing; effective grants
	// already intersect the live owner. Cleanup must remove rather than grow them.
	f.human.Set("mode", "ro")
	if err := f.app.Save(f.human); err != nil {
		t.Fatal(err)
	}
	bot := f.reload(t, f.coord)
	bot.Set("teams", []string{})
	if err := f.app.Save(bot); err != nil {
		t.Fatalf("safe access removal refused: %v", err)
	}
	if ownAccess(f.reload(t, bot)).sees(f.alpha) {
		t.Fatal("cleanup did not remove the grant")
	}
	bot = f.reload(t, bot)
	bot.Set("teams", []string{f.alpha})
	if err := f.app.Save(bot); err == nil {
		t.Fatal("narrowing exception regrew a removed grant beyond its owner")
	}
	if _, err := f.create("bot-new-invalid", botKind, f.human.Id, "", &access{teams: []string{f.alpha}, rw: true}); err == nil {
		t.Fatal("narrowing exception admitted a new wider bot")
	}
}
