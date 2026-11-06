package gopb

import (
	"errors"
	"testing"

	"github.com/pocketbase/pocketbase/core"
)

func activityDateFixture(t *testing.T) (core.App, string) {
	t.Helper()
	app, id, _, _ := auditFixture(t)
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
