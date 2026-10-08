package gopb

import (
	"encoding/json"
	"net/url"
	"regexp"
	"slices"
	"strings"

	"github.com/ganigeorgiev/fexpr"
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/search"
	"github.com/spf13/cast"
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
//   - relation filters: PocketBase checks the far side's list rule on a
//     joined row, but not inside a multi-match subquery (a plain operator
//     on a multi-valued relation or a back-relation: "every related row
//     matches"), and those rows include hidden ones. So "teams.key ~ 'B%'"
//     on a visible member, or "issues_via_assignee.title ~ 'x%'", would
//     read hidden records one character at a time (finding
//     pb-relation-filters-skip-target-rules). A narrower caller may not
//     filter or sort through any relation into or out of members: one rule,
//     rather than a list of the operators that happen to be safe. The same
//     oracle on every other collection (labels.name, blocked_by.title) is
//     readsHiddenRows (LLL-634);
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

// onTeamRoster reports whether every member who sees team teamID may see m:
// m is on that team, or m is a person with access to every team. Output with
// no single viewer (webhook payloads) names only these; the board applies
// the same rule (serve_roster.lis team_roster).
func onTeamRoster(m *core.Record, teamID string) bool {
	return slices.Contains(m.GetStringSlice("teams"), teamID) ||
		(m.GetString("scope") == "all" && m.GetString("kind") != botKind)
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
			if why := topicRefusal(e.App, topic); why != "" {
				return e.ForbiddenError(why, nil)
			}
		}
		return e.Next()
	})

	// A subscription is checked when it is made, so narrowing a member
	// afterwards (or the owner of a bot) must drop the subscriptions it could
	// no longer make (LLL-634 review F3). PocketBase keeps a client's
	// subscriptions across an auth record update and only refreshes the
	// cached record.
	app.OnRecordAfterUpdateSuccess("members").BindFunc(func(e *core.RecordEvent) error {
		before := e.Record.Original()
		for _, field := range []string{"scope", "teams", "owner", "mode"} {
			if !slices.Equal(e.Record.GetStringSlice(field), before.GetStringSlice(field)) {
				dropRefusedSubscriptions(e.App, e.Record.Id)
				break
			}
		}
		return e.Next()
	})
}

// dropRefusedSubscriptions unsubscribes, for every realtime client
// authenticated as memberID or as a bot it owns, each topic the subscribe
// hook would now refuse.
func dropRefusedSubscriptions(app core.App, memberID string) {
	for _, client := range app.SubscriptionsBroker().Clients() {
		cached, _ := client.Get(apis.RealtimeClientAuthKey).(*core.Record)
		if cached == nil || cached.Collection().Name != "members" {
			continue
		}
		auth, err := app.FindRecordById("members", cached.Id)
		if err != nil || (auth.Id != memberID && auth.GetString("owner") != memberID) || !narrowCaller(app, auth) {
			continue
		}
		for topic := range client.Subscriptions() {
			if topicRefusal(app, topic) != "" {
				client.Unsubscribe(topic)
			}
		}
	}
}

// topicRefusal is why a narrow caller may not hold a realtime subscription
// to topic, or "". It reads the options exactly as PocketBase will
// (tools/subscriptions/client.go Subscribe): url.Parse, then the "options"
// query value however it is spelled or placed. A string cut on "?options="
// missed "?x=1&options=" and "?opt%69ons=" (LLL-551 review F1).
func topicRefusal(app core.App, topic string) string {
	u, err := url.Parse(topic)
	if err != nil {
		return "" // PocketBase ignores the options too
	}
	raw := u.Query().Get("options")
	if raw == "" {
		return ""
	}
	var options struct {
		Query map[string]any `json:"query"`
	}
	if err := json.Unmarshal([]byte(raw), &options); err != nil {
		return "" // PocketBase ignores options that do not decode
	}
	filter, sort := cast.ToString(options.Query[search.FilterQueryParam]), cast.ToString(options.Query[search.SortQueryParam])
	if filter == "" && sort == "" {
		return ""
	}
	name, _, _ := strings.Cut(u.Path, "/")
	collection, err := app.FindCachedCollectionByNameOrId(name)
	if err != nil {
		return rosterProbeRefusal
	}
	return probeRefusal(app, collection, filter, sort)
}

// narrowCaller is true for a member whose effective access is narrower than
// every team: the callers the roster rule limits.
func narrowCaller(app core.App, auth *core.Record) bool {
	return auth != nil && !auth.IsSuperuser() && auth.Collection().Name == "members" && !effectiveAccess(app, auth).all
}

