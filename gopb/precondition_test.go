package gopb

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
)

func readAll(t *testing.T, resp *http.Response) string {
	t.Helper()
	defer resp.Body.Close()
	b, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// preconditionFixture builds the minimal schema the hook needs, one issue to
// move ("before"), and the request path a PATCH takes — the same router the
// real server serves, with OnServe triggered so the API routes exist. The
// issues collection carries a real autodate 'updated' so the stamp a read
// returns is the stamp the hook compares against, the same contract the live
// schema has. Updates are public: the precondition is policy, not access
// control, and this fixture tests the hook.
type preconditionFixture struct {
	app   *tests.TestApp
	issue *core.Record
	stamp string
	patch func(headers map[string]string, body string) *http.Response
}

func newPreconditionFixture(t *testing.T) preconditionFixture {
	t.Helper()
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Cleanup)
	registerIssuePrecondition(app)

	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(
		&core.TextField{Name: "title"},
		&core.AutodateField{Name: "updated", OnCreate: true, OnUpdate: true},
	)
	rule := ""
	issues.UpdateRule = &rule
	if err := app.Save(issues); err != nil {
		t.Fatal(err)
	}
	issue := core.NewRecord(issues)
	issue.Set("title", "before")
	if err := app.Save(issue); err != nil {
		t.Fatal(err)
	}
	saved, err := app.FindRecordById(issues.Id, issue.Id)
	if err != nil {
		t.Fatal(err)
	}

	baseRouter, err := apis.NewRouter(app)
	if err != nil {
		t.Fatal(err)
	}
	serveEvent := new(core.ServeEvent)
	serveEvent.App = app
	serveEvent.Router = baseRouter
	if err := app.OnServe().Trigger(serveEvent, func(e *core.ServeEvent) error { return nil }); err != nil {
		t.Fatal(err)
	}

	patch := func(headers map[string]string, body string) *http.Response {
		req := httptest.NewRequest(http.MethodPatch, "/api/collections/issues/records/"+saved.Id, strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		for k, v := range headers {
			req.Header.Set(k, v)
		}
		mux, err := baseRouter.BuildMux()
		if err != nil {
			t.Fatal(err)
		}
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)
		return rec.Result()
	}
	return preconditionFixture{app: app, issue: saved, stamp: saved.GetString("updated"), patch: patch}
}

func (f preconditionFixture) title(t *testing.T) string {
	t.Helper()
	after, err := f.app.FindRecordById(f.issue.Collection().Id, f.issue.Id)
	if err != nil {
		t.Fatal(err)
	}
	return after.GetString("title")
}

func TestPreconditionRefusesAStampThatNeverMatched(t *testing.T) {
	// LLL-399's point: the check is the server's. This request did no read
	// first — the stamp is simply wrong — and the write must not land.
	f := newPreconditionFixture(t)
	resp := f.patch(map[string]string{"If-Unmodified-Since": "2000-01-01 00:00:00.000Z"}, `{"title":"clobbered"}`)
	if resp.StatusCode != http.StatusPreconditionFailed {
		t.Fatalf("expected 412 for a stamp that never matched, got %d", resp.StatusCode)
	}
	if title := f.title(t); title != "before" {
		t.Fatalf("the refused patch landed anyway: title is %q", title)
	}
}

func TestPreconditionAcceptsTheCurrentStampAndLands(t *testing.T) {
	f := newPreconditionFixture(t)
	resp := f.patch(map[string]string{"If-Unmodified-Since": f.stamp}, `{"title":"after"}`)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 for the current stamp, got %d", resp.StatusCode)
	}
	if title := f.title(t); title != "after" {
		t.Fatalf("the accepted patch did not land: title is %q", title)
	}
}

func TestPreconditionRefusalNamesTheCurrentStamp(t *testing.T) {
	// The refusal must carry what to read next: the retry needs the new
	// stamp, and the CLI shows this message verbatim.
	f := newPreconditionFixture(t)
	resp := f.patch(map[string]string{"If-Unmodified-Since": "2000-01-01 00:00:00.000Z"}, `{"title":"clobbered"}`)
	body := readAll(t, resp)
	if !strings.Contains(body, f.stamp) {
		t.Fatalf("the 412 body must carry the current stamp %q; body was: %s", f.stamp, body)
	}
	if !strings.Contains(body, "read it again") {
		t.Fatalf("the 412 body must name the retry; body was: %s", body)
	}
}

func TestPreconditionIsAbsentWithoutTheHeader(t *testing.T) {
	// The board's own moves and every other client patch without the header;
	// none of them may start failing.
	f := newPreconditionFixture(t)
	resp := f.patch(map[string]string{}, `{"title":"after"}`)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 without the header, got %d", resp.StatusCode)
	}
}

func TestPreconditionRefusesAMalformedStamp(t *testing.T) {
	f := newPreconditionFixture(t)
	resp := f.patch(map[string]string{"If-Unmodified-Since": "not a stamp"}, `{"title":"x"}`)
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("expected 400 for a malformed stamp, got %d", resp.StatusCode)
	}
}
