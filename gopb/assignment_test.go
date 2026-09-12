package gopb

import (
	"errors"
	"testing"

	"github.com/pocketbase/pocketbase/core"
)

func TestAssignmentInputBoundary(t *testing.T) {
	for _, invalid := range []string{
		`{}`, `{"assignee":null}`, `{"assignee":false}`,
		`{"assignee":"","id":"forged"}`, `{"assignee":"","priority":1.5}`,
		`{"assignee":"","labels":[3]}`,
	} {
		if _, err := parseAssignmentFields([]byte(invalid)); err == nil {
			t.Fatalf("accepted %s", invalid)
		}
	}
	fields, err := parseAssignmentFields([]byte(`{"assignee":"","priority":0,"labels":[],"project":""}`))
	if err != nil || fields.Priority == nil || *fields.Priority != 0 || fields.Labels == nil || len(*fields.Labels) != 0 || fields.Project == nil || fields.Title != nil {
		t.Fatalf("empty versus omitted fields: %#v %v", fields, err)
	}
}

func TestAssignmentFailureRollsBackCompleteEdit(t *testing.T) {
	for _, failure := range []string{"delete", "save"} {
		t.Run(failure, func(t *testing.T) {
			app, issueID, alpha, _ := claimFixture(t)
			held, err := acquireClaim(app, issueID, alpha)
			if err != nil {
				t.Fatal(err)
			}
			reject := func(e *core.RecordEvent) error { return errors.New("injected transaction failure") }
			if failure == "delete" {
				app.OnRecordDelete("claims").BindFunc(reject)
			} else {
				app.OnRecordUpdate("issues").BindFunc(reject)
			}
			none, title := "", "must not commit"
			if _, err := updateAssignment(app, issueID, held.ClaimID, assignmentFields{Assignee: &none, Title: &title}); err == nil {
				t.Fatal("expected injected failure")
			}
			assertClaimState(t, app, issueID, alpha, alpha)
		})
	}
}

func TestAssignmentClaimPolicy(t *testing.T) {
	app, issueID, alpha, beta := claimFixture(t)
	none := ""
	if _, err := updateAssignment(app, issueID, "", assignmentFields{Assignee: &alpha}); err != nil {
		t.Fatal(err)
	}
	assertClaimState(t, app, issueID, "", alpha)
	held, err := acquireClaim(app, issueID, alpha)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := updateAssignment(app, issueID, held.ClaimID, assignmentFields{Assignee: &alpha}); err != nil {
		t.Fatal(err)
	}
	if _, err := updateAssignment(app, issueID, held.ClaimID, assignmentFields{Assignee: &beta}); err == nil {
		t.Fatal("reassignment accepted under a claim")
	}
	assertClaimState(t, app, issueID, alpha, alpha)
	outcome, err := updateAssignment(app, issueID, held.ClaimID, assignmentFields{Assignee: &none})
	if err != nil || outcome.ClaimID != held.ClaimID || outcome.MemberName != "Alpha" {
		t.Fatalf("clear did not release the observed claim: %#v %v", outcome, err)
	}
	assertClaimState(t, app, issueID, "", "")
}

func TestStaleAssignmentCannotChangeNewOrReplacementClaim(t *testing.T) {
	app, issueID, alpha, beta := claimFixture(t)
	held, err := acquireClaim(app, issueID, alpha)
	if err != nil {
		t.Fatal(err)
	}
	title := "must not commit"
	for _, assignee := range []string{"", alpha, beta} {
		if _, err := updateAssignment(app, issueID, "", assignmentFields{Assignee: &assignee, Title: &title}); err == nil {
			t.Fatal("unclaimed observation accepted after acquisition")
		}
		assertClaimState(t, app, issueID, alpha, alpha)
	}
	if _, err := releaseClaim(app, issueID, held.ClaimID); err != nil {
		t.Fatal(err)
	}
	if _, err := acquireClaim(app, issueID, alpha); err != nil {
		t.Fatal(err)
	}
	none := ""
	if _, err := updateAssignment(app, issueID, held.ClaimID, assignmentFields{Assignee: &none, Title: &title}); err == nil {
		t.Fatal("old identity accepted for a replacement by the same member")
	}
	assertClaimState(t, app, issueID, alpha, alpha)
}
