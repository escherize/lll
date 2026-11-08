package gopb

import (
	"encoding/json"
	"errors"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
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

func TestBotRemovalProtectsReferencesAndForceKeepsBodiesAndOtherRelations(t *testing.T) {
	f := newCreatorFixture(t)
	bot := f.save(t, "bot-lifecycle-history", botKind, f.human.Id, "", nil)
	history := core.NewBaseCollection("bot_history")
	history.Fields.Add(&core.TextField{Name: "body"},
		&core.RelationField{Name: "reviewers", CollectionId: f.members.Id, MaxSelect: 9})
	if err := f.app.Save(history); err != nil {
		t.Fatal(err)
	}
	note := core.NewRecord(history)
	note.Set("body", "Keep the evidence")
	note.Set("reviewers", []string{bot.Id, f.other.Id})
	if err := f.app.Save(note); err != nil {
		t.Fatal(err)
	}
	request := lifecycleHTTP(t, f)
	token := lifecycleToken(t, f.human)
	code, preview := request(token, "GET", "/api/lll/bots/owned?name="+bot.GetString("name"), nil)
	if code != 200 || preview["has_references"] != true {
		t.Fatalf("owned preview did not disclose its reference safeguard: %d, %v", code, preview)
	}
	body := map[string]any{"id": bot.Id, "name": bot.GetString("name")}
	code, _ = request(token, "POST", "/api/lll/bots/remove", body)
	if code != 409 {
		t.Fatalf("referenced bot removal without force returned %d", code)
	}
	f.reload(t, bot)
	code, _ = request(token, "DELETE", "/api/collections/members/records/"+bot.Id, nil)
	if code != 403 {
		t.Fatalf("generic member deletion was broadened: %d", code)
	}
	body["force"] = true
	code, result := request(token, "POST", "/api/lll/bots/remove", body)
	if code != 200 || result["had_references"] != true {
		t.Fatalf("explicit forced removal returned %d, %v", code, result)
	}
	kept, err := f.app.FindRecordById(history, note.Id)
	if err != nil || kept.GetString("body") != "Keep the evidence" {
		t.Fatal("forced removal lost the written evidence")
	}
	reviewers := kept.GetStringSlice("reviewers")
	if len(reviewers) != 1 || reviewers[0] != f.other.Id {
		t.Fatalf("removal changed another account's reference: %v", reviewers)
	}
}

func TestReadOnlyOwnerCanNarrowItsBotWithoutChangingItsOwnGrants(t *testing.T) {
	f := newCreatorFixture(t)
	owner := f.save(t, "read-only-owner", "person", "", "", &access{all: true, rw: false})
	bot := f.save(t, "bot-read-only-owner", botKind, owner.Id, "", &access{teams: []string{f.alpha}, rw: false})
	old := f.mint(t, owner, bot.GetString("name"))
	code, _ := lifecycleHTTP(t, f)(lifecycleToken(t, owner), "POST", "/api/lll/bots/disable",
		map[string]any{"id": bot.Id, "name": bot.GetString("name")})
	if code != 200 || f.tokenWorks(old) {
		t.Fatalf("read-only owner's narrowing failed: %d", code)
	}
	after := ownAccess(f.reload(t, owner))
	if !after.all || after.rw {
		t.Fatal("bot management changed the owner's grants")
	}
}

func TestOwnedLookupHidesForeignBotsAndRequiresTheOriginalIdentity(t *testing.T) {
	f := newCreatorFixture(t)
	narrow := f.save(t, "narrow-outsider", "person", "", "", &access{teams: []string{f.beta}, rw: true})
	request := lifecycleHTTP(t, f)
	code, hidden := request(lifecycleToken(t, narrow), "GET", "/api/lll/bots/owned?name=bot-coord", nil)
	missingCode, missing := request(lifecycleToken(t, narrow), "GET", "/api/lll/bots/owned?name=bot-missing", nil)
	if code != 404 || missingCode != code || hidden["message"] != missing["message"] {
		t.Fatal("owned lookup disclosed a hidden foreign bot")
	}
	changed := f.reload(t, f.coord)
	changed.Set("name", "bot-renamed")
	changed.SetEmail("bot-renamed@members.invalid")
	if err := f.app.Save(changed); err != nil {
		t.Fatal(err)
	}
	replacement := f.save(t, "bot-coord", botKind, f.human.Id, "", nil)
	code, _ = request(lifecycleToken(t, f.human), "POST", "/api/lll/bots/disable",
		map[string]any{"id": changed.Id, "name": "bot-coord"})
	if code != 409 || f.reload(t, replacement).GetString("mode") != "rw" || f.reload(t, changed).GetString("mode") != "rw" {
		t.Fatal("a stale id/name pair changed the original or its replacement")
	}
}

func TestBotLifecycleRechecksTransferredOwnershipAndRetiredCallerCredentials(t *testing.T) {
	for _, change := range []string{"owner transferred", "caller credential retired"} {
		t.Run(change, func(t *testing.T) {
			f := newCreatorFixture(t)
			staleCaller := f.reload(t, f.human)
			want := 403
			if change == "owner transferred" {
				bot := f.reload(t, f.coord)
				bot.Set("owner", f.other.Id)
				if err := f.app.Save(bot); err != nil {
					t.Fatal(err)
				}
			} else {
				want = 401
				fresh := f.reload(t, f.human)
				fresh.RefreshTokenKey()
				if err := f.app.Save(fresh); err != nil {
					t.Fatal(err)
				}
			}
			before := f.reload(t, f.coord)
			_, err := manageOwnedBot(f.app, staleCaller, f.coord.Id, "bot-coord", "disable", false)
			var api *router.ApiError
			if !errors.As(err, &api) || api.Status != want {
				t.Fatalf("stale authorization returned %v, expected HTTP %d", err, want)
			}
			after := f.reload(t, f.coord)
			if before.TokenKey() != after.TokenKey() || before.GetString("mode") != after.GetString("mode") {
				t.Fatal("stale authorization changed the bot")
			}
		})
	}
}

func TestFailedBotDisableRollsBackTokensAndWorkerAccess(t *testing.T) {
	f := newCreatorFixture(t)
	worker := f.save(t, "bot-rollback-worker", botKind, f.human.Id, f.coord.Id, nil)
	old := f.mint(t, f.human, "bot-coord")
	f.app.OnRecordUpdate("members").BindFunc(func(e *core.RecordEvent) error {
		if err := e.Next(); err != nil {
			return err
		}
		if e.Record.Id == f.coord.Id && e.Record.GetString("mode") == "ro" {
			if !e.App.IsTransactional() {
				t.Error("disable escaped its writer transaction")
			}
			return errors.New("synthetic post-save failure")
		}
		return nil
	})
	code, _ := lifecycleHTTP(t, f)(lifecycleToken(t, f.human), "POST", "/api/lll/bots/disable",
		map[string]any{"id": f.coord.Id, "name": "bot-coord"})
	if code != 500 || !f.tokenWorks(old) {
		t.Fatalf("failed disable did not restore the old credential: HTTP %d", code)
	}
	for _, record := range []*core.Record{f.coord, worker} {
		got := ownAccess(f.reload(t, record))
		if !got.rw || len(got.teams) != 1 || got.teams[0] != f.alpha {
			t.Fatalf("failed disable left narrowed access: %+v", got)
		}
	}
}

func TestForcedCreatorRemovalKeepsWorkersNarrowAndRetiresItsMintedTokens(t *testing.T) {
	f := newCreatorFixture(t)
	worker := f.save(t, "bot-kept-worker", botKind, f.human.Id, f.coord.Id, nil)
	old := f.mint(t, f.coord, worker.GetString("name"))
	request := lifecycleHTTP(t, f)
	body := map[string]any{"id": f.coord.Id, "name": "bot-coord"}
	owner := lifecycleToken(t, f.human)
	if code, _ := request(owner, "POST", "/api/lll/bots/remove", body); code != 409 {
		t.Fatalf("creator references were not protected: %d", code)
	}
	body["force"] = true
	if code, _ := request(owner, "POST", "/api/lll/bots/remove", body); code != 200 {
		t.Fatalf("owner could not explicitly remove the creator: %d", code)
	}
	kept := f.reload(t, worker)
	got := ownAccess(kept)
	if kept.GetString("owner") != f.human.Id || kept.GetString("created_by") != "" ||
		got.all || !got.rw || len(got.teams) != 1 || got.teams[0] != f.alpha || f.tokenWorks(old) {
		t.Fatal("creator removal widened/deleted the worker or kept its old credential")
	}
	f.mint(t, f.human, worker.GetString("name"))
}

func TestFailedBotRemovalRestoresRecordsRelationsAndCredentials(t *testing.T) {
	f := newCreatorFixture(t)
	worker := f.save(t, "bot-kept-on-failure", botKind, f.human.Id, f.coord.Id, nil)
	old := f.mint(t, f.coord, worker.GetString("name"))
	f.app.OnRecordDelete("members").BindFunc(func(e *core.RecordEvent) error {
		if err := e.Next(); err != nil {
			return err
		}
		if e.Record.Id == f.coord.Id {
			return errors.New("synthetic post-delete failure")
		}
		return nil
	})
	code, _ := lifecycleHTTP(t, f)(lifecycleToken(t, f.human), "POST", "/api/lll/bots/remove",
		map[string]any{"id": f.coord.Id, "name": "bot-coord", "force": true})
	if code != 500 {
		t.Fatalf("post-delete failure returned %d", code)
	}
	f.reload(t, f.coord)
	if kept := f.reload(t, worker); kept.GetString("created_by") != f.coord.Id || !f.tokenWorks(old) {
		t.Fatal("failed removal left detached workers or invalid credentials")
	}
}

func TestNativeBotDisableAndOwnershipTransferSerializeAuthorization(t *testing.T) {
	for round := 0; round < 8; round++ {
		f := newCreatorFixture(t)
		registerMemberUpdateTx(f.app)
		supers, err := f.app.FindCollectionByNameOrId(core.CollectionNameSuperusers)
		if err != nil {
			t.Fatal(err)
		}
		admin := core.NewRecord(supers)
		admin.SetEmail("lifecycle-race@example.invalid")
		admin.SetPassword("isolated-lifecycle-password")
		if err := f.app.Save(admin); err != nil {
			t.Fatal(err)
		}
		f.app.OnRecordUpdate("members").BindFunc(func(e *core.RecordEvent) error {
			if e.Record.Id == f.coord.Id && e.Record.GetString("mode") == "ro" {
				stored, err := e.App.FindRecordById("members", f.coord.Id)
				if err != nil || stored.GetString("owner") != f.human.Id || !e.App.IsTransactional() {
					t.Error("disable reached a write after losing ownership or its transaction")
				}
			}
			return e.Next()
		})
		request := lifecycleHTTP(t, f)
		owner, administrator := lifecycleToken(t, f.human), lifecycleToken(t, admin)
		start := make(chan struct{})
		var wg sync.WaitGroup
		var disabled, transferred int
		wg.Add(2)
		go func() {
			defer wg.Done()
			<-start
			disabled, _ = request(owner, "POST", "/api/lll/bots/disable", map[string]any{"id": f.coord.Id, "name": "bot-coord"})
		}()
		go func() {
			defer wg.Done()
			<-start
			transferred, _ = request(administrator, "PATCH", "/api/collections/members/records/"+f.coord.Id, map[string]any{"owner": f.other.Id})
		}()
		close(start)
		wg.Wait()
		if transferred != 200 || (disabled != 200 && disabled != 403) {
			t.Fatalf("native race: disable %d, transfer %d", disabled, transferred)
		}
		final := f.reload(t, f.coord)
		wantMode := "rw"
		if disabled == 200 {
			wantMode = "ro"
		}
		if final.GetString("owner") != f.other.Id || final.GetString("mode") != wantMode {
			t.Fatal("a concurrent lifecycle write overwrote committed ownership or access")
		}
	}
}
