package gopb

import (
	"strings"
	"testing"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
)

type teamRefFixture struct {
	app         core.App
	alpha, beta *core.Record
}

func newTeamRefFixture(t *testing.T) teamRefFixture {
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
	teams.Fields.Add(&core.TextField{Name: "key"})
	save(teams)
	team := func() *core.RelationField {
		return &core.RelationField{Name: "team", CollectionId: teams.Id, MaxSelect: 1, Required: true}
	}
	labels := core.NewBaseCollection("labels")
	labels.Fields.Add(&core.TextField{Name: "name"}, team())
	save(labels)
	projects := core.NewBaseCollection("projects")
	projects.Fields.Add(&core.TextField{Name: "name"}, team())
	save(projects)
	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(&core.TextField{Name: "title"}, &core.NumberField{Name: "number"}, team(),
		&core.RelationField{Name: "labels", CollectionId: labels.Id, MaxSelect: 99},
		&core.RelationField{Name: "project", CollectionId: projects.Id, MaxSelect: 1})
	save(issues)
	issues.Fields.Add(&core.RelationField{Name: "blocked_by", CollectionId: issues.Id, MaxSelect: 99})
	save(issues)
	favorites := core.NewBaseCollection("favorites")
	favorites.Fields.Add(&core.RelationField{Name: "issue", CollectionId: issues.Id, MaxSelect: 1}, &core.TextField{Name: "member"})
	save(favorites)
	docs := core.NewBaseCollection("docs")
	docs.Fields.Add(&core.TextField{Name: "slug"}, team(), &core.RelationField{Name: "issues", CollectionId: issues.Id, MaxSelect: 99})
	save(docs)
	webhooks := core.NewBaseCollection("webhooks")
	webhooks.Fields.Add(team(), &core.RelationField{Name: "project", CollectionId: projects.Id, MaxSelect: 1})
	save(webhooks)
	registerTeamRefGuard(app)
	f := teamRefFixture{app: app}
	f.alpha = f.rec(t, "teams", map[string]any{"key": "ALPHA"})
	f.beta = f.rec(t, "teams", map[string]any{"key": "BETA"})
	return f
}

