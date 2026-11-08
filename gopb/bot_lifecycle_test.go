package gopb

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
)

func lifecycleHTTP(t *testing.T, f creatorFixture) func(string, string, string, map[string]any) (int, map[string]any) {
	t.Helper()
	routes, err := apis.NewRouter(f.app)
	if err != nil {
		t.Fatal(err)
	}
	registerBotRoutes(routes)
	mux, err := routes.BuildMux()
	if err != nil {
		t.Fatal(err)
	}
	return func(token, method, path string, body map[string]any) (int, map[string]any) {
		raw, err := json.Marshal(body)
		if err != nil {
			t.Fatal(err)
		}
		req := httptest.NewRequest(method, path, strings.NewReader(string(raw)))
		req.Header.Set("Content-Type", "application/json")
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		out := httptest.NewRecorder()
		mux.ServeHTTP(out, req)
		var result map[string]any
		if err := json.Unmarshal(out.Body.Bytes(), &result); err != nil {
			t.Fatalf("HTTP %d did not return JSON", out.Code)
		}
		return out.Code, result
	}
}

func lifecycleToken(t *testing.T, record *core.Record) string {
	t.Helper()
	token, err := record.NewStaticAuthToken(time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	return token
}

func TestOwnerDisablesBotAndNarrowsItsWorkersWithoutDeletingHistory(t *testing.T) {
	f := newCreatorFixture(t)
	worker := f.save(t, "bot-lifecycle-worker", botKind, f.human.Id, f.coord.Id, nil)
	old := f.mint(t, f.human, f.coord.GetString("name"))
	request := lifecycleHTTP(t, f)
	code, result := request(lifecycleToken(t, f.human), "POST", "/api/lll/bots/disable",
		map[string]any{"id": f.coord.Id, "name": f.coord.GetString("name")})
	if code != 200 {
		t.Fatalf("owner disable: HTTP %d, %v", code, result)
	}
	if f.tokenWorks(old) {
		t.Fatal("disabled bot's previous token still authenticates")
	}
	for _, record := range []*core.Record{f.coord, worker} {
		fresh := f.reload(t, record)
		got := ownAccess(fresh)
		if got.all || got.rw || len(got.teams) != 0 {
			t.Fatalf("%s retained work access: %+v", fresh.GetString("name"), got)
		}
		if fresh.GetString("owner") != f.human.Id {
			t.Fatal("disable changed ownership")
		}
	}
	if result["id"] != f.coord.Id || result["disabled"] != true {
		t.Fatalf("incorrect disable receipt: %v", result)
	}
}

func TestBotLifecycleNeverManagesAnotherOwnersBotOrAPerson(t *testing.T) {
	f := newCreatorFixture(t)
	request := lifecycleHTTP(t, f)
	old := f.mint(t, f.human, f.coord.GetString("name"))
	for _, action := range []string{"disable", "remove"} {
		for _, token := range []string{"", lifecycleToken(t, f.other), old} {
			code, _ := request(token, "POST", "/api/lll/bots/"+action,
				map[string]any{"id": f.coord.Id, "name": f.coord.GetString("name"), "force": true})
			want := 403
			if token == "" {
				want = 401
			}
			if code != want {
				t.Fatalf("unauthorized %s returned HTTP %d", action, code)
			}
			if !f.tokenWorks(old) || f.reload(t, f.coord).GetString("mode") != "rw" {
				t.Fatal("refused lifecycle action changed the bot")
			}
		}
		code, _ := request(lifecycleToken(t, f.human), "POST", "/api/lll/bots/"+action,
			map[string]any{"id": f.human.Id, "name": f.human.GetString("name"), "force": true})
		if code != 404 {
			t.Fatalf("lifecycle %s accepted or disclosed a person: HTTP %d", action, code)
		}
	}
}

func TestOwnerCanRemoveAnUnusedBotAndOldTokensStopWorking(t *testing.T) {
	f := newCreatorFixture(t)
	bot := f.save(t, "bot-lifecycle-remove", botKind, f.human.Id, "", nil)
	old := f.mint(t, f.human, bot.GetString("name"))
	code, result := lifecycleHTTP(t, f)(lifecycleToken(t, f.human), "POST", "/api/lll/bots/remove",
		map[string]any{"id": bot.Id, "name": bot.GetString("name")})
	if code != 200 || result["removed"] != true {
		t.Fatalf("owner remove: HTTP %d, %v", code, result)
	}
	if _, err := f.app.FindRecordById("members", bot.Id); err == nil || f.tokenWorks(old) {
		t.Fatal("removed bot or its token still exists")
	}
}
