package gopb

import (
	"encoding/json"
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
		if got := crossesRoster(app, c.base, c.filter, c.sort); got != c.crosses {
			t.Errorf("%s filter=%q sort=%q: crosses=%v, want %v", c.base.Name, c.filter, c.sort, got, c.crosses)
		}
	}
}
