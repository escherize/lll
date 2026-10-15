package gopb

import (
	"encoding/json"
	"errors"
	"net/http"
	"strings"

	"github.com/pocketbase/pocketbase/core"
)

// The audit log (LLL-609). Every create, update and delete of an issue,
// comment or claim appends one audit_events row in the same transaction as
// the write, so a write without its row cannot commit
// (pb_migrations/1792900000_audit_events.js has the schema and why).
//
// The row hooks are model hooks, so they see every write path: the records
// API, the /api/lll routes, the claim-expiry sweep and cascades. A model
// hook cannot see the request, so whoever asks for a write stamps the record
// with a releaser first (stampActor): the records-API request hooks below,
// and the claim routes in claims.go. An unstamped write is the server's own
// (the sweep, a cascade) and is recorded as actor kind "system".
var auditedCollections = []string{"issues", "comments", "claims"}

// auditActorKey holds the stamp in the record's custom data. It is not a
// field, so it is never persisted and never exported.
const auditActorKey = "@lll_audit_actor"

// Self-asserted request context the CLI sends on every request. The agent
// label is the shape claims enforce; origin is truncated, never refused, so
// an odd host name cannot fail a write.
const (
	agentHeader  = "X-LLL-Agent"
	originHeader = "X-LLL-Origin-Host"
)

func stampActor(r *core.Record, by releaser) {
	if r != nil {
		r.Set(auditActorKey, by)
	}
}

func originHost(r *http.Request) string {
	host := strings.TrimSpace(r.Header.Get(originHeader))
	if len(host) > 255 {
		host = host[:255]
	}
	return host
}

// routeActor is who an /api/lll route's write is for; a superuser names no
// member. The agent label comes from the header, as the route has no other.
func routeActor(re *core.RequestEvent) releaser {
	by := releaser{origin: originHost(re.Request)}
	if !re.HasSuperuserAuth() && re.Auth != nil {
		by.memberID = re.Auth.Id
	}
	if agent := re.Request.Header.Get(agentHeader); agentLabelShape.MatchString(agent) {
		by.agent = agent
	}
	return by
}

// requestActor is who a records-API write is for. The agent label is the
// record's own (a comment carries one), else ?agent= (registerFinishRelease
// reads it), else the header; a label of the wrong shape is dropped.
func requestActor(e *core.RecordRequestEvent) releaser {
	by := releaser{origin: originHost(e.Request)}
	if e.Auth != nil && e.Auth.Collection().Name == "members" {
		by.memberID = e.Auth.Id
	}
	for _, agent := range []string{e.Record.GetString("agent"), e.Request.URL.Query().Get("agent"), e.Request.Header.Get(agentHeader)} {
		if agent != "" {
			if agentLabelShape.MatchString(agent) {
				by.agent = agent
			}
			break
		}
	}
	return by
}

func registerAuditLog(app core.App) {
	stamp := func(e *core.RecordRequestEvent) error {
		stampActor(e.Record, requestActor(e))
		return e.Next()
	}
	for _, name := range auditedCollections {
		app.OnRecordCreateRequest(name).BindFunc(stamp)
		app.OnRecordUpdateRequest(name).BindFunc(stamp)
		app.OnRecordDeleteRequest(name).BindFunc(stamp)
		app.OnRecordCreateExecute(name).BindFunc(func(e *core.RecordEvent) error { return appendAudit(e, "create") })
		app.OnRecordUpdateExecute(name).BindFunc(func(e *core.RecordEvent) error { return appendAudit(e, "update") })
		app.OnRecordDeleteExecute(name).BindFunc(func(e *core.RecordEvent) error { return appendAudit(e, "delete") })
	}
	// Append-only. The null rules already refuse members; these refuse a
	// superuser too, so history is never forged or rewritten through the
	// API. gopb's own rows are model saves, which no request hook sees.
	app.OnRecordCreateRequest("audit_events").BindFunc(func(e *core.RecordRequestEvent) error {
		return e.ForbiddenError("audit events are written by the server", nil)
	})
	app.OnRecordUpdate("audit_events").BindFunc(func(e *core.RecordEvent) error {
		return errors.New("audit events are append-only")
	})
}

