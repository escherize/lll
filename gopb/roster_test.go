package gopb

import (
	"testing"

	"github.com/pocketbase/pocketbase/core"
)

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
		{issues, `(title = "a" || (state = "todo" && assignee.kind = "bot"))`, "", true},
	} {
		if got := crossesRoster(app, c.base, c.filter, c.sort); got != c.crosses {
			t.Errorf("%s filter=%q sort=%q: crosses=%v, want %v", c.base.Name, c.filter, c.sort, got, c.crosses)
		}
	}
}
