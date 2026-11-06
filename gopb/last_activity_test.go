package gopb

import (
	"errors"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/core"
)

func activityDateFixture(t *testing.T) (core.App, string) {
	t.Helper()
	app, id, _, _ := auditFixture(t)
	events, err := app.FindCollectionByNameOrId("audit_events")
	if err != nil {
		t.Fatal(err)
	}
	events.Fields.Add(&core.AutodateField{Name: "created", OnCreate: true})
	if err := app.Save(events); err != nil {
		t.Fatal(err)
	}
	issues, err := app.FindCollectionByNameOrId("issues")
	if err != nil {
		t.Fatal(err)
	}
	issues.Fields.Add(&core.DateField{Name: "last_activity"}, &core.AutodateField{Name: "updated", OnCreate: true, OnUpdate: true})
	if err := app.Save(issues); err != nil {
		t.Fatal(err)
	}
	return app, id
}

func TestLastActivityPreservesNewerDateOnStaleIssueSave(t *testing.T) {
	app, id := activityDateFixture(t)
	stale, _ := app.FindRecordById("issues", id)
	// Simulate activity committed after the caller read its issue. A future
	// clock value also checks monotonicity after the host clock moves back.
	date := "2060-01-01 00:00:00.000Z"
	if _, err := app.DB().NewQuery("UPDATE issues SET last_activity = '" + date + "'").Execute(); err != nil {
		t.Fatal(err)
	}
	stale.Set("title", "save from stale read")
	stale.Set("last_activity", "2099-01-01 00:00:00.000Z")
	if err := app.Save(stale); err != nil {
		t.Fatal(err)
	}
	fresh, _ := app.FindRecordById("issues", id)
	if fresh.GetString("last_activity") != date {
		t.Fatal("stale save lost or forged the newer activity date")
	}
}

func TestLastActivityTracksClaimRenewalAndExpiry(t *testing.T) {
	app, id := activityDateFixture(t)
	member, _ := app.FindFirstRecordByData("members", "name", "Alpha")
	held, err := acquireClaim(app, id, member.Id, "activity")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := renewClaim(app, id, held.ClaimID, releaser{memberID: member.Id}); err != nil {
		t.Fatal(err)
	}
	if n, err := expireClaims(app, time.Now().Add(48*time.Hour), claimMaxAge); err != nil || n != 1 {
		t.Fatalf("expiry %d: %v", n, err)
	}
	rows, _ := app.FindRecordsByFilter("audit_events", "", "-seq", 1, 0)
	issue, _ := app.FindRecordById("issues", id)
	if issue.GetString("last_activity") < rows[0].GetString("created") {
		t.Fatal("claim lifecycle missing from issue activity")
	}
}

func TestLastActivityTracksCommentsWithoutTouchingIssueUpdated(t *testing.T) {
	app, id := activityDateFixture(t)
	issue, _ := app.FindRecordById("issues", id)
	issue.Set("title", "new title")
	if err := app.Save(issue); err != nil {
		t.Fatal(err)
	}
	if issue.GetString("last_activity") == "" {
		t.Fatal("issue save has no activity date")
	}
	updated := issue.GetString("updated")
	comments, _ := app.FindCollectionByNameOrId("comments")
	comment := core.NewRecord(comments)
	comment.Set("issue", id)
	comment.Set("body", "progress")
	if err := app.Save(comment); err != nil {
		t.Fatal(err)
	}
	row, _ := app.FindFirstRecordByFilter("audit_events", "collection = 'comments'")
	fresh, _ := app.FindRecordById("issues", id)
	if fresh.GetString("last_activity") < row.GetString("created") {
		t.Fatal("comment activity missing")
	}
	if fresh.GetString("updated") != updated {
		t.Fatal("comment changed issue.updated")
	}
	comment.Set("body", "edited progress")
	if err := app.Save(comment); err != nil {
		t.Fatal(err)
	}
	if err := app.Delete(comment); err != nil {
		t.Fatal(err)
	}
	rows, _ := app.FindRecordsByFilter("audit_events", "collection = 'comments'", "-seq", 1, 0)
	fresh, _ = app.FindRecordById("issues", id)
	if fresh.GetString("last_activity") < rows[0].GetString("created") {
		t.Fatal("comment edit/delete activity missing")
	}
}

func TestLastActivityRejectsSpoofingAndRollsBackWithAudit(t *testing.T) {
	app, id := activityDateFixture(t)
	issue, _ := app.FindRecordById("issues", id)
	issue.Set("last_activity", "2099-01-01 00:00:00.000Z")
	if err := app.Save(issue); err != nil {
		t.Fatal(err)
	}
	fresh, _ := app.FindRecordById("issues", id)
	if fresh.GetString("last_activity") != "" {
		t.Fatal("no-op accepted caller activity date")
	}
	issue.Set("title", "real change")
	if err := app.Save(issue); err != nil {
		t.Fatal(err)
	}
	fresh, _ = app.FindRecordById("issues", id)
	before := fresh.GetString("last_activity")
	if before == "" || before >= "2099" {
		t.Fatalf("bad server date: %q", before)
	}
	app.OnRecordCreateExecute("audit_events").BindFunc(func(e *core.RecordEvent) error { return errors.New("audit unavailable") })
	issue.Set("title", "must roll back")
	if err := app.Save(issue); err == nil {
		t.Fatal("save should fail")
	}
	fresh, _ = app.FindRecordById("issues", id)
	if fresh.GetString("last_activity") != before || fresh.GetString("title") != "real change" {
		t.Fatal("failed audit committed issue activity")
	}
}
