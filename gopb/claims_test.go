package gopb

import (
	"errors"
	"sync"
	"testing"

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
	issues.Fields.Add(&core.RelationField{Name: "assignee", CollectionId: members.Id, MaxSelect: 1}, &core.TextField{Name: "title"})
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
	if _, err := releaseClaim(app, issueID, held.ClaimID); err == nil {
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
	outcome, err := releaseClaim(app, issueID, first.ClaimID)
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
	if _, err := releaseClaim(app, issueID, held.Id); err != nil {
		t.Fatal(err)
	}
	replacement, err := acquireClaim(app, issueID, beta)
	if err != nil {
		t.Fatal(err)
	}
	if replacement.ClaimID == held.Id {
		t.Fatal("claim identity reused")
	}
	if _, err := releaseClaim(app, issueID, held.Id); err == nil {
		t.Fatal("stale release accepted")
	}
	assertClaimState(t, app, issueID, beta, beta)
}
