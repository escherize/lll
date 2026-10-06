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

// access is what a member may do: see every team or only the listed ones,
// and write or only read.
type access struct {
	all   bool
	teams []string
	rw    bool
}

func ownAccess(m *core.Record) access {
	return access{all: m.GetString("scope") == "all", teams: m.GetStringSlice("teams"), rw: m.GetString("mode") == "rw"}
}

func (a access) sees(teamID string) bool {
	return a.all || slices.Contains(a.teams, teamID)
}

// within is the intersection of a and b: what a may do that b may also do.
func (a access) within(b access) access {
	out := access{all: a.all && b.all, rw: a.rw && b.rw}
	switch {
	case a.all:
		out.teams = b.teams
	case b.all:
		out.teams = a.teams
	default:
		for _, team := range a.teams {
			if slices.Contains(b.teams, team) {
				out.teams = append(out.teams, team)
			}
		}
	}
	return out
}

// effectiveAccess is auth's access as the collection rules compute it
// (1791600000_bot_owner_scope.js, LLL-543): a superuser may do everything,
// and a bot with an owner holds its own access within its owner's current
// access, so narrowing the owner narrows the bot without touching the bot's
// record. An owner that cannot be read leaves nothing, the answer the rules
// give. One hop: checkBotOwner refuses a bot as an owner.
func effectiveAccess(app core.App, auth *core.Record) access {
	if auth == nil {
		return access{}
	}
	if auth.IsSuperuser() {
		return access{all: true, rw: true}
	}
	own := ownAccess(auth)
	ownerID := auth.GetString("owner")
	if ownerID == "" {
		return own
	}
	owner, err := app.FindRecordById("members", ownerID)
	if err != nil {
		return access{}
	}
	return own.within(ownAccess(owner))
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
	acc := effectiveAccess(re.App, re.Auth)
	if !acc.sees(issue.GetString("team")) {
		return re.NotFoundError("", nil)
	}
	if !acc.rw {
		return re.ForbiddenError(readOnlyRefusal(re.Auth), nil)
	}
	return nil
}

// registerMemberScopeDefault gives a member created without a scope or mode
// a default, then holds a bot within its owner (checkBotOwner). A bot with
// an owner defaults to the owner's access: the owner is the member whose
// token ran 'lll bot', so the bot starts with its creator's teams and mode
// (fleet case 09: 4 of 10 agents had to narrow an all + rw bot). Anything
// else defaults to "all" + "rw", the creator's: only a superuser or a full
// member creates other members. OnRecordCreate rather than the Request
// variant, so seeding and direct saves get it too. Only a missing value is
// filled; "teams" with no teams stays exactly that.
func registerMemberScopeDefault(app core.App) {
	app.OnRecordCreate("members").BindFunc(func(e *core.RecordEvent) error {
		def := access{all: true, rw: true}
		if e.Record.GetString("kind") == botKind && e.Record.GetString("owner") != "" {
			if owner, err := e.App.FindRecordById("members", e.Record.GetString("owner")); err == nil {
				def = ownAccess(owner)
			}
		}
		if e.Record.GetString("scope") == "" {
			if def.all {
				e.Record.Set("scope", "all")
			} else {
				e.Record.Set("scope", "teams")
				e.Record.Set("teams", def.teams)
			}
		}
		if e.Record.GetString("mode") == "" {
			if def.rw {
				e.Record.Set("mode", "rw")
			} else {
				e.Record.Set("mode", "ro")
			}
		}
		if err := checkBotOwner(e.App, e.Record); err != nil {
			return err
		}
		return e.Next()
	})
	app.OnRecordUpdate("members").BindFunc(func(e *core.RecordEvent) error {
		before := e.Record.Original()
		for _, field := range []string{"kind", "owner", "scope", "teams", "mode"} {
			if !slices.Equal(e.Record.GetStringSlice(field), before.GetStringSlice(field)) {
				if err := checkBotOwner(e.App, e.Record); err != nil {
					return err
				}
				break
			}
		}
		return e.Next()
	})
}

// checkBotOwner keeps a bot within its owner ("a bot never exceeds its
// owner", doc scoped-access-invites): the owner is not itself a bot, and its
// access covers the bot's own. Checked when a bot is created and when its
// kind, owner or access changes, for every caller, superusers included.
// Narrowing the owner is not checked: its bots narrow with it through
// effectiveAccess and the rules. An owner id that does not exist is left to
// the relation validator.
func checkBotOwner(app core.App, bot *core.Record) error {
	if bot.GetString("kind") != botKind || bot.GetString("owner") == "" {
		return nil
	}
	owner, err := app.FindRecordById("members", bot.GetString("owner"))
	if err != nil {
		return nil
	}
	if owner.GetString("kind") == botKind {
		return router.NewBadRequestError(
			"a bot cannot own a bot: "+owner.GetString("name")+" is a bot. Create "+bot.GetString("name")+
				" with its human owner's token, or with administrator credentials for a bot with no owner", nil)
	}
	if !accessCovers(owner, bot) {
		return router.NewBadRequestError(
			"a bot never exceeds its owner: "+bot.GetString("name")+" would have wider access than "+
				owner.GetString("name")+". Give the bot only teams and a mode its owner has, or widen the owner first with 'lll member access "+
				owner.GetString("name")+"'", nil)
	}
	return nil
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
	acc := effectiveAccess(app, auth)
	for _, id := range ids {
		target, err := app.FindRecordById(collection, id)
		if err != nil {
			continue
		}
		if !acc.sees(target.GetString("team")) {
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
	if auth == nil || effectiveAccess(app, auth).all {
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
	if name == "" || re.Auth == nil || effectiveAccess(re.App, re.Auth).rw {
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
