package gopb

import (
	"bytes"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
)

type webhookFixture struct {
	app       core.App
	team      *core.Record
	otherTeam *core.Record
	project   *core.Record
	webhook   *core.Record
}

func webhookFixtureApp(t *testing.T) webhookFixture {
	t.Helper()
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Cleanup)
	registerWebhookDelivery(app)

	teams := core.NewBaseCollection("teams")
	teams.Fields.Add(&core.TextField{Name: "key", Required: true})
	if err := app.Save(teams); err != nil {
		t.Fatal(err)
	}
	members := core.NewBaseCollection("members")
	members.Fields.Add(&core.TextField{Name: "name", Required: true})
	if err := app.Save(members); err != nil {
		t.Fatal(err)
	}
	projects := core.NewBaseCollection("projects")
	projects.Fields.Add(&core.RelationField{Name: "team", CollectionId: teams.Id, MaxSelect: 1})
	if err := app.Save(projects); err != nil {
		t.Fatal(err)
	}
	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(
		&core.RelationField{Name: "team", CollectionId: teams.Id, MaxSelect: 1, Required: true},
		&core.TextField{Name: "title"},
		&core.RelationField{Name: "project", CollectionId: projects.Id, MaxSelect: 1},
		&core.RelationField{Name: "assignee", CollectionId: members.Id, MaxSelect: 1},
	)
	if err := app.Save(issues); err != nil {
		t.Fatal(err)
	}
	webhooks := core.NewBaseCollection("webhooks")
	webhooks.Fields.Add(
		&core.RelationField{Name: "team", CollectionId: teams.Id, MaxSelect: 1, Required: true},
		&core.RelationField{Name: "project", CollectionId: projects.Id, MaxSelect: 1},
		&core.TextField{Name: "url", Required: true},
		&core.TextField{Name: "secret"},
		&core.AutodateField{Name: "created", OnCreate: true},
	)
	if err := app.Save(webhooks); err != nil {
		t.Fatal(err)
	}

	team := core.NewRecord(teams)
	team.Set("key", "ENG")
	otherTeam := core.NewRecord(teams)
	otherTeam.Set("key", "OPS")
	for _, r := range []*core.Record{team, otherTeam} {
		if err := app.Save(r); err != nil {
			t.Fatal(err)
		}
	}
	project := core.NewRecord(projects)
	if err := app.Save(project); err != nil {
		t.Fatal(err)
	}
	return webhookFixture{app: app, team: team, otherTeam: otherTeam, project: project}
}

func (f webhookFixture) register(t *testing.T, url, secret string, withProject bool) *core.Record {
	t.Helper()
	hooks, err := f.app.FindCachedCollectionByNameOrId("webhooks")
	if err != nil {
		t.Fatal(err)
	}
	rec := core.NewRecord(hooks)
	rec.Set("team", f.team.Id)
	rec.Set("url", url)
	if secret != "" {
		rec.Set("secret", secret)
	}
	if withProject {
		rec.Set("project", f.project.Id)
	}
	if err := f.app.Save(rec); err != nil {
		t.Fatal(err)
	}
	return rec
}

func (f webhookFixture) newIssue(title string, withProject bool) *core.Record {
	issues, err := f.app.FindCachedCollectionByNameOrId("issues")
	if err != nil {
		return nil
	}
	issue := core.NewRecord(issues)
	issue.Set("team", f.team.Id)
	issue.Set("title", title)
	if withProject {
		issue.Set("project", f.project.Id)
	}
	return issue
}

type receivedDelivery struct {
	path   string
	secret string
	body   []byte
}

// A receiver that records deliveries into a channel, so a test can wait a
// bounded time instead of sleeping and hoping.
func webhookReceiver(t *testing.T) (*httptest.Server, <-chan receivedDelivery) {
	t.Helper()
	ch := make(chan receivedDelivery, 32)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		ch <- receivedDelivery{path: r.URL.Path, secret: r.Header.Get("X-LLL-Secret"), body: body}
	}))
	t.Cleanup(server.Close)
	return server, ch
}

func waitDelivery(t *testing.T, ch <-chan receivedDelivery) receivedDelivery {
	t.Helper()
	select {
	case d := <-ch:
		return d
	case <-time.After(5 * time.Second):
		t.Fatal("no webhook delivery arrived within 5s")
		return receivedDelivery{}
	}
}

func assertNoDelivery(t *testing.T, ch <-chan receivedDelivery) {
	t.Helper()
	select {
	case d := <-ch:
		t.Fatalf("unexpected delivery: %s", d.body)
	case <-time.After(300 * time.Millisecond):
	}
}