const rosterProbeRefusal = "a member limited to some teams cannot filter or sort through a relation to or from members " +
	"(assignee.name, author.kind, issues_via_assignee, ...), or on a member's email or teams; filter on the id instead, e.g. assignee = 'ID'"

// recordsCollection extracts {collection} from /api/collections/{collection}/records.
var recordsCollection = regexp.MustCompile(`^/api/collections/([^/]+)/records/?$`)

// refuseRosterProbes is router middleware for the records list endpoint
// (the only one that takes filter= and sort=). Every method, not only GET:
// Go's mux serves HEAD with the GET handler, and a HEAD answer's
// Content-Length still tells one result from none.
func refuseRosterProbes(re *core.RequestEvent) error {
	match := recordsCollection.FindStringSubmatch(re.Request.URL.Path)
	if match == nil || !narrowCaller(re.App, re.Auth) {
		return re.Next()
	}
	collection, err := re.App.FindCachedCollectionByNameOrId(match[1])
	if err != nil {
		return re.Next()
	}
	q := re.Request.URL.Query()
	if why := probeRefusal(re.App, collection, q.Get(search.FilterQueryParam), q.Get(search.SortQueryParam)); why != "" {
		return re.ForbiddenError(why, nil)
	}
	return re.Next()
}

// relationProbeRefusal is the answer to a filter or sort that could read
// rows in another team (LLL-634).
const relationProbeRefusal = "a member limited to some teams cannot use a plain operator (=, !=, ~, !~, <, >) through a multi-valued relation, " +
	"a back-relation or @collection (labels.name ~ ..., blocked_by.title = ..., comments_via_issue.body ~ ...), sort through one, " +
	"or compare a relation's stored ids other than exactly: use the any-match form (labels.name ?~ 'x') or an id (labels.id ?= 'ID', project = 'ID')"

// operand is one field path a filter or sort names, with the operator it
// is compared by ("" for a sort or a function argument).
type operand struct {
	path string
	op   fexpr.SignOp
}

func anyMatch(op fexpr.SignOp) bool { return strings.HasPrefix(string(op), "?") }

// filterOperands parses filter with PocketBase's own grammar (fexpr, the
// parser search.FilterData uses) and returns every field path with its
// operator. ok is false for a filter that does not parse; PocketBase refuses
// it with its own message.
func filterOperands(filter string) (ops []operand, ok bool) {
	if filter == "" {
		return nil, true
	}
	groups, err := fexpr.Parse(filter)
	if err != nil {
		return nil, false
	}
	var token func(t fexpr.Token, op fexpr.SignOp)
	token = func(t fexpr.Token, op fexpr.SignOp) {
		switch t.Type {
		case fexpr.TokenIdentifier:
			ops = append(ops, operand{t.Literal, op})
		case fexpr.TokenFunction:
			// A function's arguments are resolved through the same
			// resolver; take them as plain, the strict reading.
			args, _ := t.Meta.([]fexpr.Token)
			for _, arg := range args {
				token(arg, "")
			}
		}
	}
	var walk func(items []fexpr.ExprGroup)
	walk = func(items []fexpr.ExprGroup) {
		for _, g := range items {
			switch item := g.Item.(type) {
			case fexpr.Expr:
				token(item.Left, item.Op)
				token(item.Right, item.Op)
			case fexpr.ExprGroup:
				walk([]fexpr.ExprGroup{item})
			case []fexpr.ExprGroup:
				walk(item)
			}
		}
	}
	walk(groups)
	return ops, true
}

// probeRefusal is why a narrow caller may not run filter and sort on base,
// or "" when it may.
func probeRefusal(app core.App, base *core.Collection, filter, sort string) string {
	ops, ok := filterOperands(filter)
	if !ok {
		return ""
	}
	for _, f := range search.ParseSortFromString(sort) {
		ops = append(ops, operand{path: f.Name})
	}
	for _, o := range ops {
		if pathCrossesRoster(app, base, o.path) {
			return rosterProbeRefusal
		}
	}
	for _, o := range ops {
		if readsHiddenRows(app, base, o) {
			return relationProbeRefusal
		}
	}
	return ""
}

