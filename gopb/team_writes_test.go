package gopb

import (
	"errors"
	"net/http"
	"strings"
	"testing"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
	"github.com/pocketbase/pocketbase/tools/router"
)

type teamWritesFixture struct {
	app          core.App
	live, frozen *core.Record
}

func newTeamWritesFixture(t *testing.T) teamWritesFixture {
	t.Helper()
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Cleanup)
	save := func(c *core.Collection) {
		if err := app.Save(c); err != nil {
			t.Fatal(err)
		}
	}
	teams := core.NewBaseCollection("teams")
	teams.Fields.Add(&core.TextField{Name: "key"}, &core.BoolField{Name: "archived"})
	save(teams)
	team := func() *core.RelationField {
		return &core.RelationField{Name: "team", CollectionId: teams.Id, MaxSelect: 1}
	}
	members := core.NewBaseCollection("members")
	members.Fields.Add(&core.TextField{Name: "name"}, &core.TextField{Name: "scope"}, &core.TextField{Name: "mode"},
		&core.TextField{Name: "owner"}, &core.RelationField{Name: "teams", CollectionId: teams.Id, MaxSelect: 99})
	save(members)
	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(&core.TextField{Name: "title"}, team(),
		&core.RelationField{Name: "assignee", CollectionId: members.Id, MaxSelect: 1})
	save(issues)
	for _, name := range []string{"comments", "claims"} {
		c := core.NewBaseCollection(name)
		c.Fields.Add(&core.TextField{Name: "body"}, &core.RelationField{Name: "issue", CollectionId: issues.Id, MaxSelect: 1})
		save(c)
	}
	for _, name := range []string{"docs", "labels", "projects"} {
		c := core.NewBaseCollection(name)
		c.Fields.Add(&core.TextField{Name: "name"}, team())
		save(c)
	}
	registerArchivedTeamGuard(app)
	registerAssigneeTeamGuard(app)
	f := teamWritesFixture{app: app}
	f.live = f.rec(t, "teams", map[string]any{"key": "LIVE"})
	f.frozen = f.rec(t, "teams", map[string]any{"key": "FROZEN"})
	return f
}

func (f teamWritesFixture) rec(t *testing.T, collection string, data map[string]any) *core.Record {
	t.Helper()
	c, err := f.app.FindCollectionByNameOrId(collection)
	if err != nil {
		t.Fatal(err)
	}
	r := core.NewRecord(c)
	r.Load(data)
	if err := f.app.Save(r); err != nil {
		t.Fatalf("%s %v: %v", collection, data, err)
	}
	return r
}

func (f teamWritesFixture) archive(t *testing.T, team *core.Record) {
	t.Helper()
	team.Set("archived", true)
	if err := f.app.Save(team); err != nil {
		t.Fatal(err)
	}
}

// request runs the records API's request hooks for one write, as auth (nil
// for none), and reports whether the write would have gone ahead.
func (f teamWritesFixture) request(t *testing.T, action string, r *core.Record, auth *core.Record) (bool, error) {
	t.Helper()
	e := &core.RecordRequestEvent{RequestEvent: &core.RequestEvent{App: f.app, Auth: auth}, Record: r}
	e.Collection = r.Collection()
	reached := false
	next := func(*core.RecordRequestEvent) error {
		reached = true
		return nil
	}
	var err error
	switch action {
	case "create":
		err = f.app.OnRecordCreateRequest().Trigger(e, next)
	case "update":
		err = f.app.OnRecordUpdateRequest().Trigger(e, next)
	case "delete":
		err = f.app.OnRecordDeleteRequest().Trigger(e, next)
	}
	return reached, err
}

func refusedAsArchived(t *testing.T, err error, key string) {
	t.Helper()
	var api *router.ApiError
	if !errors.As(err, &api) || api.Status != http.StatusForbidden {
		t.Fatalf("want a 403, got %v", err)
	}
	for _, want := range []string{"team " + key + " is archived", "'lll team unarchive " + key + "'"} {
		if !strings.Contains(strings.ToLower(api.Message[:1])+api.Message[1:], want) {
			t.Fatalf("refusal %q lacks %q", api.Message, want)
		}
	}
}

