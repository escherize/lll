package gopb

import (
	"errors"
	"sort"
	"strings"
	"sync"
	"testing"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tests"
)

func claimFixture(t *testing.T) (core.App, string, string, string) {
	t.Helper()
	app, err := tests.NewTestApp()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(app.Cleanup)
	members := core.NewBaseCollection("members")
	members.Fields.Add(&core.TextField{Name: "name", Required: true})
	if err := app.Save(members); err != nil {
		t.Fatal(err)
	}
	issues := core.NewBaseCollection("issues")
	issues.Fields.Add(
		&core.RelationField{Name: "assignee", CollectionId: members.Id, MaxSelect: 1},
		&core.TextField{Name: "title"},
		// LLL-452: the expiry announcement is skipped on finished work.
		&core.TextField{Name: "state"},
	)
	if err := app.Save(issues); err != nil {
		t.Fatal(err)
	}
	claims := core.NewBaseCollection("claims")
	claims.Fields.Add(&core.RelationField{Name: "issue", CollectionId: issues.Id, MaxSelect: 1, Required: true},
		&core.RelationField{Name: "member", CollectionId: members.Id, MaxSelect: 1, Required: true},
		&core.AutodateField{Name: "created", OnCreate: true})
	claims.Indexes = []string{"CREATE UNIQUE INDEX idx_claim_test_issue ON claims (issue)"}
	if err := app.Save(claims); err != nil {
		t.Fatal(err)
	}
	// LLL-452: the sweep records an expiry as a comment on the issue.
	comments := core.NewBaseCollection("comments")
	comments.Fields.Add(
		&core.RelationField{Name: "issue", CollectionId: issues.Id, MaxSelect: 1, Required: true},
		&core.RelationField{Name: "author", CollectionId: members.Id, MaxSelect: 1},
		&core.TextField{Name: "body", Required: true},
		&core.AutodateField{Name: "created", OnCreate: true},
	)
	if err := app.Save(comments); err != nil {
		t.Fatal(err)
	}
	a, b := core.NewRecord(members), core.NewRecord(members)
	a.Set("name", "Alpha")
	b.Set("name", "Beta")
	for _, member := range []*core.Record{a, b} {
		if err := app.Save(member); err != nil {
			t.Fatal(err)
		}
	}
	issue := core.NewRecord(issues)
	issue.Set("title", "preserve title")
	issue.Set("state", "in-progress")
	if err := app.Save(issue); err != nil {
		t.Fatal(err)
	}
	return app, issue.Id, a.Id, b.Id
}

func assertClaimState(t *testing.T, app core.App, issueID, holder, assignee string) {
	t.Helper()
	held, err := currentClaim(app, issueID)
	if err != nil {
		t.Fatal(err)
	}
	if holder == "" {
		if held != nil {
			t.Fatal("unexpected claim")
		}
	} else if held == nil || held.GetString("member") != holder {
		t.Fatal("wrong claim holder")
	}
	issue, err := app.FindRecordById("issues", issueID)
	if err != nil {
		t.Fatal(err)
	}
	if issue.GetString("assignee") != assignee || issue.GetString("title") != "preserve title" {
		t.Fatal("assignment/title mismatch")
	}
}

func TestClaimTransitionsRollbackBothWrites(t *testing.T) {
	app, issueID, alpha, _ := claimFixture(t)
	fail := false
	app.OnRecordUpdate("issues").BindFunc(func(e *core.RecordEvent) error {
		if fail {
			return errors.New("injected assignment failure")
		}
		return e.Next()
	})
	fail = true
	if _, err := acquireClaim(app, issueID, alpha); err == nil {
		t.Fatal("expected failure")
	}
	assertClaimState(t, app, issueID, "", "")
	fail = false
	held, err := acquireClaim(app, issueID, alpha)
	if err != nil {
		t.Fatal(err)
	}
	fail = true
	if _, err := releaseClaim(app, issueID, held.ClaimID, releaser{memberID: alpha}); err == nil {
		t.Fatal("expected release failure")
	}
	assertClaimState(t, app, issueID, alpha, alpha)
}

func TestClaimIdempotencyAndUnrelatedAssignment(t *testing.T) {
	app, issueID, alpha, beta := claimFixture(t)
	first, err := acquireClaim(app, issueID, alpha)
	if err != nil {
		t.Fatal(err)
	}
	again, err := acquireClaim(app, issueID, alpha)
	if err != nil || !again.AlreadyOwned || again.ClaimID != first.ClaimID || again.Created != first.Created {
		t.Fatalf("idempotent claim: %#v %v", again, err)
	}
	issue, _ := app.FindRecordById("issues", issueID)
	issue.Set("assignee", beta)
	if err := app.Save(issue); err != nil {
		t.Fatal(err)
	}
	outcome, err := releaseClaim(app, issueID, first.ClaimID, releaser{memberID: alpha})
	if err != nil || outcome.ClearedAssignee {
		t.Fatalf("unrelated assignment: %#v %v", outcome, err)
	}
	assertClaimState(t, app, issueID, "", beta)
}

