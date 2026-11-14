package gopb

import (
	"errors"
	"net/http"
	"sync"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

var errClosedProjectAuthority = errors.New("project removal authority is outside its transaction or already consumed")

type writableProjectCascade struct{ scope *projectRemovalScope }
type projectRemovalScope struct {
	mu      sync.Mutex
	active  bool
	app     core.App
	project *core.Record
	issues  []*core.Record
	preview cascadePreview
}

// The displayed revision is a freshness guard, not authority. Only this
// constructor can bind the current actor, complete deletion plan and revision
// to a removal operation. No writing/read-only boolean reaches the route.
func withWritableProjectCascade(re *core.RequestEvent, revision string, write func(writableProjectCascade) (cascadePreview, error)) (cascadePreview, error) {
	var out cascadePreview
	err := re.App.RunInTransaction(func(tx core.App) error {
		actor, err := lifecycleCaller(tx, re.Auth)
		if err != nil {
			return err
		}
		preview, rows, err := prepareProjectCascade(tx, actor, re.Request.PathValue("project"))
		if err != nil {
			return err
		}
		project, err := tx.FindRecordById("projects", preview.Project)
		if err != nil {
			return err
		}
		if !effectiveAccess(tx, actor).writes(project.GetString("team")) {
			return router.NewForbiddenError(readOnlyRefusal(actor), nil)
		}
		if err := archivedRefusal(tx, actor, project.GetString("team")); err != nil {
			return err
		}
		if preview.Revision != revision {
			return router.NewApiError(http.StatusConflict, "project changed since preview; preview again before deleting", nil)
		}
		if len(preview.Blockers) > 0 {
			return router.NewApiError(http.StatusConflict, "project has claims or external references; release or detach them before deleting", nil)
		}
		scope := &projectRemovalScope{active: true, app: tx, project: project, issues: rows, preview: preview}
		defer func() { scope.mu.Lock(); scope.active = false; scope.mu.Unlock() }()
		out, err = write(writableProjectCascade{scope: scope})
		return err
	})
	return out, err
}
func (proof writableProjectCascade) remove() (cascadePreview, error) {
	if proof.scope == nil {
		return cascadePreview{}, errClosedProjectAuthority
	}
	s := proof.scope
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.active {
		return cascadePreview{}, errClosedProjectAuthority
	}
	s.active = false
	for _, issue := range s.issues {
		if err := s.app.Delete(issue); err != nil {
			return cascadePreview{}, err
		}
	}
	if err := s.app.Delete(s.project); err != nil {
		return cascadePreview{}, err
	}
	return s.preview, nil
}