func TestArchivedTeamRefusesEveryGuardedWrite(t *testing.T) {
	f := newTeamWritesFixture(t)
	issue := f.rec(t, "issues", map[string]any{"title": "frozen work", "team": f.frozen.Id})
	records := []*core.Record{issue}
	for _, name := range []string{"comments", "claims"} {
		records = append(records, f.rec(t, name, map[string]any{"issue": issue.Id}))
	}
	for _, name := range []string{"docs", "labels", "projects"} {
		records = append(records, f.rec(t, name, map[string]any{"name": "x", "team": f.frozen.Id}))
	}
	f.archive(t, f.frozen)
	for _, r := range records {
		for _, action := range []string{"update", "delete"} {
			reached, err := f.request(t, action, r, nil)
			if reached {
				t.Fatalf("%s %s on an archived team went ahead", action, r.Collection().Name)
			}
			refusedAsArchived(t, err, "FROZEN")
		}
		fresh := core.NewRecord(r.Collection())
		fresh.Load(r.PublicExport())
		fresh.Id = ""
		reached, err := f.request(t, "create", fresh, nil)
		if reached {
			t.Fatalf("create %s in an archived team went ahead", r.Collection().Name)
		}
		refusedAsArchived(t, err, "FROZEN")
	}
}

func TestArchivedTeamRefusesMovesInAndOut(t *testing.T) {
	f := newTeamWritesFixture(t)
	inLive := f.rec(t, "issues", map[string]any{"title": "a", "team": f.live.Id})
	inFrozen := f.rec(t, "issues", map[string]any{"title": "b", "team": f.frozen.Id})
	f.archive(t, f.frozen)
	// The records API loads the stored row, so Original() is what is stored.
	inLive, _ = f.app.FindRecordById("issues", inLive.Id)
	inFrozen, _ = f.app.FindRecordById("issues", inFrozen.Id)

	inLive.Set("team", f.frozen.Id)
	_, err := f.request(t, "update", inLive, nil)
	refusedAsArchived(t, err, "FROZEN")
	inFrozen.Set("team", f.live.Id)
	_, err = f.request(t, "update", inFrozen, nil)
	refusedAsArchived(t, err, "FROZEN")

	// A comment cannot be moved onto an archived team's issue either.
	comment := f.rec(t, "comments", map[string]any{"issue": inLive.Id})
	comment, _ = f.app.FindRecordById("comments", comment.Id)
	comment.Set("issue", inFrozen.Id)
	_, err = f.request(t, "update", comment, nil)
	refusedAsArchived(t, err, "FROZEN")
}

func TestLiveTeamWritesAndUnarchiveGoAhead(t *testing.T) {
	f := newTeamWritesFixture(t)
	issue := f.rec(t, "issues", map[string]any{"title": "live", "team": f.live.Id})
	issue.Set("title", "edited")
	if reached, err := f.request(t, "update", issue, nil); !reached || err != nil {
		t.Fatalf("a live team's update was refused: %v", err)
	}
	f.archive(t, f.frozen)
	f.frozen.Set("archived", false)
	if reached, err := f.request(t, "update", f.frozen, nil); !reached || err != nil {
		t.Fatalf("unarchiving was refused: %v", err)
	}
}

// A scoped member who cannot see the archived team gets the collection
// rules' answer, not a refusal naming the team.
func TestArchivedRefusalDoesNotNameAHiddenTeam(t *testing.T) {
	f := newTeamWritesFixture(t)
	issue := f.rec(t, "issues", map[string]any{"title": "hidden", "team": f.frozen.Id})
	f.archive(t, f.frozen)
	outsider := f.rec(t, "members", map[string]any{"name": "outsider", "scope": "teams", "mode": "rw", "teams": []string{f.live.Id}})
	insider := f.rec(t, "members", map[string]any{"name": "insider", "scope": "teams", "mode": "rw", "teams": []string{f.frozen.Id}})
	if reached, err := f.request(t, "delete", issue, outsider); !reached || err != nil {
		t.Fatalf("the guard answered for a team the caller cannot see: %v", err)
	}
	_, err := f.request(t, "delete", issue, insider)
	refusedAsArchived(t, err, "FROZEN")
}

