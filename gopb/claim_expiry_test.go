package gopb

import (
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/core"
)

// LLL-183: a hold older than 24 hours frees itself, and leaves the issue in
// the state a deliberate `lll issue release` would have left it in.
func TestExpireClaimsReleasesOnlyTheStaleOnes(t *testing.T) {
	app, issueID, alpha, _ := claimFixture(t)
	if _, err := acquireClaim(app, issueID, alpha, ""); err != nil {
		t.Fatal(err)
	}
	assertClaimState(t, app, issueID, alpha, alpha)

	// A claim made a minute ago is not stale, however often the sweep runs.
	expired, err := expireClaims(app, time.Now(), claimMaxAge)
	if err != nil {
		t.Fatal(err)
	}
	if expired != 0 {
		t.Fatalf("a fresh claim was expired: %d", expired)
	}
	assertClaimState(t, app, issueID, alpha, alpha)

	// The same claim, judged from a day and a minute later. Time is a
	// parameter precisely so this does not have to wait.
	expired, err = expireClaims(app, time.Now().Add(claimMaxAge+time.Minute), claimMaxAge)
	if err != nil {
		t.Fatal(err)
	}
	if expired != 1 {
		t.Fatalf("expected one expiry, got %d", expired)
	}
	// No claim, no assignee - and the rest of the issue untouched.
	assertClaimState(t, app, issueID, "", "")
}

// The assignee is cleared only when it is still the holder, exactly as
// releaseClaim decides it. Someone else's assignment is not the claim's to
// undo, and an expiry that cleared it would quietly unassign real work.
func TestExpireClaimsLeavesAnotherMembersAssignment(t *testing.T) {
	app, issueID, alpha, beta := claimFixture(t)
	if _, err := acquireClaim(app, issueID, alpha, ""); err != nil {
		t.Fatal(err)
	}
	issue, err := app.FindRecordById("issues", issueID)
	if err != nil {
		t.Fatal(err)
	}
	issue.Set("assignee", beta)
	if err := app.Save(issue); err != nil {
		t.Fatal(err)
	}

	expired, err := expireClaims(app, time.Now().Add(claimMaxAge+time.Minute), claimMaxAge)
	if err != nil {
		t.Fatal(err)
	}
	if expired != 1 {
		t.Fatalf("expected one expiry, got %d", expired)
	}
	assertClaimState(t, app, issueID, "", beta)
}

// The sweep is registered on PocketBase's own scheduler, so it runs whether or
// not anyone is running lll. Asserted by id, because a typo in the schedule
// would otherwise be invisible until a claim failed to expire a day later.
func TestClaimExpiryIsScheduled(t *testing.T) {
	app, _, _, _ := claimFixture(t)
	registerClaimExpiry(app)
	var found *struct{}
	for _, job := range app.Cron().Jobs() {
		if job.Id() == "lllExpireClaims" {
			found = &struct{}{}
			if job.Expression() != claimSweepSchedule {
				t.Fatalf("wrong schedule: %s", job.Expression())
			}
		}
	}
	if found == nil {
		t.Fatal("the claim sweep is not on the scheduler")
	}
}

// LLL-452: the release leaves a record on the issue. The first sweep on the
// hosted board freed 123 claims and nothing anywhere said so.
func TestExpiredClaimIsAnnouncedOnAnOpenIssue(t *testing.T) {
	app, issueID, alpha, _ := claimFixture(t)
	if _, err := acquireClaim(app, issueID, alpha, ""); err != nil {
		t.Fatal(err)
	}
	if _, err := expireClaims(app, time.Now().Add(claimMaxAge+time.Minute), claimMaxAge); err != nil {
		t.Fatal(err)
	}
	comments, err := app.FindAllRecords("comments")
	if err != nil {
		t.Fatal(err)
	}
	if len(comments) != 1 {
		t.Fatalf("expected one comment, got %d", len(comments))
	}
	body := comments[0].GetString("body")
	// It names the holder, because the comment itself has no author: the
	// sweep is not a member and must not mint one.
	if !strings.Contains(body, "Alpha") {
		t.Fatalf("the comment does not name the holder: %s", body)
	}
	if !strings.Contains(body, "24 hours") {
		t.Fatalf("the comment does not say how long it stood: %s", body)
	}
	if comments[0].GetString("author") != "" {
		t.Fatal("the sweep attributed its comment to a member")
	}
	if comments[0].GetString("issue") != issueID {
		t.Fatal("the comment landed on the wrong issue")
	}
}

// Finished work gets none: 119 of the first sweep's 123 releases were holds on
// done issues, and a note there is noise on something nobody is reading.
func TestExpiredClaimOnFinishedWorkIsNotAnnounced(t *testing.T) {
	for _, state := range []string{"done", "cancelled"} {
		app, issueID, alpha, _ := claimFixture(t)
		issue, err := app.FindRecordById("issues", issueID)
		if err != nil {
			t.Fatal(err)
		}
		issue.Set("state", state)
		if err := app.Save(issue); err != nil {
			t.Fatal(err)
		}
		if _, err := acquireClaim(app, issueID, alpha, ""); err != nil {
			t.Fatal(err)
		}
		expired, err := expireClaims(app, time.Now().Add(claimMaxAge+time.Minute), claimMaxAge)
		if err != nil {
			t.Fatal(err)
		}
		if expired != 1 {
			t.Fatalf("%s: the claim was not released: %d", state, expired)
		}
		comments, err := app.FindAllRecords("comments")
		if err != nil {
			t.Fatal(err)
		}
		if len(comments) != 0 {
			t.Fatalf("%s: expected no comment, got %d", state, len(comments))
		}
	}
}

// The release is the half that must not be undone by the half that records it.
func TestAnnouncementFailureDoesNotUndoTheRelease(t *testing.T) {
	app, issueID, alpha, _ := claimFixture(t)
	if _, err := acquireClaim(app, issueID, alpha, ""); err != nil {
		t.Fatal(err)
	}
	// A comment collection that refuses every write, which is the shape of any
	// announcement failure: a validation rule, a hook, a full disk.
	app.OnRecordCreate("comments").BindFunc(func(e *core.RecordEvent) error {
		return errors.New("injected comment failure")
	})
	expired, err := expireClaims(app, time.Now().Add(claimMaxAge+time.Minute), claimMaxAge)
	if err != nil {
		t.Fatal(err)
	}
	if expired != 1 {
		t.Fatalf("a failed announcement changed the expiry count: %d", expired)
	}
	// Gone for good: a release that rolled back here would hand the same claim
	// to the next sweep, every hour, forever.
	assertClaimState(t, app, issueID, "", "")
}