func (f teamRefFixture) rec(t *testing.T, collection string, data map[string]any) *core.Record {
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

// refused saves r and wants the cross-team refusal containing every want.
func (f teamRefFixture) refused(t *testing.T, r *core.Record, want ...string) {
	t.Helper()
	err := f.app.Save(r)
	if err == nil {
		t.Fatalf("%s saved; want a cross-team refusal", r.Collection().Name)
	}
	for _, w := range append(want, "reference stays inside one team") {
		if !strings.Contains(err.Error(), w) {
			t.Fatalf("refusal %q lacks %q", err, w)
		}
	}
}

func (f teamRefFixture) fresh(t *testing.T, r *core.Record) *core.Record {
	t.Helper()
	got, err := f.app.FindRecordById(r.Collection().Name, r.Id)
	if err != nil {
		t.Fatal(err)
	}
	return got
}

// LLL-631: a reference stays inside one team for every writer; the hook runs
// on the app's own saves, which is what a superuser and the custom routes use.
func TestCrossTeamReferencesAreRefusedForEveryWriter(t *testing.T) {
	f := newTeamRefFixture(t)
	alphaLabel := f.rec(t, "labels", map[string]any{"name": "bug", "team": f.alpha.Id})
	betaLabel := f.rec(t, "labels", map[string]any{"name": "secretbeta", "team": f.beta.Id})
	betaProject := f.rec(t, "projects", map[string]any{"name": "bp", "team": f.beta.Id})
	betaIssue := f.rec(t, "issues", map[string]any{"title": "b", "number": 1, "team": f.beta.Id})
	issue := f.rec(t, "issues", map[string]any{"title": "a", "number": 1, "team": f.alpha.Id, "labels": []string{alphaLabel.Id}})

	for field, value := range map[string]any{"labels+": betaLabel.Id, "project": betaProject.Id, "blocked_by+": betaIssue.Id} {
		r := f.fresh(t, issue)
		r.Set(field, value)
		f.refused(t, r, "another team")
	}
	issues, _ := f.app.FindCollectionByNameOrId("issues")
	created := core.NewRecord(issues)
	created.Load(map[string]any{"title": "c", "number": 2, "team": f.alpha.Id, "labels": []string{betaLabel.Id}})
	f.refused(t, created, "labels: label "+betaLabel.Id)
	docs, _ := f.app.FindCollectionByNameOrId("docs")
	doc := core.NewRecord(docs)
	doc.Load(map[string]any{"slug": "d", "team": f.alpha.Id, "issues": []string{betaIssue.Id}})
	f.refused(t, doc)
	webhooks, _ := f.app.FindCollectionByNameOrId("webhooks")
	hook := core.NewRecord(webhooks)
	hook.Load(map[string]any{"team": f.alpha.Id, "project": betaProject.Id})
	f.refused(t, hook)

	// Same-team references still work.
	alphaProject := f.rec(t, "projects", map[string]any{"name": "ap", "team": f.alpha.Id})
	r := f.fresh(t, issue)
	r.Set("project", alphaProject.Id)
	if err := f.app.Save(r); err != nil {
		t.Fatalf("same-team project: %v", err)
	}
}

// A reference made before the rule does not block an unrelated edit.
func TestALegacyCrossTeamReferenceDoesNotBlockUnrelatedEdits(t *testing.T) {
	f := newTeamRefFixture(t)
	betaLabel := f.rec(t, "labels", map[string]any{"name": "secretbeta", "team": f.beta.Id})
	issue := f.rec(t, "issues", map[string]any{"title": "a", "number": 1, "team": f.alpha.Id})
	if _, err := f.app.DB().NewQuery("UPDATE issues SET labels = {:l} WHERE id = {:id}").
		Bind(map[string]any{"l": `["` + betaLabel.Id + `"]`, "id": issue.Id}).Execute(); err != nil {
		t.Fatal(err)
	}
	r := f.fresh(t, issue)
	r.Set("title", "edited")
	if err := f.app.Save(r); err != nil {
		t.Fatalf("unrelated edit refused: %v", err)
	}
}

// A move is checked against the NEW team, in both directions, and the
// refusal names what to detach.
func TestATeamMoveIsRefusedWhileReferencesWouldCrossTeams(t *testing.T) {
	f := newTeamRefFixture(t)
	label := f.rec(t, "labels", map[string]any{"name": "bug", "team": f.alpha.Id})
	blocker := f.rec(t, "issues", map[string]any{"title": "blocker", "number": 1, "team": f.alpha.Id})
	issue := f.rec(t, "issues", map[string]any{"title": "a", "number": 2, "team": f.alpha.Id,
		"labels": []string{label.Id}, "blocked_by": []string{blocker.Id}})

	// Outgoing: the issue's own label and blocker.
	r := f.fresh(t, issue)
	r.Set("team", f.beta.Id)
	f.refused(t, r, "labels: label 'bug' (ALPHA)", "blocked_by: issue ALPHA-1", "from ALPHA to BETA")
	// Incoming: the issue it blocks, and the label's users.
	r = f.fresh(t, blocker)
	r.Set("team", f.beta.Id)
	f.refused(t, r, "issues.blocked_by of issue ALPHA-2")
	r = f.fresh(t, label)
	r.Set("team", f.beta.Id)
	f.refused(t, r, "issues.labels of issue ALPHA-2")
	doc := f.rec(t, "docs", map[string]any{"slug": "d", "team": f.alpha.Id, "issues": []string{blocker.Id}})
	r = f.fresh(t, doc)
	r.Set("team", f.beta.Id)
	f.refused(t, r, "issues: issue ALPHA-1")

	// Detached, the move goes through.
	r = f.fresh(t, issue)
	r.Set("labels", []string{})
	r.Set("blocked_by", []string{})
	if err := f.app.Save(r); err != nil {
		t.Fatal(err)
	}
	r = f.fresh(t, issue)
	r.Set("team", f.beta.Id)
	if err := f.app.Save(r); err != nil {
		t.Fatalf("a move with no references left: %v", err)
	}
}

// Review F2: a save built on a stale read must not write the old team back
// under a reference made since.
func TestAStaleSaveCannotUndoAMove(t *testing.T) {
	f := newTeamRefFixture(t)
	label := f.rec(t, "labels", map[string]any{"name": "bug", "team": f.alpha.Id})
	stale := f.fresh(t, label)
	moved := f.fresh(t, label)
	moved.Set("team", f.beta.Id)
	if err := f.app.Save(moved); err != nil {
		t.Fatal(err)
	}
	f.rec(t, "issues", map[string]any{"title": "b", "number": 1, "team": f.beta.Id, "labels": []string{label.Id}})
	stale.Set("name", "renamed")
	f.refused(t, stale, "issues.labels of issue BETA-1", "from BETA to ALPHA")
}

func TestTeamKeyShape(t *testing.T) {
	for key, ok := range map[string]bool{
		"ENG": true, "WEB-2": true, "A_B": true, "A": true, "ABCDEFGHIJKLMNOP": true,
		"ABCDEFGHIJKLMNOPQ": false, "2ENG": false, "": false, "-A": false, `Q"<B>$(ID)`: false,
		"A B": false, "ÉQUIPE": false, "eng": false, "A\nB": false,
	} {
		if teamKeyShape.MatchString(key) != ok {
			t.Errorf("%q: match=%v, want %v", key, !ok, ok)
		}
	}
}
