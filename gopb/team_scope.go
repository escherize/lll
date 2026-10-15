package gopb

import (
	"net/http"
	"slices"
	"strings"

	"github.com/pocketbase/dbx"
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
// (1791700000_bot_owner_scope.js, LLL-543): a superuser may do everything,
// and a bot with an owner holds its own access within its owner's current
// access, so narrowing the owner narrows the bot without touching the bot's
// record. An owner that cannot be read leaves nothing, the answer the rules
// give. One hop: checkOwner refuses ownership chains.
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
// and 403 for a read-only member or an archived team (team_writes.go). An issue that does not exist is left to the
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
	return archivedRefusal(re.App, re.Auth, issue.GetString("team"))
}

// registerMemberScopeDefault gives a member created without a scope or mode
// a default, then holds a bot within its owner (checkOwner). A bot with
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
		// A bot another bot created (LLL-709) starts with its creator's
		// access, which may be narrower than the owner they share.
		if creator, err := e.App.FindRecordById("members", e.Record.GetString("created_by")); err == nil {
			def = effectiveAccess(e.App, creator)
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
		if err := checkOwner(e.App, e.Record); err != nil {
			return err
		}
		return e.Next()
	})
	app.OnRecordUpdate("members").BindFunc(func(e *core.RecordEvent) error {
		before := e.Record.Original()
		// Losing the owner must not widen a bot back to its own fields
		// (fail closed, LLL-543 security review). A superuser clearing it
		// leaves the bot what it could do at that moment: its access within
		// the old owner's, persisted. Deleting the owner lands here too:
		// PocketBase clears the relation with a save after the owner row is
		// gone, so the lookup fails and the bot keeps nothing (no teams,
		// read-only) until an administrator grants it access again.
		// Keyed on the old owner alone: a PATCH that also changes kind must
		// not skip it.
		if before.GetString("owner") != "" && e.Record.GetString("owner") == "" {
			kept := access{}
			if old, err := e.App.FindRecordById("members", before.GetString("owner")); err == nil {
				kept = ownAccess(e.Record).within(ownAccess(old))
			}
			setAccess(e.Record, kept)
		}
		detachStaleCreator(e.App, e.Record)
		for _, field := range []string{"kind", "owner", "created_by", "scope", "teams", "mode"} {
			if !slices.Equal(e.Record.GetStringSlice(field), before.GetStringSlice(field)) {
				if err := checkOwner(e.App, e.Record); err != nil {
					return err
				}
				break
			}
		}
		if err := e.Next(); err != nil {
			return err
		}
		return narrowCreated(e.App, e.Record)
	})
}

// narrowCreated keeps every bot m created (created_by, LLL-709) within m's
// access after m changes. Those bots share m's owner, so the rules narrow
// them with the owner already; this covers narrowing m itself, which the
// rules cannot see. m's process holds the tokens of the bots it created, so
// they must not keep access m lost. Each save narrows what that bot created
// in turn.
func narrowCreated(app core.App, m *core.Record) error {
	if m.Collection().Fields.GetByName("created_by") == nil {
		return nil // a test fixture's members collection without the field
	}
	created, err := app.FindRecordsByFilter("members", "created_by = {:id}", "", 0, 0, dbx.Params{"id": m.Id})
	if err != nil {
		return err
	}
	// m's effective access, not its own: the bot shares m's owner, and an
	// owner narrowed earlier must not leave the narrowed bot wider than the
	// owner, which checkOwner would refuse.
	limit := effectiveAccess(app, m)
	for _, bot := range created {
		own := ownAccess(bot)
		kept := own.within(limit)
		// And within the bot's own owner, which m may no longer share: a
		// narrowing save must never be one checkOwner refuses.
		if owner, err := app.FindRecordById("members", bot.GetString("owner")); err == nil {
			kept = kept.within(ownAccess(owner))
		} else if bot.GetString("owner") != "" {
			// The owner is being deleted: PocketBase clears this bot's
			// owner with its own save, which leaves it nothing (above)
			// and detaches it. A save now would fail on the dead relation.
			continue
		}
		shared := m.GetString("owner") != "" && m.GetString("owner") == bot.GetString("owner")
		if kept.covers(own) && shared {
			continue
		}
		// The save detaches the bot when the owners no longer match
		// (detachStaleCreator).
		setAccess(bot, kept)
		if err := app.Save(bot); err != nil {
			return err
		}
	}
	return nil
}

