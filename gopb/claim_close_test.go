package gopb

import (
	"testing"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/core"
)

func issueState(t *testing.T, app core.App, issueID string) string {
	t.Helper()
	issue, err := app.FindRecordById("issues", issueID)
	if err != nil {
		t.Fatal(err)
	}
	return issue.GetString("state")
}

func setState(t *testing.T, app core.App, issueID, state string) {
	t.Helper()
	issue, err := app.FindRecordById("issues", issueID)
	if err != nil {
		t.Fatal(err)
	}
	issue.Set("state", state)
	if err := app.Save(issue); err != nil {
		t.Fatal(err)
	}
}

// D3 (LLL-640): the holder's close releases the claim and keeps the
// assignee; keepClaim keeps the hold; no comment either way.
func TestCloseByTheHolderReleases(t *testing.T) {
	app, issueID, alpha, _ := claimFixture(t)
	held, err := acquireClaim(app, issueID, alpha, "wt-a")
	if err != nil {
		t.Fatal(err)
	}
	outcome, err := closeIssue(app, issueID, held.ClaimID, releaser{memberID: alpha, agent: "wt-a"}, true)
	if err != nil || outcome.Forced || !outcome.AlreadyOwned {
		t.Fatalf("keep-claim close: %#v %v", outcome, err)
	}
	assertClaimState(t, app, issueID, alpha, alpha)
	if issueState(t, app, issueID) != "done" {
		t.Fatal("keep-claim close did not close")
	}
	setState(t, app, issueID, "in-progress")

	outcome, err = closeIssue(app, issueID, held.ClaimID, releaser{memberID: alpha, agent: "wt-a"}, false)
	if err != nil || outcome.Forced || outcome.ClaimID != held.ClaimID {
		t.Fatalf("holder close: %#v %v", outcome, err)
	}
	assertClaimState(t, app, issueID, "", alpha)
	if issueState(t, app, issueID) != "done" {
		t.Fatal("holder close did not close")
	}
	assertComments(t, app, issueID)

	// Nothing claimed: the observed claim is "" and the close is plain.
	setState(t, app, issueID, "todo")
	if outcome, err := closeIssue(app, issueID, "", releaser{memberID: alpha}, false); err != nil || outcome.ClaimID != "" {
		t.Fatalf("unclaimed close: %#v %v", outcome, err)
	}
}

// A non-holder's close takes the issue from its holder, so it follows the
// release rule: refused without force, and forced it releases and comments.
// It may not keep another member's claim.
func TestCloseByANonHolderNeedsForce(t *testing.T) {
	app, issueID, alpha, beta := claimFixture(t)
	held, err := acquireClaim(app, issueID, alpha, "")
	if err != nil {
		t.Fatal(err)
	}
	for _, by := range []releaser{{memberID: beta}, {}} {
		if _, err := closeIssue(app, issueID, held.ClaimID, by, false); err == nil {
			t.Fatalf("unforced close by %#v succeeded", by)
		}
	}
	_, err = closeIssue(app, issueID, held.ClaimID, releaser{memberID: beta, force: true}, true)
	if err == nil || err.Error() != "the claim is held by Alpha; only the holder keeps a claim while closing, and closing anyone else's claimed issue releases it" {
		t.Fatalf("non-holder keep-claim: %v", err)
	}
	if _, err := closeIssue(app, issueID, "stale", releaser{memberID: alpha}, false); err == nil {
		t.Fatal("close over a claim it did not observe")
	}
	assertClaimState(t, app, issueID, alpha, alpha)
	if issueState(t, app, issueID) != "in-progress" {
		t.Fatal("a refused close changed the state")
	}
	assertComments(t, app, issueID)

	outcome, err := closeIssue(app, issueID, held.ClaimID, releaser{memberID: beta, force: true, reason: "done elsewhere"}, false)
	if err != nil || !outcome.Forced {
		t.Fatalf("forced close: %#v %v", outcome, err)
	}
	assertClaimState(t, app, issueID, "", alpha)
	assertComments(t, app, issueID, beta+": Beta force-released Alpha's claim.\n\nReason: done elsewhere")
	assertSystemComments(t, app, issueID, 1)
}

// LLL-633: a server-written comment is stored text every reader of the issue
// sees, so it names a member only when everyone on the issue's team may see
// that member. LLL-654: it is marked as the server's.
func TestForcedReleaseCommentNamesOnlyTeamRosterMembers(t *testing.T) {
	app, issueID, alpha, beta := claimFixture(t)
	hidden, err := app.FindRecordById("members", beta)
	if err != nil {
		t.Fatal(err)
	}
	hidden.Set("scope", "")
	if err := app.Save(hidden); err != nil {
		t.Fatal(err)
	}
	held, err := acquireClaim(app, issueID, beta, "bot-a")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := releaseClaim(app, issueID, held.ClaimID, releaser{memberID: alpha, force: true}); err != nil {
		t.Fatal(err)
	}
	held, err = acquireClaim(app, issueID, alpha, "")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := releaseClaim(app, issueID, held.ClaimID, releaser{memberID: beta, force: true}); err != nil {
		t.Fatal(err)
	}
	assertComments(t, app, issueID,
		alpha+": Alpha force-released a member outside this team (agent bot-a)'s claim.",
		beta+": A member outside this team force-released Alpha's claim.")
	assertSystemComments(t, app, issueID, 2)
}

func assertSystemComments(t *testing.T, app core.App, issueID string, want int) {
	t.Helper()
	records, err := app.FindRecordsByFilter("comments", "issue={:issue} && author_kind='system'", "", 0, 0, dbx.Params{"issue": issueID})
	if err != nil {
		t.Fatal(err)
	}
	if len(records) != want {
		t.Fatalf("%d system comments, want %d", len(records), want)
	}
}
