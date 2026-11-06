package gopb

import (
	"fmt"

	"github.com/pocketbase/dbx"
	validation "github.com/pocketbase/ozzo-validation/v4"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

const treeForceCloseKey = "@lll_tree_force_close"

// registerIssueTreeGuard owns containment invariants for every issue writer.
// The graph read and save share SQLite's serialized writer transaction, so two
// individually valid reparentings cannot commit a cycle together. It also
// reads the current stored state rather than an API request's stale Original.
func registerIssueTreeGuard(app core.App) {
	check := func(e *core.RecordEvent) error {
		// Earlier migrations can save issues before the additive parent migration.
		if e.Record.Collection().Fields.GetByName("parent") == nil {
			return e.Next()
		}
		original := e.App
		defer func() { e.App = original }()
		return original.RunInTransaction(func(tx core.App) error {
			e.App = tx
			if err := checkIssueParent(tx, e.Record); err != nil {
				return err
			}
			if err := checkIssueTreeClose(tx, e.Record); err != nil {
				return err
			}
			return e.Next()
		})
	}
	app.OnRecordCreate("issues").BindFunc(check)
	app.OnRecordUpdate("issues").BindFunc(check)
	// A request may explicitly force a close. Never trust a client-supplied
	// custom record key; every request replaces this in-memory-only marker.
	app.OnRecordUpdateRequest("issues").BindFunc(func(e *core.RecordRequestEvent) error {
		e.Record.Set(treeForceCloseKey, e.Request.URL.Query().Get("force") == "true")
		return e.Next()
	})
}

func treeRefusal(code, message string) error {
	return validation.Errors{"parent": validation.NewError(code, message)}
}

func checkIssueParent(app core.App, issue *core.Record) error {
	seen := map[string]bool{issue.Id: true}
	parent := issue.GetString("parent")
	for parent != "" {
		if seen[parent] {
			return treeRefusal("validation_parent_cycle", "parent would create a cycle; choose an issue outside this subtree")
		}
		seen[parent] = true
		ancestor, err := app.FindRecordById("issues", parent)
		if err != nil || ancestor.GetString("team") != issue.GetString("team") {
			return treeRefusal("validation_parent_team", "parent must be an existing issue in the same team")
		}
		parent = ancestor.GetString("parent")
	}
	return nil
}

// openIssueDescendants counts through closed intermediate nodes too. SQLite's
// recursive UNION avoids a query per descendant and remains bounded if a
// restored/corrupt graph contains a cycle. It reads only the count, never
// hidden issue titles. Parent references themselves are constrained by team.
func openIssueDescendants(app core.App, id string) (int, error) {
	var result struct {
		Count int `db:"count"`
	}
	err := app.DB().NewQuery(`WITH RECURSIVE descendants(id, state) AS (
 SELECT id, state FROM issues WHERE parent = {:id}
 UNION
 SELECT issues.id, issues.state FROM issues JOIN descendants ON issues.parent = descendants.id
 ) SELECT count(*) AS count FROM descendants WHERE state NOT IN ('done', 'cancelled')`).
		Bind(dbx.Params{"id": id}).One(&result)
	return result.Count, err
}

func checkIssueTreeClose(app core.App, issue *core.Record) error {
	state := issue.GetString("state")
	if state != "done" && state != "cancelled" || issue.GetBool(treeForceCloseKey) {
		return nil
	}
	if !issue.IsNew() {
		stored, err := app.FindRecordById("issues", issue.Id)
		if err != nil {
			return err
		}
		if stored.GetString("state") == state {
			return nil
		}
	}
	count, err := openIssueDescendants(app, issue.Id)
	if err != nil {
		return err
	}
	if count == 0 {
		return nil
	}
	return treeRefusal("validation_open_descendants", fmt.Sprintf("this issue has %d open descendant(s); finish them first or explicitly force the close", count))
}

// The native records and composite assignment routes share the same refusal
// for a parent that is absent or outside the authenticated caller's scope.
func parentRefsInScope(app core.App, auth *core.Record, ids []string) error {
	for _, id := range ids {
		if _, err := app.FindRecordById("issues", id); err != nil {
			return router.NewBadRequestError("Failed to find all relation records with the provided ids.", nil)
		}
	}
	return refsInScope(app, auth, "issues", ids)
}
