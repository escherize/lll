package gopb

import (
	"fmt"
	"slices"
	"strings"

	"github.com/pocketbase/dbx"
	validation "github.com/pocketbase/ozzo-validation/v4"
	"github.com/pocketbase/pocketbase/core"
)

// LLL-631: a reference stays inside one team, for every writer.
//
// LLL-100 decided to refuse cross-team references (a label, project or blocker
// from another team on an issue), and the CLI refuses them, but the server
// refused them only for team-scoped members (checkNewRefs). An all-scope
// member, a superuser or a raw PATCH {team: BETA} could still leave an ALPHA
// row pointing at BETA's records. Those references are what the board had to
// hide at render time and what LLL-634's filter oracle reads.
//
// The rule, checked on every save of a collection in scopedRefs or a target
// of one (OnRecordCreate/OnRecordUpdate, so the records API, the custom
// /api/lll routes and the app's own saves all pass through it):
//
//   - create: every reference must be in the record's team;
//   - update that keeps the team: every ADDED reference must be in it, so a
//     reference made before this rule does not block an unrelated edit
//     (scripts/audit_cross_team_refs.py lists those);
//   - update that changes the team (a move): every reference the record
//     holds, and every reference other records hold to it, must be in the
//     NEW team. The refusal names what to detach.
//
// Superusers are not exempt. Nothing in the existing code exempted them on
// purpose: checkNewRefs skipped them only because a superuser sees every
// team, which is the same accident that skipped all-scope members. A
// superuser who needs a cross-team reference has no use the data model
// supports, since every renderer would have to hide it again.
//
// The check runs in the save's transaction (one writer connection), so a
// concurrent move of the label and an edit adding it to an issue cannot both
// pass against the state before the other.

// refHolders is the inverse of scopedRefs: target collection -> the
// collections and fields that point at it.
func refHolders(target string) [][2]string {
	var out [][2]string
	for collection, fields := range scopedRefs {
		for field, to := range fields {
			if to == target {
				out = append(out, [2]string{collection, field})
			}
		}
	}
	slices.SortFunc(out, func(a, b [2]string) int { return strings.Compare(a[0]+"."+a[1], b[0]+"."+b[1]) })
	return out
}

func registerTeamRefGuard(app core.App) {
	guarded := map[string]bool{}
	for collection, fields := range scopedRefs {
		guarded[collection] = true
		for _, target := range fields {
			guarded[target] = true
		}
	}
	names := make([]string, 0, len(guarded))
	for name := range guarded {
		names = append(names, name)
	}
	check := func(e *core.RecordEvent) error {
		original := e.App
		defer func() { e.App = original }()
		return original.RunInTransaction(func(tx core.App) error {
			e.App = tx
			if err := checkTeamRefs(tx, e.Record); err != nil {
				return err
			}
			return e.Next()
		})
	}
	app.OnRecordCreate(names...).BindFunc(check)
	app.OnRecordUpdate(names...).BindFunc(check)
}

// checkTeamRefs applies the rule above to record as it is about to be saved.
func checkTeamRefs(app core.App, record *core.Record) error {
	collection := record.Collection().Name
	team := record.GetString("team")
	from := ""
	moved := false
	if !record.IsNew() {
		from = record.Original().GetString("team")
		moved = from != team
	}
	var problems []string
	for _, field := range sortedKeys(scopedRefs[collection]) {
		target := scopedRefs[collection][field]
		ids := record.GetStringSlice(field)
		if !record.IsNew() && !moved {
			ids = added(ids, record.Original().GetStringSlice(field))
		}
		for _, id := range ids {
			ref, err := app.FindRecordById(target, id)
			if err != nil {
				continue // the relation validator reports a missing id
			}
			if ref.GetString("team") != team {
				problems = append(problems, field+": "+describeRef(app, ref, from, team))
			}
		}
	}
	if moved {
		for _, holder := range refHolders(collection) {
			others, err := app.FindRecordsByFilter(holder[0],
				fmt.Sprintf("%s.id ?= {:id} && team != {:team}", holder[1]), "id", 0, 0,
				dbx.Params{"id": record.Id, "team": team})
			if err != nil {
				return err
			}
			for _, other := range others {
				problems = append(problems, holder[0]+"."+holder[1]+" of "+describeRef(app, other, from, team))
			}
		}
	}
	if len(problems) == 0 {
		return nil
	}
	return validation.Errors{"team": validation.NewError("validation_cross_team_ref", teamRefRefusal(app, record, from, team, moved, problems))}
}

// teamRefRefusal says what is wrong and what to do about it.
func teamRefRefusal(app core.App, record *core.Record, from, team string, moved bool, problems []string) string {
	what := strings.TrimSuffix(record.Collection().Name, "s")
	shown := problems
	more := ""
	if len(shown) > 10 {
		more = fmt.Sprintf(" (and %d more)", len(shown)-10)
		shown = shown[:10]
	}
	list := strings.Join(shown, "; ") + more
	if moved {
		return fmt.Sprintf("a reference stays inside one team: moving this %s from %s to %s would leave references across teams: %s. "+
			"Detach them first (e.g. labels-, blocked_by-, project: \"\"), or move those records to %s too",
			what, teamKey(app, from), teamKey(app, team), list, teamKey(app, team))
	}
	return fmt.Sprintf("a reference stays inside one team: this %s is in %s, so it cannot reference %s. "+
		"Use %s's own labels, projects and issues",
		what, teamKey(app, team), list, teamKey(app, team))
}

// describeRef names ref for a refusal. The writer of a record must see its
// old and new team (the collection rules require both), so a ref in either
// is named; one anywhere else is only "in another team", with its id, so a
// refusal never names a team or record the writer may not see.
func describeRef(app core.App, ref *core.Record, from, to string) string {
	refTeam := ref.GetString("team")
	if refTeam != from && refTeam != to {
		return strings.TrimSuffix(ref.Collection().Name, "s") + " " + ref.Id + " in another team"
	}
	key := teamKey(app, refTeam)
	switch ref.Collection().Name {
	case "issues":
		return fmt.Sprintf("issue %s-%d", key, ref.GetInt("number"))
	case "docs":
		return fmt.Sprintf("doc '%s' (%s)", ref.GetString("slug"), key)
	case "webhooks":
		return fmt.Sprintf("webhook %s (%s)", ref.Id, key)
	default:
		return fmt.Sprintf("%s '%s' (%s)", strings.TrimSuffix(ref.Collection().Name, "s"), ref.GetString("name"), key)
	}
}

func teamKey(app core.App, id string) string {
	if t, err := app.FindRecordById("teams", id); err == nil {
		return t.GetString("key")
	}
	return "no team"
}

func sortedKeys(m map[string]string) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	return keys
}
