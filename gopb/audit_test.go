package gopb

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/core"
)

// auditFixture is claimFixture with the audit log bound, as Serve binds it,
// and audit_events shaped as 1792900000_audit_events.js makes it.
func auditFixture(t *testing.T) (core.App, string, string, string) {
	t.Helper()
	app, issueID, alpha, beta := claimFixture(t)
	events := core.NewBaseCollection("audit_events")
	events.Fields.Add(
		&core.NumberField{Name: "seq", Required: true, OnlyInt: true},
		&core.TextField{Name: "collection"}, &core.TextField{Name: "record"}, &core.TextField{Name: "action"},
		&core.TextField{Name: "team"}, &core.TextField{Name: "issue"}, &core.NumberField{Name: "number"}, &core.TextField{Name: "project"},
		&core.TextField{Name: "actor"}, &core.TextField{Name: "actor_kind"},
		&core.TextField{Name: "agent"}, &core.TextField{Name: "origin_host"},
		&core.JSONField{Name: "changes", MaxSize: 4 << 20},
	)
	events.Indexes = []string{"CREATE UNIQUE INDEX idx_audit_test_seq ON audit_events (seq)"}
	if err := app.Save(events); err != nil {
		t.Fatal(err)
	}
	registerAuditLog(app)
	return app, issueID, alpha, beta
}

type auditRow struct {
	seq                                    int
	collection, action, actor, kind, agent string
	origin                                 string
	changes                                map[string]fieldChange
}

func auditRows(t *testing.T, app core.App) []auditRow {
	t.Helper()
	records, err := app.FindRecordsByFilter("audit_events", "", "seq", 0, 0)
	if err != nil {
		t.Fatal(err)
	}
	var rows []auditRow
	for _, r := range records {
		row := auditRow{seq: r.GetInt("seq"), collection: r.GetString("collection"), action: r.GetString("action"),
			actor: r.GetString("actor"), kind: r.GetString("actor_kind"), agent: r.GetString("agent"), origin: r.GetString("origin_host")}
		if err := json.Unmarshal([]byte(r.GetString("changes")), &row.changes); err != nil {
			t.Fatal(err)
		}
		rows = append(rows, row)
	}
	return rows
}

// LLL-609: every claim write leaves one row, in order, naming who asked.
func TestAuditRecordsClaimLifecycleWithActor(t *testing.T) {
	app, issueID, alpha, beta := auditFixture(t)
	by := releaser{memberID: alpha, agent: "wt-a", origin: "host-a"}
	held, err := acquireClaim(app, issueID, by)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := renewClaim(app, issueID, held.ClaimID, by); err != nil {
		t.Fatal(err)
	}
	if _, err := releaseClaim(app, issueID, held.ClaimID, releaser{memberID: beta, force: true, reason: "dead", origin: "host-b"}); err != nil {
		t.Fatal(err)
	}
	rows := auditRows(t, app)
	want := []struct{ collection, action, actor, agent, origin string }{
		{"claims", "create", alpha, "wt-a", "host-a"},
		{"issues", "update", alpha, "wt-a", "host-a"}, // assignee set
		{"claims", "update", alpha, "wt-a", "host-a"}, // renewal
		{"claims", "delete", beta, "", "host-b"},
		{"issues", "update", beta, "", "host-b"},   // assignee cleared
		{"comments", "create", beta, "", "host-b"}, // the forced-release note
	}
	if len(rows) != len(want) {
		t.Fatalf("rows: %+v", rows)
	}
	for i, w := range want {
		r := rows[i]
		if r.seq != i+1 || r.collection != w.collection || r.action != w.action || r.actor != w.actor ||
			r.kind != "person" || r.agent != w.agent || r.origin != w.origin {
			t.Fatalf("row %d: %+v, want %+v", i, r, w)
		}
	}
	if c := rows[1].changes["assignee"]; c.From != "" || c.To != alpha {
		t.Fatalf("assignee change: %+v", rows[1].changes)
	}
	if c := rows[3].changes["member"]; c.From != alpha || c.To != nil {
		t.Fatalf("deleted claim keeps its holder: %+v", rows[3].changes)
	}
}

// The sweep is the server's own write: unstamped, so actor kind system.
func TestAuditRecordsExpiryAsSystem(t *testing.T) {
	app, issueID, alpha, _ := auditFixture(t)
	if _, err := acquireClaim(app, issueID, releaser{memberID: alpha}); err != nil {
		t.Fatal(err)
	}
	if n, err := expireClaims(app, time.Now().Add(48*time.Hour), claimMaxAge); err != nil || n != 1 {
		t.Fatalf("expired %d: %v", n, err)
	}
	rows := auditRows(t, app)
	if len(rows) < 3 {
		t.Fatalf("rows: %+v", rows)
	}
	for _, r := range rows[2:] {
		if r.kind != "system" || r.actor != "" {
			t.Fatalf("sweep row not system: %+v", rows)
		}
	}
	if rows[2].collection != "issues" && rows[2].collection != "claims" {
		t.Fatalf("rows: %+v", rows)
	}
}

// A save that changes nothing is not an event; a failed write leaves no row.
func TestAuditSkipsNoOpsAndFailedWrites(t *testing.T) {
	app, issueID, _, _ := auditFixture(t)
	issue, err := app.FindRecordById("issues", issueID)
	if err != nil {
		t.Fatal(err)
	}
	if err := app.Save(issue); err != nil {
		t.Fatal(err)
	}
	if rows := auditRows(t, app); len(rows) != 0 {
		t.Fatalf("no-op save logged: %+v", rows)
	}
	comments, _ := app.FindCollectionByNameOrId("comments")
	bad := core.NewRecord(comments)
	bad.Set("issue", issueID) // no body: fails validation
	if err := app.Save(bad); err == nil {
		t.Fatal("comment without a body saved")
	}
	if rows := auditRows(t, app); len(rows) != 0 {
		t.Fatalf("failed write logged: %+v", rows)
	}
}

// Append-only: not even a model save may rewrite a row.
func TestAuditRowsAreAppendOnly(t *testing.T) {
	app, issueID, alpha, _ := auditFixture(t)
	if _, err := acquireClaim(app, issueID, releaser{memberID: alpha}); err != nil {
		t.Fatal(err)
	}
	row, err := app.FindFirstRecordByFilter("audit_events", "seq = 1")
	if err != nil {
		t.Fatal(err)
	}
	row.Set("actor", "forged")
	if err := app.Save(row); err == nil {
		t.Fatal("audit row updated")
	}
}