// detachStaleCreator clears created_by on an update when the creator no
// longer shares the bot's human owner: the creator lost its owner or was
// re-owned, or the bot was. The bot is then an ordinary bot of its owner:
// the creator stops rotating it and stops bounding it, every token minted
// for it so far stops working, and checkCreator
// cannot refuse a save that narrows or revokes. A created_by the update
// itself sets is left for checkCreator to judge.
func detachStaleCreator(app core.App, m *core.Record) {
	id := m.GetString("created_by")
	if id == "" || id != m.Original().GetString("created_by") {
		return
	}
	creator, err := app.FindRecordById("members", id)
	if err != nil {
		return
	}
	if creator.GetString("owner") == "" || creator.GetString("owner") != m.GetString("owner") {
		m.Set("created_by", "")
		// The creator holds every token it minted for this bot. Detaching
		// strands them, so a revoked creator cannot keep acting as it; the
		// bot's owner re-mints with 'lll bot rotate'.
		m.RefreshTokenKey()
	}
}

// setAccess writes a to m's scope, teams and mode.
func setAccess(m *core.Record, a access) {
	m.Set("teams", []string{})
	if a.all {
		m.Set("scope", "all")
	} else {
		m.Set("scope", "teams")
		m.Set("teams", a.teams)
	}
	if a.rw {
		m.Set("mode", "rw")
	} else {
		m.Set("mode", "ro")
	}
}

// checkOwner keeps ownership one hop deep and keeps an owned member within
// its owner ("a bot never exceeds its owner", doc scoped-access-invites).
// effectiveAccess and the rules read only the direct owner, so a chain would
// let a narrowed owner's grandchild keep its access. Refused, for every
// caller, superusers included:
//
//   - an owner that is a bot or has an owner itself;
//   - an owner on a member that owns members;
//   - a bot that owns members;
//   - an owned member wider than its owner;
//   - a bot another bot created (created_by) that breaks checkCreator.
//
// A bot with a human owner still creates bots: they are owned by that
// person, not by the bot (LLL-709). Checked when a member is created and
// when its kind, owner, created_by or access changes. Narrowing an owner is not checked: what it owns narrows with it.
// An owner id that does not exist is left to the relation validator.
func checkOwner(app core.App, m *core.Record) error {
	name := m.GetString("name")
	if err := checkCreator(app, m); err != nil {
		return err
	}
	// A member being created owns nothing yet (and its id may be empty,
	// which would match every unowned member).
	var owns *core.Record
	if !m.IsNew() {
		owns, _ = app.FindFirstRecordByFilter("members", "owner = {:id}", dbx.Params{"id": m.Id})
	}
	if owns != nil && m.GetString("kind") == botKind {
		return router.NewBadRequestError("a bot cannot own members: "+name+" owns "+owns.GetString("name")+
			". Give "+owns.GetString("name")+" a human owner first", nil)
	}
	if m.GetString("owner") == "" {
		return nil
	}
	if owns != nil {
		return router.NewBadRequestError("an owner is one hop: "+name+" owns "+owns.GetString("name")+
			", so it cannot have an owner itself. Re-own or remove what it owns first", nil)
	}
	owner, err := app.FindRecordById("members", m.GetString("owner"))
	if err != nil {
		return nil
	}
	if owner.GetString("kind") == botKind && owner.GetString("owner") != "" {
		human := owner.GetString("owner")
		if h, err := app.FindRecordById("members", human); err == nil {
			human = h.GetString("name")
		}
		return router.NewBadRequestError(
			"a bot cannot own a bot: "+owner.GetString("name")+" is a bot, and a bot creates bots for its own owner, "+
				human+". Give "+name+" the owner "+human+" ('lll bot create' does this)", nil)
	}
	if owner.GetString("kind") == botKind {
		return router.NewBadRequestError(
			"a bot cannot own a bot: "+owner.GetString("name")+" is a bot. Create "+name+
				" with its human owner's token, or with administrator credentials for a bot with no owner", nil)
	}
	if owner.GetString("owner") != "" {
		return router.NewBadRequestError("an owner is one hop: "+owner.GetString("name")+
			" has an owner itself, so it cannot own "+name+". Give "+name+" that member's owner instead", nil)
	}
	if !accessCovers(owner, m) {
		// A stable code (LLL-675): `lll member access` relays this refusal
		// as it is, and decides so on the code, not on the wording.
		return withCode(router.NewBadRequestError(
			"a bot never exceeds its owner: "+name+" would have wider access than "+
				owner.GetString("name")+". Give it only teams and a mode its owner has, or widen the owner first with 'lll member access "+
				owner.GetString("name")+"'", nil), "bot_exceeds_owner")
	}
	return nil
}

