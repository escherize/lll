package gopb

import (
	"encoding/json"
	"net/url"
	"testing"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
)

// A webhook payload has no viewer, so it expands only an assignee every
// member of the issue's team may see, and never with another team's id.
func TestWebhookPayloadExpandsOnlyATeamVisibleAssignee(t *testing.T) {
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Cleanup)
	teams := core.NewBaseCollection("teams")
	teams.Fields.Add(&core.TextField{Name: "key"})
	if err := app.Save(teams); err != nil {
		t.Fatal(err)
	}
	members := core.NewBaseCollection("members")
	members.Fields.Add(&core.TextField{Name: "name"}, &core.TextField{Name: "scope"}, &core.TextField{Name: "kind"},
		&core.RelationField{Name: "teams", CollectionId: teams.Id, MaxSelect: 99})
	if err := app.Save(members); err != nil {
		t.Fatal(err)
	}
	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(&core.RelationField{Name: "team", CollectionId: teams.Id, MaxSelect: 1},
		&core.RelationField{Name: "assignee", CollectionId: members.Id, MaxSelect: 1})
	if err := app.Save(issues); err != nil {
		t.Fatal(err)
	}
	eng, ops := core.NewRecord(teams), core.NewRecord(teams)
	eng.Set("key", "ENG")
	ops.Set("key", "OPS")
	for _, r := range []*core.Record{eng, ops} {
		if err := app.Save(r); err != nil {
			t.Fatal(err)
		}
	}
	bot, both := core.NewRecord(members), core.NewRecord(members)
	bot.Load(map[string]any{"name": "bot-garden", "scope": "all", "kind": botKind})
	both.Load(map[string]any{"name": "both", "scope": "teams", "kind": "person", "teams": []string{eng.Id, ops.Id}})
	for _, r := range []*core.Record{bot, both} {
		if err := app.Save(r); err != nil {
			t.Fatal(err)
		}
	}
	payload := func(assignee string) map[string]any {
		issue := core.NewRecord(issues)
		issue.Set("team", eng.Id)
		issue.Set("assignee", assignee)
		body, err := webhookPayload(app, "create", issue)
		if err != nil {
			t.Fatal(err)
		}
		var out struct {
			Record struct {
				Expand map[string]any `json:"expand"`
			} `json:"record"`
		}
		if err := json.Unmarshal(body, &out); err != nil {
			t.Fatal(err)
		}
		return out.Record.Expand
	}
	if got := payload(bot.Id); got["assignee"] != nil {
		t.Fatalf("a full-access bot was expanded: %v", got["assignee"])
	}
	got, _ := payload(both.Id)["assignee"].(map[string]any)
	if got == nil || got["name"] != "both" {
		t.Fatalf("a team member was not expanded: %v", got)
	}
	if ids, _ := got["teams"].([]any); len(ids) != 1 || ids[0] != eng.Id {
		t.Fatalf("another team's id rode the payload: %v", got["teams"])
	}
}

