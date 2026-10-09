package gopb

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
	"github.com/pocketbase/pocketbase/tools/router"
)

// numberingFixture is the schema the numbering reads, the production hooks,
// and the HTTP router, with a member and a superuser to send requests as.
type numberingFixture struct {
	app           core.App
	issues, teams *core.Collection
	alpha, bravo  *core.Record
	member, super string
	mux           http.Handler
}

func newNumberingFixture(t *testing.T) numberingFixture {
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
	teams := core.NewBaseCollection("teams")
	teams.Fields.Add(&core.TextField{Name: "key"}, &core.BoolField{Name: "archived"})
	save(teams)
	members := core.NewAuthCollection("members")
	members.Fields.Add(&core.TextField{Name: "scope"}, &core.TextField{Name: "mode"}, &core.TextField{Name: "owner"},
		&core.RelationField{Name: "teams", CollectionId: teams.Id, MaxSelect: 99})
	save(members)
	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(
		&core.RelationField{Name: "team", CollectionId: teams.Id, MaxSelect: 1},
		&core.NumberField{Name: "number", OnlyInt: true},
		&core.NumberField{Name: "sort"},
		&core.TextField{Name: "title"},
	)
	open := ""
	issues.CreateRule, issues.UpdateRule = &open, &open
	issues.Indexes = []string{"CREATE UNIQUE INDEX idx_numbering_test ON issues (team, number)"}
	save(issues)
	counters := core.NewBaseCollection(issueCounters)
	counters.Fields.Add(
		&core.RelationField{Name: "team", CollectionId: teams.Id, MaxSelect: 1, Required: true, CascadeDelete: true, Hidden: true},
		&core.NumberField{Name: "last", OnlyInt: true, Hidden: true},
	)
	counters.Indexes = []string{"CREATE UNIQUE INDEX idx_counters_test ON issue_counters (team)"}
	save(counters)
	registerIssueNumbering(app)
	// The production create hook, as gopb.Run binds it.
	app.OnRecordCreate("issues").BindFunc(func(e *core.RecordEvent) error {
		originalApp := e.App
		defer func() { e.App = originalApp }()
		return originalApp.RunInTransaction(func(txApp core.App) error {
			e.App = txApp
			if err := issueDefaults(txApp, e.Record); err != nil {
				return err
			}
			return e.Next()
		})
	})

	f := numberingFixture{app: app, issues: issues, teams: teams}
	f.alpha = f.team(t, "ALPHA")
	f.bravo = f.team(t, "BRAVO")

	m := core.NewRecord(members)
	m.SetEmail("m@example.test")
	m.SetPassword("password123")
	m.Set("scope", "all")
	m.Set("mode", "rw")
	save(m)
	supers, err := app.FindCachedCollectionByNameOrId(core.CollectionNameSuperusers)
	if err != nil {
		t.Fatal(err)
	}
	su := core.NewRecord(supers)
	su.SetEmail("su@example.test")
	su.SetPassword("password123")
	save(su)
	if f.member, err = m.NewAuthToken(); err != nil {
		t.Fatal(err)
	}
	if f.super, err = su.NewAuthToken(); err != nil {
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
	registerIssueCounterRoutes(baseRouter)
	if f.mux, err = baseRouter.BuildMux(); err != nil {
		t.Fatal(err)
	}
	return f
}

func (f numberingFixture) team(t *testing.T, key string) *core.Record {
	t.Helper()
	team := core.NewRecord(f.teams)
	team.Set("key", key)
	if err := f.app.Save(team); err != nil {
		t.Fatal(err)
	}
	return team
}

// create saves a new issue in `team` from the server's own code (number 0
// asks for the next one).
func (f numberingFixture) create(t *testing.T, team *core.Record, number int) *core.Record {
	t.Helper()
	issue := core.NewRecord(f.issues)
	issue.Set("team", team.Id)
	issue.Set("number", number)
	if err := f.app.Save(issue); err != nil {
		t.Fatal(err)
	}
	return issue
}

func (f numberingFixture) send(method, path, tok, body string) (int, string) {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if tok != "" {
		req.Header.Set("Authorization", tok)
	}
	rec := httptest.NewRecorder()
	f.mux.ServeHTTP(rec, req)
	return rec.Code, rec.Body.String()
}

// post creates an issue through the API as `tok` and returns its number.
func (f numberingFixture) post(t *testing.T, tok string, team *core.Record, number int) int {
	t.Helper()
	code, body := f.send(http.MethodPost, "/api/collections/issues/records", tok,
		`{"team":"`+team.Id+`","title":"t","number":`+strconv.Itoa(number)+`}`)
	if code != http.StatusOK {
		t.Fatalf("create answered %d: %s", code, body)
	}
	i := strings.Index(body, `"number":`)
	n, _ := strconv.Atoi(strings.TrimRight(strings.SplitN(body[i+len(`"number":`):], ",", 2)[0], "}"))
	return n
}

func (f numberingFixture) last(t *testing.T, team *core.Record) int {
	t.Helper()
	counter, err := f.app.FindFirstRecordByData(issueCounters, "team", team.Id)
	if err != nil {
		t.Fatal(err)
	}
	return counter.GetInt("last")
}

func TestDeletingTheHighestIssueDoesNotFreeItsNumber(t *testing.T) {
	f := newNumberingFixture(t)
	for want := 1; want <= 3; want++ {
		if got := f.create(t, f.alpha, 0).GetInt("number"); got != want {
			t.Fatalf("issue %d numbered %d", want, got)
		}
	}
	top, err := f.app.FindFirstRecordByFilter("issues", "number = 3")
	if err != nil {
		t.Fatal(err)
	}
	if err := f.app.Delete(top); err != nil {
		t.Fatal(err)
	}
	if got := f.create(t, f.alpha, 0).GetInt("number"); got != 4 {
		t.Fatalf("after deleting ALPHA-3 the next issue took %d; ALPHA-3 must never come back", got)
	}
	if got := f.create(t, f.bravo, 0).GetInt("number"); got != 1 {
		t.Fatalf("BRAVO's first issue numbered %d", got)
	}
}

func TestATeamWithoutACounterStartsPastItsLiveIssues(t *testing.T) {
	f := newNumberingFixture(t)
	f.create(t, f.alpha, 7)
	counter, err := f.app.FindFirstRecordByData(issueCounters, "team", f.alpha.Id)
	if err != nil {
		t.Fatal(err)
	}
	if err := f.app.Delete(counter); err != nil {
		t.Fatal(err)
	}
	if got := f.create(t, f.alpha, 0).GetInt("number"); got != 8 {
		t.Fatalf("expected 8 past a live ALPHA-7, got %d", got)
	}
	if last := f.last(t, f.alpha); last != 8 {
		t.Fatalf("the counter should record 8, has %d", last)
	}
}

func TestAMemberNeverChoosesANumber(t *testing.T) {
	f := newNumberingFixture(t)
	f.post(t, f.member, f.alpha, 0)
	f.post(t, f.member, f.alpha, 0)
	for i, forged := range []int{9007199254740000, 3 + 1000, 999_999_999, 1, -5, 4} {
		got := f.post(t, f.member, f.alpha, forged)
		if got != 3+i {
			t.Fatalf("a member's explicit %d numbered %d, want the server's %d", forged, got, 3+i)
		}
		if last := f.last(t, f.alpha); last != got {
			t.Fatalf("a member's explicit %d moved the counter to %d", forged, last)
		}
	}
}

func TestAMemberCannotChangeANumber(t *testing.T) {
	f := newNumberingFixture(t)
	issue := f.create(t, f.alpha, 0)
	code, _ := f.send(http.MethodPatch, "/api/collections/issues/records/"+issue.Id, f.member, `{"number":999999999}`)
	if code != http.StatusBadRequest {
		t.Fatalf("a member's number PATCH answered %d", code)
	}
	if last := f.last(t, f.alpha); last != 1 {
		t.Fatalf("the refused PATCH moved the counter to %d", last)
	}
	code, _ = f.send(http.MethodPatch, "/api/collections/issues/records/"+issue.Id, f.super, `{"number":5}`)
	if code != http.StatusOK {
		t.Fatalf("a superuser's renumbering answered %d", code)
	}
	if last := f.last(t, f.alpha); last != 5 {
		t.Fatalf("a superuser's renumbering left the counter at %d", last)
	}
}

func TestAMovedIssueGetsAFreshNumberInItsNewTeam(t *testing.T) {
	f := newNumberingFixture(t)
	for i := 0; i < 6; i++ {
		f.create(t, f.alpha, 0)
	}
	f.create(t, f.bravo, 0)
	top, err := f.app.FindFirstRecordByFilter("issues", "team = {:t} && number = 6", map[string]any{"t": f.alpha.Id})
	if err != nil {
		t.Fatal(err)
	}
	code, body := f.send(http.MethodPatch, "/api/collections/issues/records/"+top.Id, f.member, `{"team":"`+f.bravo.Id+`"}`)
	if code != http.StatusOK {
		t.Fatalf("the move answered %d: %s", code, body)
	}
	moved, _ := f.app.FindRecordById("issues", top.Id)
	if moved.GetInt("number") != 2 {
		t.Fatalf("the moved issue is BRAVO-%d, want BRAVO-2", moved.GetInt("number"))
	}
	if f.last(t, f.bravo) != 2 || f.last(t, f.alpha) != 6 {
		t.Fatalf("counters after the move: ALPHA %d, BRAVO %d", f.last(t, f.alpha), f.last(t, f.bravo))
	}
	// ALPHA-6 is gone from ALPHA and does not come back.
	if got := f.create(t, f.alpha, 0).GetInt("number"); got != 7 {
		t.Fatalf("ALPHA's next issue took %d", got)
	}
}

func TestASuperusersImportKeepsTheMirrorsNumbers(t *testing.T) {
	// lll import dir with a superuser token into a fresh team: gaps larger
	// than any margin, in the mirror's file order, kept; the counter moves to
	// the highest once.
	f := newNumberingFixture(t)
	for _, n := range []int{1, 10000, 1850, 2, 5, 900} {
		if got := f.post(t, f.super, f.alpha, n); got != n {
			t.Fatalf("imported %d numbered %d", n, got)
		}
	}
	if last := f.last(t, f.alpha); last != 10000 {
		t.Fatalf("the counter after the import is %d", last)
	}
	// The same mirror from a member is numbered by the server.
	if got := f.post(t, f.member, f.bravo, 900); got != 1 {
		t.Fatalf("a member's imported 900 numbered %d", got)
	}
}

func TestASuperuserMayNameANumber(t *testing.T) {
	f := newNumberingFixture(t)
	if got := f.post(t, f.super, f.alpha, 40); got != 40 {
		t.Fatalf("a superuser's explicit 40 numbered %d", got)
	}
	if got := f.post(t, f.member, f.alpha, 0); got != 41 {
		t.Fatalf("expected 41 after 40, got %d", got)
	}
	code, _ := f.send(http.MethodPost, "/api/collections/issues/records", f.super,
		`{"team":"`+f.alpha.Id+`","title":"t","number":1000000000}`)
	if code != http.StatusBadRequest {
		t.Fatalf("a number past the ceiling answered %d", code)
	}
}

func TestRunningOutNamesTheHolderAndTheRepair(t *testing.T) {
	f := newNumberingFixture(t)
	f.create(t, f.alpha, maxIssueNumber)
	issue := core.NewRecord(f.issues)
	issue.Set("team", f.alpha.Id)
	err := f.app.Save(issue)
	if err == nil || !strings.Contains(err.Error(), "ALPHA-999999999 holds the highest") || !strings.Contains(err.Error(), "issue-counter") {
		t.Fatalf("expected the exhausted refusal naming ALPHA-999999999, got %v", err)
	}
}

func TestAFailedCreateLeavesTheCounterAlone(t *testing.T) {
	f := newNumberingFixture(t)
	f.create(t, f.alpha, 0)
	f.create(t, f.alpha, 5)
	clash := core.NewRecord(f.issues)
	clash.Set("team", f.alpha.Id)
	clash.Set("number", 5)
	if err := f.app.Save(clash); err == nil {
		t.Fatal("a duplicate number saved")
	}
	if last := f.last(t, f.alpha); last != 5 {
		t.Fatalf("the counter moved on a refused create: %d", last)
	}
}

func TestDeletingATeamTakesItsCounter(t *testing.T) {
	f := newNumberingFixture(t)
	issue := f.create(t, f.bravo, 0)
	if err := f.app.Delete(issue); err != nil {
		t.Fatal(err)
	}
	if err := f.app.Delete(f.bravo); err != nil {
		t.Fatal(err)
	}
	if _, err := f.app.FindFirstRecordByData(issueCounters, "team", f.bravo.Id); err == nil {
		t.Fatal("the deleted team's counter survived")
	}
}

func TestNoRequestTouchesACounter(t *testing.T) {
	f := newNumberingFixture(t)
	f.create(t, f.alpha, 0)
	counter, err := f.app.FindFirstRecordByData(issueCounters, "team", f.alpha.Id)
	if err != nil {
		t.Fatal(err)
	}
	path := "/api/collections/issue_counters/records/" + counter.Id
	if code, _ := f.send(http.MethodPatch, path, f.super, `{"last":0}`); code != http.StatusForbidden {
		t.Fatalf("a superuser's counter PATCH answered %d", code)
	}
	if code, _ := f.send(http.MethodDelete, path, f.super, ""); code != http.StatusForbidden {
		t.Fatalf("a superuser's counter DELETE answered %d", code)
	}
	if code, _ := f.send(http.MethodDelete, "/api/collections/issue_counters/truncate", f.super, ""); code != http.StatusForbidden {
		t.Fatalf("a superuser's counter truncate answered %d", code)
	}
	if f.last(t, f.alpha) != 1 {
		t.Fatal("the counter did not survive")
	}
}

// ------------------------------------------------------- counter repair

func TestOnlyASuperuserRepairsACounter(t *testing.T) {
	f := newNumberingFixture(t)
	for i := 0; i < 3; i++ {
		f.create(t, f.alpha, 0)
	}
	if _, err := repairIssueCounter(f.app, f.alpha.Id, 5000); err != nil {
		t.Fatal(err)
	}
	repair := func(tok, body string) int {
		code, _ := f.send(http.MethodPost, "/api/lll/teams/"+f.alpha.Id+"/issue-counter", tok, body)
		return code
	}
	if code := repair(f.member, `{"last":3,"reason":"pushed too far"}`); code != http.StatusForbidden && code != http.StatusUnauthorized {
		t.Fatalf("a member's repair answered %d", code)
	}
	if code := repair("", `{"last":3,"reason":"anonymous"}`); code != http.StatusUnauthorized && code != http.StatusForbidden {
		t.Fatalf("an anonymous repair answered %d", code)
	}
	if code := repair(f.super, `{"last":3}`); code != http.StatusBadRequest {
		t.Fatalf("a repair with no reason answered %d", code)
	}
	if code := repair(f.super, `{"last":2,"reason":"below the live issues"}`); code != http.StatusBadRequest {
		t.Fatalf("a repair below the highest live issue answered %d", code)
	}
	if last := f.last(t, f.alpha); last != 5000 {
		t.Fatalf("a refused repair changed the counter to %d", last)
	}
	if code := repair(f.super, `{"last":3,"reason":"pushed too far"}`); code != http.StatusOK {
		t.Fatalf("the superuser's repair answered %d", code)
	}
	if got := f.create(t, f.alpha, 0).GetInt("number"); got != 4 {
		t.Fatalf("after the repair the next issue took %d", got)
	}
}

// ------------------------------------------------- assignment precondition

func assignmentPreconditionFixture(t *testing.T) (core.App, *core.Record, string) {
	t.Helper()
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Cleanup)
	members := core.NewBaseCollection("members")
	members.Fields.Add(&core.TextField{Name: "name"})
	if err := app.Save(members); err != nil {
		t.Fatal(err)
	}
	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(
		&core.RelationField{Name: "assignee", CollectionId: members.Id, MaxSelect: 1},
		&core.TextField{Name: "description"},
		&core.AutodateField{Name: "updated", OnCreate: true, OnUpdate: true},
	)
	if err := app.Save(issues); err != nil {
		t.Fatal(err)
	}
	claims := core.NewBaseCollection("claims")
	claims.Fields.Add(&core.RelationField{Name: "issue", CollectionId: issues.Id, MaxSelect: 1})
	if err := app.Save(claims); err != nil {
		t.Fatal(err)
	}
	member := core.NewRecord(members)
	member.Set("name", "Alpha")
	if err := app.Save(member); err != nil {
		t.Fatal(err)
	}
	issue := core.NewRecord(issues)
	issue.Set("description", "read")
	if err := app.Save(issue); err != nil {
		t.Fatal(err)
	}
	saved, err := app.FindRecordById("issues", issue.Id)
	if err != nil {
		t.Fatal(err)
	}
	return app, saved, member.Id
}