// The model layer is not guarded: deleting a member clears its id from an
// archived team's issues through a save, and that must keep working.
func TestArchivedTeamKeepsSystemSaves(t *testing.T) {
	f := newTeamWritesFixture(t)
	m := f.rec(t, "members", map[string]any{"name": "m", "scope": "all", "mode": "rw"})
	issue := f.rec(t, "issues", map[string]any{"title": "x", "team": f.frozen.Id, "assignee": m.Id})
	f.archive(t, f.frozen)
	issue.Set("assignee", "")
	if err := f.app.Save(issue); err != nil {
		t.Fatalf("a system save on an archived team failed: %v", err)
	}
}

func TestAssigneeMustSeeTheIssuesTeam(t *testing.T) {
	f := newTeamWritesFixture(t)
	liveOnly := f.rec(t, "members", map[string]any{"name": "live-only", "scope": "teams", "mode": "rw", "teams": []string{f.live.Id}})
	everyone := f.rec(t, "members", map[string]any{"name": "everyone", "scope": "all", "mode": "rw"})
	issues, _ := f.app.FindCollectionByNameOrId("issues")
	newIssue := func(team, assignee string) *core.Record {
		r := core.NewRecord(issues)
		r.Load(map[string]any{"title": "t", "team": team, "assignee": assignee})
		return r
	}
	refused := func(err error, what string) {
		t.Helper()
		if err == nil || !strings.Contains(err.Error(), "cannot see team FROZEN") {
			t.Fatalf("%s: want the assignee refusal, got %v", what, err)
		}
		if strings.Contains(err.Error(), "live-only") {
			t.Fatalf("%s: the refusal names the member: %v", what, err)
		}
	}

	refused(f.app.Save(newIssue(f.frozen.Id, liveOnly.Id)), "create")
	if err := f.app.Save(newIssue(f.live.Id, liveOnly.Id)); err != nil {
		t.Fatalf("assigning within the member's team: %v", err)
	}
	if err := f.app.Save(newIssue(f.frozen.Id, everyone.Id)); err != nil {
		t.Fatalf("assigning an all-scope member: %v", err)
	}

	open := newIssue(f.frozen.Id, "")
	if err := f.app.Save(open); err != nil {
		t.Fatal(err)
	}
	open.Set("assignee", liveOnly.Id)
	refused(f.app.Save(open), "update")

	// A move must not strand the assignee outside the new team.
	moving := newIssue(f.live.Id, liveOnly.Id)
	if err := f.app.Save(moving); err != nil {
		t.Fatal(err)
	}
	moving.Set("team", f.frozen.Id)
	refused(f.app.Save(moving), "move")

	// Narrowing a member later keeps what they hold: an unrelated edit and a
	// clear both go through.
	held := newIssue(f.live.Id, liveOnly.Id)
	if err := f.app.Save(held); err != nil {
		t.Fatal(err)
	}
	liveOnly.Set("teams", []string{f.frozen.Id})
	if err := f.app.Save(liveOnly); err != nil {
		t.Fatal(err)
	}
	held, _ = f.app.FindRecordById("issues", held.Id)
	held.Set("title", "renamed")
	if err := f.app.Save(held); err != nil {
		t.Fatalf("an unrelated edit after narrowing: %v", err)
	}
	held.Set("assignee", "")
	if err := f.app.Save(held); err != nil {
		t.Fatalf("clearing the assignee: %v", err)
	}
}

// A bot sees only what its owner also sees.
func TestAssigneeBotIsHeldToItsOwner(t *testing.T) {
	f := newTeamWritesFixture(t)
	owner := f.rec(t, "members", map[string]any{"name": "owner", "scope": "teams", "mode": "rw", "teams": []string{f.live.Id}})
	bot := f.rec(t, "members", map[string]any{"name": "bot-x", "scope": "all", "mode": "rw", "owner": owner.Id})
	issues, _ := f.app.FindCollectionByNameOrId("issues")
	r := core.NewRecord(issues)
	r.Load(map[string]any{"title": "t", "team": f.frozen.Id, "assignee": bot.Id})
	if err := f.app.Save(r); err == nil || !strings.Contains(err.Error(), "cannot see team FROZEN") {
		t.Fatalf("a bot was assigned outside its owner's teams: %v", err)
	}
}