// readsHiddenRows reports whether o could be decided by rows the caller may
// not see (LLL-634, finding pb-relation-filters-skip-target-rules).
// PocketBase applies a related collection's list rule to a JOINED row, but a
// plain operator through a multi-valued relation, a back-relation
// (x_via_y) or @collection compiles to a multi-match subquery ("every
// related row matches") that skips it. So labels.name ~ "%e%" on a visible
// issue read the names of another team's labels on it, one character at a
// time. The rule, one for every collection rather than a list of the ones
// whose targets happen to be same-team today (favorites_via_issue, for one,
// would read other members' favorites):
//
//   - @collection.* needs a ?-operator (PocketBase already refuses it to
//     anyone but a superuser; this keeps the rule from depending on that);
//   - a hop through a multi-valued relation or a back-relation needs a
//     ?-operator, and cannot be sorted on;
//   - a relation field itself (its stored ids, which may name hidden rows)
//     may only be matched exactly: =, != or ?=, ?!= on a single relation,
//     ?=, ?!= on a multi-valued one, with no modifier, and not sorted on.
//
// Allowed, because a ?-operator and a single-relation hop use the joined,
// rule-checked row: state = 'todo', title ~ 'x', project = 'ID',
// team = 'ID', labels.id ?= 'ID', labels.name ?~ 'bug', blocked_by.id ?= 'ID',
// project.name ~ 'x', sort=-created or sort=project.name.
// memberScoped collections hold rows a narrow caller sees only when they are
// its own (favorites, saved views). A hop into one is refused with any
// operator: PocketBase ANDs the joined row's list rule at the top level, so
// a visible issue another member favorited drops out of
// "favorites_via_issue.id ?!= 'x' || id != ”", and the gap is the answer
// (LLL-634 review F1).
var memberScoped = map[string]bool{"favorites": true, "views": true}

func readsHiddenRows(app core.App, base *core.Collection, o operand) bool {
	path := o.path
	current := base
	switch {
	case strings.HasPrefix(path, "@collection."):
		return !anyMatch(o.op)
	case strings.HasPrefix(path, "@request.auth."):
		members, err := app.FindCachedCollectionByNameOrId("members")
		if err != nil {
			return false
		}
		current, path = members, strings.TrimPrefix(path, "@request.auth.")
	case strings.HasPrefix(path, "@"):
		return false // @request.body/query/headers, @now, ...: no rows
	}
	props := strings.Split(path, ".")
	for i, raw := range props {
		prop, modifier, _ := strings.Cut(raw, ":")
		last := i == len(props)-1
		var next *core.Collection
		if field, ok := current.Fields.GetByName(prop).(*core.RelationField); ok {
			if last {
				exact := o.op == fexpr.SignAnyEq || o.op == fexpr.SignAnyNeq
				if !field.IsMultiple() {
					exact = exact || o.op == fexpr.SignEq || o.op == fexpr.SignNeq
				}
				return modifier != "" || !exact
			}
			if field.IsMultiple() && !anyMatch(o.op) {
				return true
			}
			next, _ = app.FindCachedCollectionByNameOrId(field.CollectionId)
		} else if parts := viaProp.FindStringSubmatch(prop); parts != nil && !last {
			if !anyMatch(o.op) {
				return true
			}
			next, _ = app.FindCachedCollectionByNameOrId(parts[1])
		}
		if next == nil {
			return false // a plain field, a json path or an unknown name
		}
		if memberScoped[next.Name] {
			return true
		}
		current = next
	}
	return false
}

var viaProp = regexp.MustCompile(`^(\w+)_via_(\w+)$`)

// pathCrossesRoster walks one dotted path ("assignee.name",
// "issues_via_assignee.title") from base. Every hop but the last prop is a
// relation or a back-relation; a hop whose either end is members crosses.
//
// On members itself, `email` and `teams` cross too (LLL-551 review F2, F3):
// PocketBase guards an email FILTER with emailVisibility but not an email
// SORT, and a bot the caller mints with a chosen email makes the order an
// oracle; and `teams` holds the stored ids the enrich hook strips, so
// "teams ~ 'x'" or "teams:length = 2" would read hidden team ids.
func pathCrossesRoster(app core.App, base *core.Collection, path string) bool {
	if strings.HasPrefix(path, "@") {
		return false // @request/@collection: superuser-only in a query already
	}
	props := strings.Split(path, ".")
	current := base
	if base.Name == "members" {
		if first, _, _ := strings.Cut(props[0], ":"); first == core.FieldNameEmail || first == "teams" {
			return true
		}
	}
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