func TestAssignmentWithAStaleDerivedDescriptionIsRefused(t *testing.T) {
	// LLL-665: 'lll issue update KEY --assignee x --description-append y'
	// derives the description from a read; the assignment route must not
	// write it over a newer description.
	app, issue, member := assignmentPreconditionFixture(t)
	stale := "2000-01-01 00:00:00.000Z"
	derived := "read\nappended"
	fields := assignmentFields{Assignee: &member, Description: &derived, IfUnmodifiedSince: &stale}
	_, err := updateAssignment(app, issue.Id, "", fields, releaser{}, false)
	var answered *router.ApiError
	if !errors.As(err, &answered) || answered.Status != http.StatusPreconditionFailed {
		t.Fatalf("expected a 412, got %v", err)
	}
	after, _ := app.FindRecordById("issues", issue.Id)
	if after.GetString("assignee") != "" || after.GetString("description") != "read" {
		t.Fatalf("the refused update landed: assignee %q, description %q", after.GetString("assignee"), after.GetString("description"))
	}

	current := issue.GetString("updated")
	fields.IfUnmodifiedSince = &current
	if _, err := updateAssignment(app, issue.Id, "", fields, releaser{}, false); err != nil {
		t.Fatalf("the current stamp was refused: %v", err)
	}
	after, _ = app.FindRecordById("issues", issue.Id)
	if after.GetString("assignee") != member || after.GetString("description") != derived {
		t.Fatalf("the accepted update did not land: assignee %q, description %q", after.GetString("assignee"), after.GetString("description"))
	}
}

