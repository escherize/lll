package gopb

import (
	"encoding/json"
	"net/http"
	"net/url"
	"regexp"
	"slices"
	"strings"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/search"
)

// The members roster (LLL-551, decision option b). A member whose effective
// access is every team sees every member and every email, as before. Anyone
// narrower sees exactly:
//
//  1. itself;
//  2. every member that shares a team with it: a team in that member's own
//     `teams` that the caller effectively sees;
//  3. every person (not a bot) whose scope is "all".
//
// and no email but its own. The collection rule enforces the set
// (1791900000_member_roster_scope.js); this file holds what a rule cannot
// express:
//
//   - emails: every member is stored with emailVisibility false, and the
//     enrich hook shows them again to a full-access caller;
//   - a visible member's other teams: the enrich hook drops team ids the
//     caller cannot see, so a roster entry never names a hidden team;
//   - relation filters: PocketBase checks no rule on the far side of a
//     relation in filter= or sort=, so "assignee.name ~ 'x%'" would read a
//     hidden member's name through an issue the caller can see. A narrower
//     caller may not filter or sort through a relation into or out of
//     members;
//   - names in custom-route messages (rosterName).

// rosterSees reports whether viewer may see member m under the rule above.
// A nil viewer is a superuser or the process, which sees everyone.
func rosterSees(app core.App, viewer, m *core.Record) bool {
	if viewer == nil || viewer.IsSuperuser() || viewer.Id == m.Id {
		return true
	}
	acc := effectiveAccess(app, viewer)
	if acc.all {
		return true
	}
	if m.GetString("scope") == "all" && m.GetString("kind") != botKind {
		return true
	}
	return slices.ContainsFunc(m.GetStringSlice("teams"), acc.sees)
}

// hiddenMember is how a message names a member the caller may not see. The
// CLI and the board use the same words (display.hidden_member).
const hiddenMember = "a hidden member"

// rosterName is memberID's name as viewerID may see it: the name, "a hidden
// member" when the roster hides it, or fallback when it does not exist. An
// empty viewerID is a superuser.
func rosterName(app core.App, viewerID, memberID, fallback string) string {
	m, err := app.FindRecordById("members", memberID)
	if err != nil {
		return fallback
	}
	if viewerID != "" {
		viewer, err := app.FindRecordById("members", viewerID)
		if err != nil || !rosterSees(app, viewer, m) {
			return hiddenMember
		}
	}
	return m.GetString("name")
}

// registerRosterScope binds the member enrich hook, keeps every stored
// emailVisibility false, and refuses relation probes in realtime
// subscriptions. The list and view endpoints get refuseRosterProbes as
// router middleware.
func registerRosterScope(app core.App) {
	hideEmail := func(e *core.RecordEvent) error {
		e.Record.SetEmailVisibility(false)
		return e.Next()
	}
	app.OnRecordCreate("members").BindFunc(hideEmail)
	app.OnRecordUpdate("members").BindFunc(hideEmail)

	app.OnRecordEnrich("members").BindFunc(func(e *core.RecordEnrichEvent) error {
		viewer := e.RequestInfo.Auth
		if viewer == nil || viewer.IsSuperuser() || viewer.Id == e.Record.Id || viewer.Collection().Name != "members" {
			return e.Next()
		}
		acc := effectiveAccess(e.App, viewer)
		if acc.all {
			// Today's view for full access: every email.
			e.Record.IgnoreEmailVisibility(true)
			return e.Next()
		}
		teams := e.Record.GetStringSlice("teams")
		e.Record.Set("teams", slices.DeleteFunc(slices.Clone(teams), func(id string) bool { return !acc.sees(id) }))
		return e.Next()
	})

	app.OnRealtimeSubscribeRequest().BindFunc(func(e *core.RealtimeSubscribeRequestEvent) error {
		if !narrowCaller(e.App, e.Auth) {
			return e.Next()
		}
		for _, topic := range e.Subscriptions {
			base, rawOptions, _ := strings.Cut(topic, "?options=")
			name, _, _ := strings.Cut(base, "/")
			collection, err := e.App.FindCachedCollectionByNameOrId(name)
			if err != nil || rawOptions == "" {
				continue
			}
			decoded, err := url.QueryUnescape(rawOptions)
			if err != nil {
				return e.BadRequestError("invalid subscription options", nil)
			}
			var options struct {
				Query map[string]string `json:"query"`
			}
			if err := json.Unmarshal([]byte(decoded), &options); err != nil {
				return e.BadRequestError("invalid subscription options", nil)
			}
			if crossesRoster(e.App, collection, options.Query[search.FilterQueryParam], options.Query[search.SortQueryParam]) {
				return e.ForbiddenError(rosterProbeRefusal, nil)
			}
		}
		return e.Next()
	})
}

