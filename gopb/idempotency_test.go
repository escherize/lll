package gopb

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
)

// commentKeyFixture is the native records route for comments with
// registerIdempotency bound, as gopb.Run binds it: two members and two
// issues, so the per-issue scope (LLL-700) has somewhere to differ.
type commentKeyFixture struct {
	app                   *tests.TestApp
	first, second         string
	alpha, beta           string
	alphaToken, betaToken string
	serve                 http.Handler
}

func newCommentKeyFixture(t *testing.T) commentKeyFixture {
	t.Helper()
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Cleanup)
	save := func(r core.Model) {
		t.Helper()
		if err := app.Save(r); err != nil {
			t.Fatal(err)
		}
	}
	members := core.NewAuthCollection("members")
	members.Fields.Add(&core.TextField{Name: "name"})
	save(members)
	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(&core.TextField{Name: "title"})
	save(issues)
	open := ""
	comments := core.NewBaseCollection("comments")
	comments.Fields.Add(
		&core.RelationField{Name: "issue", CollectionId: issues.Id, MaxSelect: 1, Required: true},
		&core.RelationField{Name: "author", CollectionId: members.Id, MaxSelect: 1},
		&core.TextField{Name: "body", Required: true},
		&core.TextField{Name: "idempotency_key", Hidden: true},
		&core.TextField{Name: "idempotency_fingerprint", Hidden: true, Max: 64},
	)
	comments.Indexes = []string{"CREATE UNIQUE INDEX idx_comments_idempotency ON comments (issue, idempotency_key) WHERE idempotency_key != ''"}
	comments.CreateRule, comments.UpdateRule, comments.ViewRule, comments.ListRule = &open, &open, &open, &open
	save(comments)

	member := func(name string) (string, string) {
		m := core.NewRecord(members)
		m.SetEmail(name + "@example.test")
		m.SetPassword("password123")
		m.Set("name", name)
		save(m)
		tok, err := m.NewAuthToken()
		if err != nil {
			t.Fatal(err)
		}
		return m.Id, tok
	}
	f := commentKeyFixture{app: app}
	f.alpha, f.alphaToken = member("Alpha")
	f.beta, f.betaToken = member("Beta")
	issue := func() string {
		r := core.NewRecord(issues)
		r.Set("title", "work")
		save(r)
		return r.Id
	}
	f.first, f.second = issue(), issue()

	registerIdempotency(app)
	baseRouter, err := apis.NewRouter(app)
	if err != nil {
		t.Fatal(err)
	}
	registerIdempotencyRoutes(baseRouter)
	if f.serve, err = baseRouter.BuildMux(); err != nil {
		t.Fatal(err)
	}
	return f
}

func (f commentKeyFixture) send(t *testing.T, method, path, token, key, body string) (int, map[string]any) {
	t.Helper()
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	if token != "" {
		req.Header.Set("Authorization", token)
	}
	if key != "" {
		req.Header.Set("Idempotency-Key", key)
	}
	rec := httptest.NewRecorder()
	f.serve.ServeHTTP(rec, req)
	out := map[string]any{}
	_ = json.Unmarshal(rec.Body.Bytes(), &out)
	return rec.Code, out
}

func (f commentKeyFixture) comment(t *testing.T, token, key, issue, body string) (int, map[string]any) {
	t.Helper()
	payload, _ := json.Marshal(map[string]string{"issue": issue, "body": body})
	return f.send(t, http.MethodPost, "/api/collections/comments/records", token, key, string(payload))
}

func (f commentKeyFixture) count(t *testing.T, issue string) int {
	t.Helper()
	var where []dbx.Expression
	if issue != "" {
		where = append(where, dbx.HashExp{"issue": issue})
	}
	n, err := f.app.CountRecords("comments", where...)
	if err != nil {
		t.Fatal(err)
	}
	return int(n)
}

func TestCommentIdempotencySupportRoute(t *testing.T) {
	f := newCommentKeyFixture(t)
	for _, collection := range []string{"issues", "comments"} {
		path := "/api/lll/" + collection + "/idempotency"
		if code, body := f.send(t, http.MethodGet, path, f.alphaToken, "", ""); code != 200 || body["supported"] != true {
			t.Fatalf("%s: %d %v", path, code, body)
		}
		if code, _ := f.send(t, http.MethodGet, path, "", "", ""); code != 401 {
			t.Fatalf("%s without auth: %d", path, code)
		}
	}
}

// LLL-700: a retried keyed comment is the comment the first attempt saved.
func TestCommentIdempotencyReusesMatchingRetry(t *testing.T) {
	f := newCommentKeyFixture(t)
	code, first := f.comment(t, f.alphaToken, "k1", f.first, "same body")
	if code != 200 || first["reused"] != nil {
		t.Fatalf("first: %d %v", code, first)
	}
	code, again := f.comment(t, f.alphaToken, "k1", f.first, "same body")
	if code != 200 || again["id"] != first["id"] || again["reused"] != true {
		t.Fatalf("retry: %d %v", code, again)
	}
	if n := f.count(t, f.first); n != 1 {
		t.Fatalf("comments on the issue: %d, want 1", n)
	}
	// Hidden, server-owned fields never reach the client.
	if _, leaked := again["idempotency_key"]; leaked {
		t.Fatalf("idempotency_key exported: %v", again)
	}
}