func TestAnUnknownAssignmentFieldIsStillRefused(t *testing.T) {
	// The stamp is a named field, not a hole: anything else unknown fails.
	if _, err := parseAssignmentFields([]byte(`{"assignee":"","if_unmodified_since":"x"}`)); err != nil {
		t.Fatalf("the stamp field was refused: %v", err)
	}
	if _, err := parseAssignmentFields([]byte(`{"assignee":"","sort":1}`)); err == nil {
		t.Fatal("an unknown field was accepted")
	}
}

// ----------------------------------------------------- comment immutability

func TestACommentCannotMoveToAnotherIssue(t *testing.T) {
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Cleanup)
	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(&core.TextField{Name: "title"})
	if err := app.Save(issues); err != nil {
		t.Fatal(err)
	}
	comments := core.NewBaseCollection("comments")
	comments.Fields.Add(
		&core.RelationField{Name: "issue", CollectionId: issues.Id, MaxSelect: 1, Required: true},
		&core.TextField{Name: "author"},
		&core.TextField{Name: "body"},
		&core.TextField{Name: "author_kind"},
		&core.BoolField{Name: "server_record"},
	)
	open := ""
	comments.UpdateRule = &open
	if err := app.Save(comments); err != nil {
		t.Fatal(err)
	}
	registerSystemCommentGuard(app)
	first, second := core.NewRecord(issues), core.NewRecord(issues)
	for _, issue := range []*core.Record{first, second} {
		if err := app.Save(issue); err != nil {
			t.Fatal(err)
		}
	}
	comment := core.NewRecord(comments)
	comment.Set("issue", first.Id)
	comment.Set("body", "about the first issue")
	if err := app.Save(comment); err != nil {
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
	mux, err := baseRouter.BuildMux()
	if err != nil {
		t.Fatal(err)
	}
	patch := func(body string) int {
		req := httptest.NewRequest(http.MethodPatch, "/api/collections/comments/records/"+comment.Id, strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)
		return rec.Code
	}
	if code := patch(`{"issue":"` + second.Id + `"}`); code != http.StatusBadRequest {
		t.Fatalf("moving the comment answered %d", code)
	}
	after, _ := app.FindRecordById("comments", comment.Id)
	if after.GetString("issue") != first.Id {
		t.Fatal("the comment moved")
	}
	// Its own issue, restated, and a body edit still go through.
	if code := patch(`{"issue":"` + first.Id + `","body":"edited"}`); code != http.StatusOK {
		t.Fatalf("an edit naming the same issue answered %d", code)
	}
}