func TestWebhookDeliversCreateUpdateDelete(t *testing.T) {
	f := webhookFixtureApp(t)
	server, ch := webhookReceiver(t)
	f.register(t, server.URL+"/hook", "sekrit", false)

	issue := f.newIssue("ship it", false)
	if err := f.app.Save(issue); err != nil {
		t.Fatal(err)
	}
	d := waitDelivery(t, ch)
	if d.path != "/hook" {
		t.Errorf("delivery path = %q, want /hook", d.path)
	}
	if d.secret != "sekrit" {
		t.Errorf("secret header = %q, want sekrit", d.secret)
	}
	var payload struct {
		Topic  string `json:"topic"`
		Action string `json:"action"`
		Record struct {
			Title  string `json:"title"`
			Expand struct {
				Team struct {
					Key string `json:"key"`
				} `json:"team"`
			} `json:"expand"`
		} `json:"record"`
	}
	if err := json.Unmarshal(d.body, &payload); err != nil {
		t.Fatalf("payload is not JSON: %v\n%s", err, d.body)
	}
	if payload.Topic != "issues" || payload.Action != "create" {
		t.Errorf("envelope = %s/%s, want issues/create", payload.Topic, payload.Action)
	}
	if payload.Record.Title != "ship it" {
		t.Errorf("record.title = %q, want ship it", payload.Record.Title)
	}
	if payload.Record.Expand.Team.Key != "ENG" {
		t.Errorf("record.expand.team.key = %q, want ENG", payload.Record.Expand.Team.Key)
	}

	issue.Set("title", "ship it harder")
	if err := f.app.Save(issue); err != nil {
		t.Fatal(err)
	}
	d = waitDelivery(t, ch)
	if err := json.Unmarshal(d.body, &payload); err != nil {
		t.Fatalf("payload is not JSON: %v\n%s", err, d.body)
	}
	if payload.Action != "update" || payload.Record.Title != "ship it harder" {
		t.Errorf("update payload = %s/%q", payload.Action, payload.Record.Title)
	}

	if err := f.app.Delete(issue); err != nil {
		t.Fatal(err)
	}
	d = waitDelivery(t, ch)
	if err := json.Unmarshal(d.body, &payload); err != nil {
		t.Fatalf("payload is not JSON: %v\n%s", err, d.body)
	}
	if payload.Action != "delete" {
		t.Errorf("delete payload action = %q, want delete", payload.Action)
	}
}

func TestWebhookScopeFiltersDeliveries(t *testing.T) {
	f := webhookFixtureApp(t)
	server, ch := webhookReceiver(t)
	// One project-scoped registration and one on another team: neither may
	// see a plain team issue.
	f.register(t, server.URL+"/project", "", true)
	if _, err := f.app.FindCachedCollectionByNameOrId("webhooks"); err != nil {
		t.Fatal(err)
	}
	hooks, _ := f.app.FindCachedCollectionByNameOrId("webhooks")
	other := core.NewRecord(hooks)
	other.Set("team", f.otherTeam.Id)
	other.Set("url", server.URL+"/otherteam")
	if err := f.app.Save(other); err != nil {
		t.Fatal(err)
	}

	if err := f.app.Save(f.newIssue("unscoped", false)); err != nil {
		t.Fatal(err)
	}
	assertNoDelivery(t, ch)

	// Positive control: the same receiver DOES get the matching issue, so the
	// silence above says the scope filtered, not that delivery is broken.
	if err := f.app.Save(f.newIssue("scoped", true)); err != nil {
		t.Fatal(err)
	}
	d := waitDelivery(t, ch)
	if d.path != "/project" {
		t.Errorf("delivery path = %q, want /project", d.path)
	}
	if !strings.Contains(string(d.body), `"title":"scoped"`) {
		t.Errorf("delivery body missing scoped issue: %s", d.body)
	}
	assertNoDelivery(t, ch) // and the other team's registration stayed silent
}

func TestWebhookFailureIsLoggedNotSilent(t *testing.T) {
	f := webhookFixtureApp(t)
	// A receiver that always fails: the transport succeeds, the answer is a 500.
	dead := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body)
		http.Error(w, "no", http.StatusInternalServerError)
	}))
	t.Cleanup(dead.Close)
	f.register(t, dead.URL+"/dead", "", false)

	var buf bytes.Buffer
	prev := log.Writer()
	log.SetOutput(&buf)
	defer log.SetOutput(prev)

	if err := f.app.Save(f.newIssue("witness", false)); err != nil {
		t.Fatal(err)
	}

	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if strings.Contains(buf.String(), "webhook: delivery to "+dead.URL+"/dead answered 500") {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("no failure line for the dead receiver; log was:\n%s", buf.String())
}

func TestWebhookTransportFailureIsLoggedNotSilent(t *testing.T) {
	f := webhookFixtureApp(t)
	// An address where nothing listens: the transport itself must fail.
	f.register(t, "http://127.0.0.1:1/hook", "", false)

	var buf bytes.Buffer
	prev := log.Writer()
	log.SetOutput(&buf)
	defer log.SetOutput(prev)

	if err := f.app.Save(f.newIssue("witness", false)); err != nil {
		t.Fatal(err)
	}

	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if strings.Contains(buf.String(), "webhook: delivery to http://127.0.0.1:1/hook failed:") {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("no transport-failure line for the unreachable receiver; log was:\n%s", buf.String())
}
