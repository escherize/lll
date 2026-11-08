package gopb

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"sort"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

type cascadeIssue struct {
	ID    string `json:"id"`
	Key   string `json:"key"`
	Title string `json:"title"`
	State string `json:"state"`
}
type cascadeBlocker struct {
	Kind  string `json:"kind"`
	Count int    `json:"count"`
}
type cascadePreview struct {
	Project  string           `json:"project"`
	Name     string           `json:"name"`
	Issues   []cascadeIssue   `json:"issues"`
	Blockers []cascadeBlocker `json:"blockers"`
	Revision string           `json:"revision"`
}

// A revision covers complete affected records, not just issue.updated: comments
// and relation changes do not necessarily advance that timestamp. The hash is a
// compare-and-swap guard, never an authorization credential.
func prepareProjectCascade(app core.App, auth *core.Record, id string, writing bool) (cascadePreview, []*core.Record, error) {
	out := cascadePreview{Issues: []cascadeIssue{}, Blockers: []cascadeBlocker{}}
	if auth == nil {
		return out, nil, router.NewUnauthorizedError("sign in first", nil)
	}
	caller, err := app.FindRecordById(auth.Collection(), auth.Id)
	if err != nil || caller.TokenKey() != auth.TokenKey() {
		return out, nil, router.NewUnauthorizedError("the credential is no longer current", nil)
	}
	project, err := app.FindRecordById("projects", id)
	if err != nil {
		return out, nil, router.NewNotFoundError("project not found", nil)
	}
	acc := effectiveAccess(app, caller)
	if !acc.sees(project.GetString("team")) {
		return out, nil, router.NewNotFoundError("project not found", nil)
	}
	if writing {
		if !acc.rw {
			return out, nil, router.NewForbiddenError(readOnlyRefusal(caller), nil)
		}
		if err := archivedRefusal(app, caller, project.GetString("team")); err != nil {
			return out, nil, err
		}
	}
	team, err := app.FindRecordById("teams", project.GetString("team"))
	if err != nil {
		return out, nil, err
	}
	rows, err := app.FindRecordsByFilter("issues", "project = {:project}", "id", 0, 0, dbx.Params{"project": id})
	if err != nil {
		return out, nil, err
	}
	out.Project = id
	out.Name = project.GetString("name")
	inside := map[string]bool{}
	records := map[string]any{"projects/" + id: project.PublicExport()}
	for _, issue := range rows {
		// Historical cross-team references must not disclose or delete hidden work.
		if issue.GetString("team") != project.GetString("team") {
			return out, nil, router.NewApiError(http.StatusConflict, "project has inconsistent team references; repair them first", nil)
		}
		inside[issue.Id] = true
		out.Issues = append(out.Issues, cascadeIssue{issue.Id, team.GetString("key") + "-" + issue.GetString("number"), issue.GetString("title"), issue.GetString("state")})
		records["issues/"+issue.Id] = issue.PublicExport()
	}
	blocked := map[string]int{}
	// Discover references from PocketBase's schema, including multi relations.
	// Native deletion may clear external references; cascade refuses those instead.
	for _, target := range []string{"projects", "issues"} {
		collection, err := app.FindCollectionByNameOrId(target)
		if err != nil {
			return out, nil, err
		}
		refs, err := app.FindCollectionReferences(collection)
		if err != nil {
			return out, nil, err
		}
		ids := []string{id}
		if target == "issues" {
			ids = ids[:0]
			for _, r := range rows {
				ids = append(ids, r.Id)
			}
		}
		for source, fields := range refs {
			for _, field := range fields {
				for _, targetID := range ids {
					found, err := app.FindRecordsByFilter(source.Name, field.GetName()+".id ?= {:id}", "id", 0, 0, dbx.Params{"id": targetID})
					if err != nil {
						return out, nil, err
					}
					for _, record := range found {
						key := source.Name + "/" + record.Id
						if _, seen := records[key]; !seen {
							records[key] = record.PublicExport()
						}
						allowed := target == "projects" && source.Name == "issues" && inside[record.Id]
						if target == "issues" {
							allowed = source.Name == "comments" || source.Name == "favorites" || source.Name == "issues" && inside[record.Id]
						}
						if !allowed {
							blocked[source.Name+"."+field.GetName()]++
						}
					}
				}
			}
		}
	}
	keys := make([]string, 0, len(blocked))
	for key := range blocked {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		out.Blockers = append(out.Blockers, cascadeBlocker{key, blocked[key]})
	}
	raw, err := json.Marshal(records)
	if err != nil {
		return out, nil, err
	}
	sum := sha256.Sum256(raw)
	out.Revision = hex.EncodeToString(sum[:])
	return out, rows, nil
}

func registerProjectCascadeRoutes(routes *router.Router[*core.RequestEvent]) {
	routes.GET("/api/lll/projects/cascade-support", func(re *core.RequestEvent) error { return re.JSON(http.StatusOK, map[string]bool{"supported": true}) })
	routes.GET("/api/lll/projects/{project}/cascade", func(re *core.RequestEvent) error {
		preview, _, err := prepareProjectCascade(re.App, re.Auth, re.Request.PathValue("project"), false)
		if err != nil {
			return err
		}
		return re.JSON(http.StatusOK, preview)
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))
	routes.POST("/api/lll/projects/{project}/cascade", func(re *core.RequestEvent) error {
		var body struct {
			Revision string `json:"revision"`
		}
		re.Request.Body = http.MaxBytesReader(re.Response, re.Request.Body, 4096)
		if err := re.BindBody(&body); err != nil || len(body.Revision) != 64 {
			return re.BadRequestError("a preview revision is required", nil)
		}
		var result cascadePreview
		err := re.App.RunInTransaction(func(tx core.App) error {
			preview, rows, err := prepareProjectCascade(tx, re.Auth, re.Request.PathValue("project"), true)
			if err != nil {
				return err
			}
			if preview.Revision != body.Revision {
				return router.NewApiError(http.StatusConflict, "project changed since preview; preview again before deleting", nil)
			}
			if len(preview.Blockers) > 0 {
				return router.NewApiError(http.StatusConflict, "project has claims or external references; release or detach them before deleting", nil)
			}
			for _, issue := range rows {
				if err := tx.Delete(issue); err != nil {
					return err
				}
			}
			project, err := tx.FindRecordById("projects", preview.Project)
			if err != nil {
				return err
			}
			if err := tx.Delete(project); err != nil {
				return err
			}
			result = preview
			return nil
		})
		if err != nil {
			var answered *router.ApiError
			if errors.As(err, &answered) {
				return err
			}
			return re.InternalServerError("project cascade failed; nothing was deleted", err)
		}
		return re.JSON(http.StatusOK, map[string]any{"project": result.Project, "deleted": true, "issues": result.Issues})
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))
}
