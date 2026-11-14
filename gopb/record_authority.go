package gopb

import (
	"errors"
	"sync"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

var errClosedRecordAuthority = errors.New("record write authority is outside its transaction or already consumed")

// writableRecordRequest is a single native operation, not an ambient write
// flag. Only its bound continuation can use it. Copies share a closed lease;
// Go cannot express a generative transaction lifetime in its type system.
type writableRecordRequest struct{ scope *recordWriteScope }
type recordWriteScope struct {
	mu     sync.Mutex
	active bool
	next   func() error
}

func (proof writableRecordRequest) commit() error {
	if proof.scope == nil {
		return errClosedRecordAuthority
	}
	s := proof.scope
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.active {
		return errClosedRecordAuthority
	}
	s.active = false
	return s.next()
}

// Native rules remain the first boundary. They have already run when a
// request hook is reached; their actor snapshot may predate a wait on the
// database writer. Parse fresh source/destination authority while holding that
// writer and keep the native save in the same transaction. System model saves
// deliberately do not enter this request-only boundary.
func withWritableRecordRequest(e *core.RecordRequestEvent, write func(writableRecordRequest) error) error {
	originalApp, originalAuth := e.App, e.Auth
	defer func() { e.App, e.Auth = originalApp, originalAuth }()
	return originalApp.RunInTransaction(func(tx core.App) error {
		actor, err := lifecycleCaller(tx, originalAuth)
		if err != nil {
			return err
		}
		teams := []string{recordTeam(tx, e.Record)}
		if !e.Record.IsNew() {
			stored, err := tx.FindRecordById(e.Record.Collection().Id, e.Record.Id)
			if err != nil {
				return router.NewNotFoundError("record not found", nil)
			}
			teams = append(teams, recordTeam(tx, stored))
		}
		acc := effectiveAccess(tx, actor)
		for _, team := range teams {
			if !actor.IsSuperuser() {
				if !acc.sees(team) {
					return router.NewNotFoundError("record not found", nil)
				}
				if !acc.writes(team) {
					return router.NewForbiddenError(readOnlyRefusal(actor), nil)
				}
			}
			if err := archivedRefusal(tx, actor, team); err != nil {
				return err
			}
		}
		e.App, e.Auth = tx, actor
		scope := &recordWriteScope{active: true, next: e.Next}
		defer func() { scope.mu.Lock(); scope.active = false; scope.mu.Unlock() }()
		return write(writableRecordRequest{scope: scope})
	})
}