// checkCreator holds a bot another bot created (created_by, LLL-709) to what
// made creating it safe: it is a bot, owned by its creator's owner (so
// ownership stays one hop), and no wider than its creator's effective access.
// Checked for every caller, like the rest of checkOwner. A creator id that
// does not exist is left to the relation validator.
func checkCreator(app core.App, m *core.Record) error {
	if m.GetString("created_by") == "" {
		return nil
	}
	creator, err := app.FindRecordById("members", m.GetString("created_by"))
	if err != nil {
		return nil
	}
	name, by := m.GetString("name"), creator.GetString("name")
	if m.GetString("kind") != botKind || creator.GetString("kind") != botKind {
		return router.NewBadRequestError("only a bot records the bot that created it: created_by names a bot, and "+
			name+" or "+by+" is not one", nil)
	}
	if creator.GetString("owner") == "" {
		return router.NewBadRequestError("a bot that "+by+" creates is owned by the creating bot's owner, and "+
			by+" has none. A bot with no owner cannot create bots; ask an administrator", nil)
	}
	if m.GetString("owner") != creator.GetString("owner") {
		human := creator.GetString("owner")
		if h, err := app.FindRecordById("members", human); err == nil {
			human = h.GetString("name")
		}
		return router.NewBadRequestError("a bot that "+by+" creates is owned by the creating bot's owner, "+
			human+". Give "+name+" the owner "+human+" ('lll bot create' does this)", nil)
	}
	if !effectiveAccess(app, creator).covers(ownAccess(m)) {
		return withCode(router.NewBadRequestError(
			"a bot never exceeds the bot that created it: "+name+" would have wider access than "+by+
				". Give it only teams and a mode "+by+" has", nil), "bot_exceeds_owner")
	}
	return nil
}

// accessCovers reports whether member a holds at least b's access: every team
// b sees, and write if b writes.
func accessCovers(a, b *core.Record) bool {
	return ownAccess(a).covers(ownAccess(b))
}

// covers reports whether a holds at least b: every team b sees, and write if
// b writes.
func (a access) covers(b access) bool {
	if b.rw && !a.rw {
		return false
	}
	if a.all {
		return true
	}
	if b.all {
		return false
	}
	for _, team := range b.teams {
		if !slices.Contains(a.teams, team) {
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

// checkNewRefs runs refsInScope over the relation ids a write adds, so a
// narrow caller is told about a hidden id exactly as about a missing one.
// For every caller (an all-scope member sees every team, so it passes here)
// the team rule itself is registerTeamRefGuard's, which runs on the save.
// Only added ids are checked: a link made before LLL-631 must not block an
// unrelated edit.
func checkNewRefs(app core.App, auth *core.Record, record *core.Record) error {
	if auth == nil {
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

// registerAccessRoute answers GET /api/lll/access with the calling member's
// effective access (LLL-545): the board resolves a member-token cookie
// through it on every request. PocketBase's auth middleware has already
// checked the token (signature, expiry, tokenKey, record still exists), and
// the grants come from effectiveAccess, so a bot's token gets its owner's
// intersection, read fresh rather than cached in the cookie. Members only:
// a superuser token names no member and is not a board credential.
func registerAccessRoute(routes *router.Router[*core.RequestEvent]) {
	routes.GET("/api/lll/access", func(re *core.RequestEvent) error {
		if re.Auth == nil || re.Auth.Collection().Name != "members" {
			return re.UnauthorizedError("a member token is required", nil)
		}
		acc := effectiveAccess(re.App, re.Auth)
		all, err := re.App.FindAllRecords("teams")
		if err != nil {
			return re.InternalServerError("failed to read teams", err)
		}
		type team struct {
			ID  string `json:"id"`
			Key string `json:"key"`
		}
		teams := []team{}
		for _, t := range all {
			if acc.sees(t.Id) {
				teams = append(teams, team{ID: t.Id, Key: t.GetString("key")})
			}
		}
		return re.JSON(http.StatusOK, map[string]any{
			"id":    re.Auth.Id,
			"name":  re.Auth.GetString("name"),
			"rw":    acc.rw,
			"all":   acc.all,
			"teams": teams,
		})
	})
}