func TestCommentIdempotencyRefusesChangedBody(t *testing.T) {
	f := newCommentKeyFixture(t)
	if code, body := f.comment(t, f.alphaToken, "k1", f.first, "same body"); code != 200 {
		t.Fatalf("first: %d %v", code, body)
	}
	code, body := f.comment(t, f.alphaToken, "k1", f.first, "changed body")
	if code != http.StatusConflict || !strings.Contains(body["message"].(string), "different creation payload") {
		t.Fatalf("changed body: %d %v", code, body)
	}
	if n := f.count(t, ""); n != 1 {
		t.Fatalf("comments: %d, want 1", n)
	}
}

// The owner's decision on LLL-700: the key is scoped per issue.
func TestCommentIdempotencyIsScopedPerIssue(t *testing.T) {
	f := newCommentKeyFixture(t)
	_, first := f.comment(t, f.alphaToken, "k1", f.first, "same body")
	code, other := f.comment(t, f.alphaToken, "k1", f.second, "same body")
	if code != 200 || other["id"] == first["id"] || other["reused"] != nil {
		t.Fatalf("same key on another issue: %d %v", code, other)
	}
	if f.count(t, f.first) != 1 || f.count(t, f.second) != 1 {
		t.Fatalf("want one comment on each issue")
	}
}

// The author is forced to the signed-in member before fingerprinting: a
// forged author does not change the fingerprint, and another member's
// identical request is a different payload.
func TestCommentIdempotencyFingerprintsTheMember(t *testing.T) {
	f := newCommentKeyFixture(t)
	posted := func(body string) (int, map[string]any) {
		return f.send(t, http.MethodPost, "/api/collections/comments/records", f.alphaToken, "k1", body)
	}
	code, first := posted(`{"issue":"` + f.first + `","body":"same body","author":"` + f.beta + `"}`)
	if code != 200 {
		t.Fatalf("forged author: %d %v", code, first)
	}
	if code, replay := f.comment(t, f.alphaToken, "k1", f.first, "same body"); code != 200 || replay["id"] != first["id"] {
		t.Fatalf("retry without the forged author: %d %v", code, replay)
	}
	if code, replay := posted(`{"body":"same body","author":"` + f.alpha + `","issue":"` + f.first + `"}`); code != 200 || replay["id"] != first["id"] {
		t.Fatalf("explicit own author, reordered keys: %d %v", code, replay)
	}
	if code, _ := f.comment(t, f.betaToken, "k1", f.first, "same body"); code != http.StatusConflict {
		t.Fatalf("another member's identical comment under the key: %d, want 409", code)
	}
}

func TestCommentIdempotencyMetadataIsServerOwned(t *testing.T) {
	f := newCommentKeyFixture(t)
	payload, _ := json.Marshal(map[string]string{"issue": f.first, "body": "plain", "idempotency_key": "forged"})
	code, plain := f.send(t, http.MethodPost, "/api/collections/comments/records", f.alphaToken, "", string(payload))
	if code != 200 {
		t.Fatalf("unkeyed: %d %v", code, plain)
	}
	_, keyed := f.comment(t, f.alphaToken, "k1", f.first, "keyed")
	id := keyed["id"].(string)
	if code, body := f.send(t, http.MethodPatch, "/api/collections/comments/records/"+id, f.alphaToken, "",
		`{"body":"edited","idempotency_key":"other","idempotency_fingerprint":"forged"}`); code != 200 {
		t.Fatalf("patch: %d %v", code, body)
	}
	for _, r := range []struct{ id, key string }{{plain["id"].(string), ""}, {id, "k1"}} {
		rec, err := f.app.FindRecordById("comments", r.id)
		if err != nil {
			t.Fatal(err)
		}
		if rec.GetString("idempotency_key") != r.key {
			t.Fatalf("comment %s key %q, want %q", r.id, rec.GetString("idempotency_key"), r.key)
		}
	}
	// A replay returns the current comment without reapplying the original.
	code, replay := f.comment(t, f.alphaToken, "k1", f.first, "keyed")
	if code != 200 || replay["id"] != id || replay["body"] != "edited" || replay["reused"] != true {
		t.Fatalf("replay after edit: %d %v", code, replay)
	}
	if code, _ := f.send(t, http.MethodPost, "/api/collections/comments/records", f.alphaToken, " ",
		`{"issue":"`+f.first+`","body":"blank"}`); code != 400 {
		t.Fatalf("blank key: %d, want 400", code)
	}
}
