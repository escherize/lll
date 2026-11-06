package gopb

import (
	"fmt"
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

// LLL-622: a create may validate P as unowned, pause, and insert its child
// after a concurrent superuser PATCH has made P owned.
func TestMemberCreateAndOwnerUpdateCannotFormAChain(t *testing.T) {
	f := newCreatorFixture(t)
	parent := f.save(t, "parent", "person", "", "", &access{all: true, rw: true})
	supers, err := f.app.FindCollectionByNameOrId(core.CollectionNameSuperusers)
	if err != nil {
		t.Fatal(err)
	}
	admin := core.NewRecord(supers)
	admin.SetEmail("owner-race@example.test")
	admin.SetPassword("owner-race-password")
	if err = f.app.Save(admin); err != nil {
		t.Fatal(err)
	}
	token, err := admin.NewAuthToken()
	if err != nil {
		t.Fatal(err)
	}
	entered := make(chan struct{})
	f.app.OnRecordUpdateRequest("members").BindFunc(func(e *core.RecordRequestEvent) error { close(entered); return e.Next() })
	registerMemberUpdateTx(f.app)
	paused, resume := make(chan bool, 1), make(chan struct{})
	var once sync.Once
	release := func() { once.Do(func() { close(resume) }) }
	f.app.OnRecordCreate("members").BindFunc(func(e *core.RecordEvent) error {
		if e.Record.GetString("name") == "bot-child" {
			paused <- e.App.IsTransactional()
			<-resume
		}
		return e.Next()
	})
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
		t.Logf("%s: %d %s", method, out.Code, out.Body.String())
		return out.Code
	}
	created, updated := make(chan int, 1), make(chan int, 1)
	var workers sync.WaitGroup
	t.Cleanup(func() { release(); workers.Wait() })
	workers.Add(1)
	go func() {
		defer workers.Done()
		created <- request(http.MethodPost, "/api/collections/members/records", fmt.Sprintf(`{"name":"bot-child","kind":"bot","owner":%q,"scope":"all","mode":"rw","email":"child@example.test","password":"child-password","passwordConfirm":"child-password"}`, parent.Id))
	}()
	var transactional bool
	select {
	case transactional = <-paused:
	case <-time.After(5 * time.Second):
		t.Fatal("create did not reach checked-before-save barrier")
	}
	workers.Add(1)
	go func() {
		defer workers.Done()
		updated <- request(http.MethodPatch, "/api/collections/members/records/"+parent.Id, fmt.Sprintf(`{"owner":%q}`, f.other.Id))
	}()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("PATCH never entered")
	}
	// Force the vulnerable ordering if create holds no transaction. If it
	// owns the writer, let it commit so PATCH can re-check the current owner.
	updateCode := 0
	if !transactional {
		select {
		case updateCode = <-updated:
		case <-time.After(5 * time.Second):
			t.Fatal("unprotected create unexpectedly blocked PATCH")
		}
	}
	release()
	var createCode int
	select {
	case createCode = <-created:
	case <-time.After(5 * time.Second):
		t.Fatal("create did not finish")
	}
	if updateCode == 0 {
		select {
		case updateCode = <-updated:
		case <-time.After(5 * time.Second):
			t.Fatal("PATCH did not finish")
		}
	}
	child, childErr := f.app.FindFirstRecordByFilter("members", "name='bot-child'")
	current := f.reload(t, parent)
	if childErr == nil && child.GetString("owner") == parent.Id && current.GetString("owner") != "" {
		t.Fatalf("forbidden two-hop chain (POST=%d PATCH=%d)", createCode, updateCode)
	}
	if !((createCode == 200 && updateCode == 400) || (createCode == 400 && updateCode == 200)) {
		t.Fatalf("expected one accepted write and one policy refusal, got POST=%d PATCH=%d", createCode, updateCode)
	}
}