// narrowCaller is true for a member whose effective access is narrower than
// every team: the callers the roster rule limits.
func narrowCaller(app core.App, auth *core.Record) bool {
	return auth != nil && !auth.IsSuperuser() && auth.Collection().Name == "members" && !effectiveAccess(app, auth).all
}

const rosterProbeRefusal = "a member limited to some teams cannot filter or sort through a relation to or from members " +
	"(assignee.name, author.kind, issues_via_assignee, ...); filter on the id instead, e.g. assignee = 'ID'"

// recordsCollection extracts {collection} from /api/collections/{collection}/records.
var recordsCollection = regexp.MustCompile(`^/api/collections/([^/]+)/records/?$`)

// refuseRosterProbes is router middleware for the records list endpoint
// (the only one that takes filter= and sort=).
func refuseRosterProbes(re *core.RequestEvent) error {
	if re.Request.Method != http.MethodGet {
		return re.Next()
	}
	match := recordsCollection.FindStringSubmatch(re.Request.URL.Path)
	if match == nil || !narrowCaller(re.App, re.Auth) {
		return re.Next()
	}
	collection, err := re.App.FindCachedCollectionByNameOrId(match[1])
	if err != nil {
		return re.Next()
	}
	q := re.Request.URL.Query()
	if crossesRoster(re.App, collection, q.Get(search.FilterQueryParam), q.Get(search.SortQueryParam)) {
		return re.ForbiddenError(rosterProbeRefusal, nil)
	}
	return re.Next()
}

// pathRecorder is a search.FieldResolver that only collects the field paths
// a filter names, so the filter is parsed by PocketBase's own grammar.
type pathRecorder struct{ paths []string }

func (p *pathRecorder) UpdateQuery(*dbx.SelectQuery) error { return nil }

func (p *pathRecorder) Resolve(field string) (*search.ResolverResult, error) {
	p.paths = append(p.paths, field)
	return &search.ResolverResult{Identifier: "NULL"}, nil
}

// crossesRoster reports whether a filter or sort on base walks a relation
// into or out of members. A filter that does not parse is left to
// PocketBase, which refuses it with its own message.
func crossesRoster(app core.App, base *core.Collection, filter, sort string) bool {
	rec := &pathRecorder{}
	if filter != "" {
		if _, err := search.FilterData(filter).BuildExpr(rec); err != nil {
			return false
		}
	}
	for _, f := range search.ParseSortFromString(sort) {
		rec.paths = append(rec.paths, f.Name)
	}
	for _, path := range rec.paths {
		if pathCrossesRoster(app, base, path) {
			return true
		}
	}
	return false
}

var viaProp = regexp.MustCompile(`^(\w+)_via_(\w+)$`)

// pathCrossesRoster walks one dotted path ("assignee.name",
// "issues_via_assignee.title") from base. Every hop but the last prop is a
// relation or a back-relation; a hop whose either end is members crosses.
func pathCrossesRoster(app core.App, base *core.Collection, path string) bool {
	if strings.HasPrefix(path, "@") {
		return false // @request/@collection: superuser-only in a query already
	}
	props := strings.Split(path, ".")
	current := base
	for _, prop := range props[:len(props)-1] {
		prop, _, _ = strings.Cut(prop, ":")
		var next *core.Collection
		if field, ok := current.Fields.GetByName(prop).(*core.RelationField); ok {
			next, _ = app.FindCachedCollectionByNameOrId(field.CollectionId)
		} else if parts := viaProp.FindStringSubmatch(prop); parts != nil {
			next, _ = app.FindCachedCollectionByNameOrId(parts[1])
		}
		if next == nil {
			return false // a json path or an unknown field: not a relation hop
		}
		if current.Name == "members" || next.Name == "members" {
			return true
		}
		current = next
	}
	return false
}
