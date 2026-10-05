package gopb

import (
	"net/http"
	"slices"
	"strings"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

// Team-scoped members (members.scope/teams/mode, 1789900000_member_teams.js):
// the collection rules keep a scoped member inside its teams, but the custom
// /api/lll routes read records through the app and skip those rules. Each
// one that takes an issue calls issueWritable first; all of them write.

// memberSeesTeam reports whether auth may see rows of teamID. Superusers and
// scope "all" see every team; scope "teams" sees only the listed ones, so an
// empty list sees nothing.
func memberSeesTeam(auth *core.Record, teamID string) bool {
	if auth == nil {
		return false
	}
	if auth.IsSuperuser() || auth.GetString("scope") == "all" {
		return true
	}
	return slices.Contains(auth.GetStringSlice("teams"), teamID)
}

// issueWritable answers 404 for an issue outside the caller's teams, the same
// answer a rule gives, so the route does not reveal that the issue exists,
// and 403 for a read-only member. An issue that does not exist is left to the
// route's own handling.
func issueWritable(re *core.RequestEvent, issueID string) error {
	issue, err := re.App.FindRecordById("issues", issueID)
	if err != nil {
		return nil
	}
	if !memberSeesTeam(re.Auth, issue.GetString("team")) {
		return re.NotFoundError("", nil)
	}
	if !re.Auth.IsSuperuser() && re.Auth.GetString("mode") != "rw" {
		return re.ForbiddenError(readOnlyRefusal(re.Auth), nil)
	}
	return nil
}

// registerMemberScopeDefault gives a member created without a scope or mode
// its creator's: only a superuser or an "all" + "rw" member passes
// members.createRule, so the default is "all" + "rw". OnRecordCreate rather
// than the Request variant, so seeding and direct saves get it too. Only a
// missing value is filled; "teams" with no teams stays exactly that.
func registerMemberScopeDefault(app core.App) {
	app.OnRecordCreate("members").BindFunc(func(e *core.RecordEvent) error {
		if e.Record.GetString("scope") == "" {
			e.Record.Set("scope", "all")
		}
		if e.Record.GetString("mode") == "" {
			e.Record.Set("mode", "rw")
		}
		return e.Next()
	})
}

// accessCovers reports whether member a holds at least b's access: every team
// b sees, and write if b writes.
func accessCovers(a, b *core.Record) bool {
	if b.GetString("mode") == "rw" && a.GetString("mode") != "rw" {
		return false
	}
	if a.GetString("scope") == "all" {
		return true
	}
	if b.GetString("scope") == "all" {
		return false
	}
	for _, team := range b.GetStringSlice("teams") {
		if !slices.Contains(a.GetStringSlice("teams"), team) {
			return false
		}
	}
	return true
}

// Relations a scoped member could point across teams, by collection: field ->
// the collection it relates to. Every target carries its own team.
var scopedRefs = map[string]map[string]string{
	"issues":   {"project": "projects", "labels": "labels", "blocked_by": "issues"},
	"docs":     {"issues": "issues"},
	"webhooks": {"project": "projects"},
}

// refsInScope refuses ids in collection that belong to a team auth cannot
// see. Unknown ids pass, so the relation validator reports them exactly as it
// reports a hidden one. Without this a scoped member who learned a BETA id
// could hang BETA's project, label or issue on an ALPHA row, and every page
// that renders the row as the board's all-scope member would show BETA's name.
func refsInScope(app core.App, auth *core.Record, collection string, ids []string) error {
	for _, id := range ids {
		target, err := app.FindRecordById(collection, id)
		if err != nil {
			continue
		}
		if !memberSeesTeam(auth, target.GetString("team")) {
			return router.NewBadRequestError("Failed to find all relation records with the provided ids.", nil)
		}
	}
	return nil
}

// added returns the ids in now that were not in before.
func added(now, before []string) []string {
	var out []string
	for _, id := range now {
		if !slices.Contains(before, id) {
			out = append(out, id)
		}
	}
	return out
}

// checkNewRefs runs refsInScope over the relation ids a write adds. Only
// added ids are checked: a link an all-scope member made earlier must not
// block a scoped member's unrelated edit.
func checkNewRefs(app core.App, auth *core.Record, record *core.Record) error {
	if auth == nil || auth.IsSuperuser() || auth.GetString("scope") == "all" {
		return nil
	}
	original := record.Original()
	for field, target := range scopedRefs[record.Collection().Name] {
		ids := added(record.GetStringSlice(field), original.GetStringSlice(field))
		if err := refsInScope(app, auth, target, ids); err != nil {
			return err
		}
	}
	return nil
}

// registerScopedRefGuard binds checkNewRefs to API creates and updates of the
// collections in scopedRefs. The Request variants carry the caller; the
// custom assignment route, which saves through the app, checks its own
// fields (claims_http.go).
func registerScopedRefGuard(app core.App) {
	for collection := range scopedRefs {
		app.OnRecordCreateRequest(collection).BindFunc(func(e *core.RecordRequestEvent) error {
			if err := checkNewRefs(e.App, e.Auth, e.Record); err != nil {
				return err
			}
			return e.Next()
		})
		app.OnRecordUpdateRequest(collection).BindFunc(func(e *core.RecordRequestEvent) error {
			if err := checkNewRefs(e.App, e.Auth, e.Record); err != nil {
				return err
			}
			return e.Next()
		})
	}
}

// readOnlyRefusal is the one wording for a read-only member's write, shared
// by the collection hooks below and the custom /api/lll routes.
func readOnlyRefusal(auth *core.Record) string {
	return "read-only access: " + auth.GetString("name") +
		" can read but not change records here. 'lll whoami' shows your access; ask the person who invited you for read-write"
}

// Collections a read-only member may still write: its own favorites and
// saved views, and its own member record (name, password).
var readOnlyWritable = map[string]bool{"favorites": true, "views": true}

// refuseReadOnlyWrites answers a read-only member's write through the
// records API with a 403 that says why, instead of the rule's bare "Failed
// to create record." (400) or 404 (fleet case 02: 10 of 10 agents could not
// tell why they were refused). The rules still enforce it; this names the
// reason. Router middleware, because PocketBase checks a create rule before
// any request hook runs. It answers before any record lookup, so the reply is
// the same whether or not the id exists and reveals nothing.
func refuseReadOnlyWrites(re *core.RequestEvent) error {
	method := re.Request.Method
	if method != http.MethodPost && method != http.MethodPatch && method != http.MethodDelete {
		return re.Next()
	}
	name := re.Request.PathValue("collection")
	if name == "" || re.Auth == nil || re.Auth.IsSuperuser() || re.Auth.GetString("mode") != "ro" {
		return re.Next()
	}
	if c, err := re.App.FindCachedCollectionByNameOrId(name); err == nil {
		name = c.Name
	}
	if readOnlyWritable[name] || (name == "members" && method == http.MethodPatch && re.Request.PathValue("id") == re.Auth.Id) {
		return re.Next()
	}
	if !strings.HasPrefix(re.Request.URL.Path, "/api/collections/") {
		return re.Next()
	}
	return re.ForbiddenError(readOnlyRefusal(re.Auth), nil)
}
