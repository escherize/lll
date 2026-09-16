package gopb

import (
	"testing"
	"time"
)

// LLL-183: a hold older than 24 hours frees itself, and leaves the issue in
// the state a deliberate `lll issue release` would have left it in.
func TestExpireClaimsReleasesOnlyTheStaleOnes(t *testing.T) {
	app, issueID, alpha, _ := claimFixture(t)
	if _, err := acquireClaim(app, issueID, alpha); err != nil {
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
	if _, err := acquireClaim(app, issueID, alpha); err != nil {
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