// LLL-551: a claim refusal names the holder only to a caller whose roster
// includes it. A full-access bot is hidden from a member limited to teams.
func TestClaimRefusalHidesAHolderOutsideTheRoster(t *testing.T) {
	app, issueID, alpha, beta := claimFixture(t)
	holder, err := app.FindRecordById("members", alpha)
	if err != nil {
		t.Fatal(err)
	}
	holder.Set("kind", botKind)
	guest, err := app.FindRecordById("members", beta)
	if err != nil {
		t.Fatal(err)
	}
	guest.Set("scope", "teams")
	for _, m := range []*core.Record{holder, guest} {
		if err := app.Save(m); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := acquireClaim(app, issueID, alpha, ""); err != nil {
		t.Fatal(err)
	}
	_, err = acquireClaim(app, issueID, beta, "")
	if err == nil || err.Error() != "issue is already claimed by a hidden member" {
		t.Fatalf("scoped caller: %v", err)
	}
	// A superuser (no member id) and the holder still read the name.
	if got := rosterName(app, "", alpha, "x"); got != "Alpha" {
		t.Fatalf("superuser read %q", got)
	}
	if got := rosterName(app, alpha, alpha, "x"); got != "Alpha" {
		t.Fatalf("holder read %q", got)
	}
	// A full-access person is visible to everyone.
	holder.Set("kind", "person")
	if err := app.Save(holder); err != nil {
		t.Fatal(err)
	}
	if got := rosterName(app, beta, alpha, "x"); got != "Alpha" {
		t.Fatalf("full-access person read %q", got)
	}
}

// Relation hops into or out of members are refused for a narrow caller;
// hops between other collections and plain fields are not.
func TestRosterProbePaths(t *testing.T) {
	app, _, _, _ := claimFixture(t)
	issues, err := app.FindCollectionByNameOrId("issues")
	if err != nil {
		t.Fatal(err)
	}
	comments, err := app.FindCollectionByNameOrId("comments")
	if err != nil {
		t.Fatal(err)
	}
	members, err := app.FindCollectionByNameOrId("members")
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct {
		base         *core.Collection
		filter, sort string
		crosses      bool
	}{
		{issues, `assignee.name ~ "bot-g%"`, "", true},
		{issues, `assignee:lower.name = "x"`, "", true},
		{issues, "", "-assignee.name", true},
		{issues, `assignee = "abc"`, "", false},
		{issues, `title ~ "x"`, "-created", false},
		{comments, `issue.assignee.name = "x"`, "", true},
		{comments, `issue.title = "x" && author = "abc"`, "", false},
		{members, `issues_via_assignee.title ~ "x"`, "", true},
		{members, `comments_via_author.body ~ "x"`, "", true},
		{members, `name = "x" || kind = "bot"`, "name", false},
		{members, "", "email", true},
		{members, `email ~ "a"`, "", true},
		{members, "teams:length = 2", "", true},
		{members, `teams ~ "x"`, "-teams", true},
		{issues, `team = "x"`, "", false},
		{issues, `(title = "a" || (state = "todo" && assignee.kind = "bot"))`, "", true},
	} {
		if got := probeRefusal(app, c.base, c.filter, c.sort) == rosterProbeRefusal; got != c.crosses {
			t.Errorf("%s filter=%q sort=%q: crosses=%v, want %v", c.base.Name, c.filter, c.sort, got, c.crosses)
		}
	}
}

// LLL-634 review round 2: options are decoded the way PocketBase decodes
// them, so a trailing duplicate key cannot hide the filter; and an all-scope
// read-only member is kept out of other members' favorites and views.
func TestCallerRefusalByAccess(t *testing.T) {
	f := newTeamRefFixture(t)
	narrow := f.rec(t, "members", map[string]any{"name": "narrow", "scope": "teams", "mode": "rw", "teams": []string{f.alpha.Id}})
	allro := f.rec(t, "members", map[string]any{"name": "allro", "scope": "all", "mode": "ro"})
	allrw := f.rec(t, "members", map[string]any{"name": "allrw", "scope": "all", "mode": "rw"})
	topic := func(options string) string { return "issues/*?options=" + url.QueryEscape(options) }
	for _, c := range []struct {
		who     *core.Record
		topic   string
		refused bool
	}{
		{narrow, topic(`{"query":{"filter":"labels.name ~ \"%e%\""}}`), true},
		{narrow, topic(`{"query":{"filter":"labels.name ~ \"%e%\""},"query":1}`), true},
		{narrow, topic(`{"query":{"filter":"labels.name ~ \"%e%\""},"QUERY":1}`), true},
		{narrow, topic(`{"query":{"filter":"labels.name ~ \"%e%\""},"headers":1}`), true},
		{narrow, topic(`{"query":{"filter":"state = \"todo\""},"query":1}`), false},
		{narrow, "issues/*", false},
		{allrw, topic(`{"query":{"filter":"labels.name ~ \"%e%\""}}`), false},
		{allro, topic(`{"query":{"filter":"favorites_via_issue.id ?!= \"x\" || id != \"\""}}`), true},
		{allrw, topic(`{"query":{"filter":"favorites_via_issue.id ?!= \"x\" || id != \"\""}}`), false},
		{allro, topic(`{"query":{"filter":"labels.name ~ \"%e%\""}}`), false},
	} {
		if got := topicRefusal(f.app, c.who, c.topic) != ""; got != c.refused {
			t.Errorf("%s %s: refused=%v, want %v", c.who.GetString("name"), c.topic, got, c.refused)
		}
	}
}

// LLL-634: a narrow caller may not read rows of another team through a
// multi-match subquery. ?-operators, ids matched exactly and single-relation
// hops use the joined, rule-checked row and stay allowed.
func TestRelationProbePaths(t *testing.T) {
	f := newTeamRefFixture(t)
	issues, _ := f.app.FindCollectionByNameOrId("issues")
	labels, _ := f.app.FindCollectionByNameOrId("labels")
	for _, c := range []struct {
		base         *core.Collection
		filter, sort string
		refused      bool
	}{
		// The audit repros.
		{issues, `labels.name ~ "%e%"`, "", true},
		{issues, `blocked_by.title ~ "%i%"`, "", true},
		// Every plain operator, modifiers, negations, nesting, functions.
		{issues, `labels.name = "x"`, "", true},
		{issues, `labels.name != "x"`, "", true},
		{issues, `labels.name !~ "x"`, "", true},
		{issues, `labels.name > "m"`, "", true},
		{issues, `labels.name:lower = "x"`, "", true},
		{issues, `labels.name:each ~ "x"`, "", true},
		{issues, `"x" = labels.name`, "", true},
		{issues, `state = "todo" && (title = "a" || blocked_by.labels.name ?~ "x" || blocked_by.title = "y")`, "", true},
		{issues, `strftime('%Y', blocked_by.created) = "2026"`, "", true},
		{issues, `@collection.labels.name != "secret"`, "", true},
		{issues, `@collection.issues:other.title ~ "x"`, "", true},
		{labels, `issues_via_labels.title ~ "x"`, "", true},
		{issues, `docs_via_issues.slug = "x"`, "", true},
		// Review F1: a member-scoped collection, with any operator.
		{issues, `favorites_via_issue.id ?!= "zz" || id != ""`, "", true},
		{issues, `favorites_via_issue.member ?= "x"`, "", true},
		{issues, "", "favorites_via_issue.id", true},
		// Stored ids: exact matches only, no modifiers, no sort.
		{issues, `labels ~ "a"`, "", true},
		{issues, `labels = "id"`, "", true},
		{issues, `labels:length > 1`, "", true},
		{issues, `labels:each ?= "x"`, "", true},
		{issues, `project ~ "a"`, "", true},
		{issues, `project > "m"`, "", true},
		{issues, "", "labels", true},
		{issues, "", "-project", true},
		{issues, "", "labels.name", true},
		{issues, "", "@collection.labels.name", true},
		// Allowed.
		{issues, `labels.name ?~ "%e%"`, "", false},
		{issues, `labels.id ?= "id" || labels.id ?= "id2"`, "", false},
		{issues, `blocked_by.id ?= "id"`, "", false},
		{issues, `blocked_by.title ?!~ "x"`, "", false},
		{issues, `labels ?= "id"`, "", false},
		{issues, `labels ?!= "id"`, "", false},
		{issues, `project = "id" && team = "t" && project != ""`, "", false},
		{issues, `project.name ~ "x"`, "project.name", false},
		{issues, `@collection.labels.name ?= "x"`, "", false},
		{issues, `state = "todo" && title ~ "x" && number > 3`, "-created,number", false},
		{issues, `@request.auth.id != ""`, "", false},
		{labels, `issues_via_labels.title ?~ "x"`, "", false},
	} {
		got := probeRefusal(f.app, c.base, c.filter, c.sort) == relationProbeRefusal
		if got != c.refused {
			t.Errorf("%s filter=%q sort=%q: refused=%v, want %v", c.base.Name, c.filter, c.sort, got, c.refused)
		}
	}
}