func TestConcurrentClaimantsAndStaleRelease(t *testing.T) {
	app, issueID, alpha, beta := claimFixture(t)
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		member := alpha
		if i%2 != 0 {
			member = beta
		}
		wg.Add(1)
		go func() { defer wg.Done(); _, _ = acquireClaim(app, issueID, member) }()
	}
	wg.Wait()
	held, err := currentClaim(app, issueID)
	if err != nil || held == nil {
		t.Fatalf("missing winning claim: %v", err)
	}
	assertClaimState(t, app, issueID, held.GetString("member"), held.GetString("member"))
	if _, err := releaseClaim(app, issueID, held.Id, releaser{memberID: held.GetString("member")}); err != nil {
		t.Fatal(err)
	}
	replacement, err := acquireClaim(app, issueID, beta)
	if err != nil {
		t.Fatal(err)
	}
	if replacement.ClaimID == held.Id {
		t.Fatal("claim identity reused")
	}
	if _, err := releaseClaim(app, issueID, held.Id, releaser{memberID: held.GetString("member")}); err == nil {
		t.Fatal("stale release accepted")
	}
	assertClaimState(t, app, issueID, beta, beta)
}

// LLL-512: the holder releases freely; anyone else is refused unless they
// force, and a forced release leaves a comment naming both members.
func TestReleaseRequiresHolderOrForce(t *testing.T) {
	app, issueID, alpha, beta := claimFixture(t)
	held, err := acquireClaim(app, issueID, alpha)
	if err != nil {
		t.Fatal(err)
	}
	for _, by := range []releaser{{memberID: beta}, {}} {
		if _, err := releaseClaim(app, issueID, held.ClaimID, by); err == nil ||
			err.Error() != "the claim is held by Alpha; releasing another member's claim needs force" {
			t.Fatalf("non-holder %#v: %v", by, err)
		}
		assertClaimState(t, app, issueID, alpha, alpha)
	}
	assertComments(t, app, issueID)

	outcome, err := releaseClaim(app, issueID, held.ClaimID, releaser{memberID: alpha, force: true})
	if err != nil || outcome.Forced || !outcome.ClearedAssignee {
		t.Fatalf("holder release: %#v %v", outcome, err)
	}
	assertClaimState(t, app, issueID, "", "")
	assertComments(t, app, issueID)

	held, err = acquireClaim(app, issueID, alpha)
	if err != nil {
		t.Fatal(err)
	}
	outcome, err = releaseClaim(app, issueID, held.ClaimID, releaser{memberID: beta, force: true, reason: "Alpha's agent crashed"})
	if err != nil || !outcome.Forced || outcome.MemberName != "Alpha" {
		t.Fatalf("forced release: %#v %v", outcome, err)
	}
	assertClaimState(t, app, issueID, "", "")
	assertComments(t, app, issueID, beta+": Beta force-released Alpha's claim.\n\nReason: Alpha's agent crashed")

	held, err = acquireClaim(app, issueID, alpha)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := releaseClaim(app, issueID, held.ClaimID, releaser{force: true}); err != nil {
		t.Fatal(err)
	}
	assertComments(t, app, issueID,
		beta+": Beta force-released Alpha's claim.\n\nReason: Alpha's agent crashed",
		": An administrator force-released Alpha's claim.")
}

// The comment is part of the forced release: if it cannot be written, the
// claim stays where it was.
func TestForcedReleaseRollsBackWithoutItsComment(t *testing.T) {
	app, issueID, alpha, beta := claimFixture(t)
	held, err := acquireClaim(app, issueID, alpha)
	if err != nil {
		t.Fatal(err)
	}
	app.OnRecordCreate("comments").BindFunc(func(e *core.RecordEvent) error {
		return errors.New("injected comment failure")
	})
	if _, err := releaseClaim(app, issueID, held.ClaimID, releaser{memberID: beta, force: true}); err == nil {
		t.Fatal("forced release committed without its comment")
	}
	assertClaimState(t, app, issueID, alpha, alpha)
}

// assertComments pins the issue's comments as "author: body". Sorted, not by
// creation time: two comments inside one millisecond would tie.
func assertComments(t *testing.T, app core.App, issueID string, want ...string) {
	t.Helper()
	records, err := app.FindRecordsByFilter("comments", "issue={:issue}", "", 0, 0, dbx.Params{"issue": issueID})
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, r := range records {
		got = append(got, r.GetString("author")+": "+r.GetString("body"))
	}
	sort.Strings(got)
	sort.Strings(want)
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("comments:\n got %q\nwant %q", got, want)
	}
}