// appendAudit runs the write and its audit row in one transaction. The
// changes are read before the write, while Original() is the stored row.
func appendAudit(e *core.RecordEvent, action string) error {
	changes := recordChanges(e.Record, action)
	// A save that changed nothing is not an event, except a claim's: a
	// renewal moves only its autodate, and is the event.
	if action == "update" && len(changes) == 0 && e.Record.Collection().Name != "claims" {
		return e.Next()
	}
	original := e.App
	defer func() { e.App = original }()
	return original.RunInTransaction(func(tx core.App) error {
		e.App = tx
		if err := e.Next(); err != nil {
			return err
		}
		return writeAuditEvent(tx, e.Record, action, changes)
	})
}

type fieldChange struct {
	From any `json:"from"`
	To   any `json:"to"`
}

// recordChanges is every visible field the write changes: for a create the
// fields it sets, for a delete the fields the record had. Autodates and
// hidden fields (idempotency keys) are left out.
func recordChanges(r *core.Record, action string) map[string]fieldChange {
	out := map[string]fieldChange{}
	for _, field := range r.Collection().Fields {
		name := field.GetName()
		if name == core.FieldNameId || field.GetHidden() || field.Type() == core.FieldTypeAutodate {
			continue
		}
		var from, to any
		if action != "create" {
			from = r.Original().Get(name)
		}
		if action != "delete" {
			to = r.Get(name)
		}
		before, after := canonical(from), canonical(to)
		if before == after {
			continue
		}
		out[name] = fieldChange{From: from, To: to}
	}
	return out
}

// canonical compares values by their JSON, with every empty value alike:
// a field a create leaves at "" did not change from nothing.
func canonical(v any) string {
	raw, err := json.Marshal(v)
	if err != nil {
		return ""
	}
	switch s := string(raw); s {
	case "null", `""`, "0", "false", "[]", "{}":
		return ""
	default:
		return s
	}
}

func writeAuditEvent(tx core.App, r *core.Record, action string, changes map[string]fieldChange) error {
	events, err := tx.FindCachedCollectionByNameOrId("audit_events")
	if err != nil {
		return err
	}
	collection := r.Collection().Name
	row := core.NewRecord(events)
	row.Set("collection", collection)
	row.Set("record", r.Id)
	row.Set("action", action)
	row.Set("changes", changes)

	// The issue the write belongs to, and its team and project as they are
	// now. A comment or claim deleted with its issue may outlive the lookup.
	issueID := r.GetString("issue")
	if collection == "issues" {
		issueID = r.Id
	}
	row.Set("issue", issueID)
	issue := r
	if collection != "issues" {
		issue, _ = tx.FindRecordById("issues", issueID)
	}
	if issue != nil {
		row.Set("team", issue.GetString("team"))
		row.Set("number", issue.GetInt("number"))
		row.Set("project", issue.GetString("project"))
	}

	by, stamped := r.Get(auditActorKey).(releaser)
	switch {
	case !stamped:
		row.Set("actor_kind", "system")
	case by.memberID == "":
		row.Set("actor_kind", "superuser")
	default:
		row.Set("actor", by.memberID)
		row.Set("actor_kind", "person")
		if member, err := tx.FindRecordById("members", by.memberID); err == nil && member.GetString("kind") == "bot" {
			row.Set("actor_kind", "bot")
		}
	}
	if stamped {
		row.Set("agent", by.agent)
		row.Set("origin_host", by.origin)
	}

	var next int
	if err := tx.DB().NewQuery("SELECT COALESCE(MAX(seq), 0) + 1 FROM audit_events").Row(&next); err != nil {
		return err
	}
	row.Set("seq", next)
	return tx.Save(row)
}
