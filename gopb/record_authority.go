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
		e.App, e.Auth = tx, actor
		switch e.Record.Collection().Name {
		case "members":
			if err := nativeMemberAuthority(e, actor); err != nil {
				return err
			}
		case "teams":
			acc := effectiveAccess(tx, actor)
			if !actor.IsSuperuser() && !isWorkspaceAdmin(actor) && !(acc.all && acc.rw) {
				return router.NewForbiddenError("workspace Admin or legacy all-team management authority is required", nil)
			}
		default:
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
		}
		scope := &recordWriteScope{active: true, next: e.Next}
		defer func() { scope.mu.Lock(); scope.active = false; scope.mu.Unlock() }()
		return write(writableRecordRequest{scope: scope})
	})
}

// Native member creation rules depend on both target kind/owner and the
// request actor. Re-establish those mutable facts before issuing the bound
// continuation. Static body-field protections remain in the native rules.
func nativeMemberAuthority(e *core.RecordRequestEvent, actor *core.Record) error {
	if actor.IsSuperuser() {
		return nil
	}
	if !e.Record.IsNew() {
		info, err := e.RequestInfo()
		if err != nil {
			return err
		}
		allowed, err := e.App.CanAccessRecord(e.Record, info, e.Record.Collection().UpdateRule)
		if err != nil {
			return router.NewInternalServerError("could not establish member update authority", err)
		}
		if !allowed {
			return router.NewNotFoundError("member not found", nil)
		}
		return nil
	}
	acc := effectiveAccess(e.App, actor)
	independent := actor.GetString("kind") != botKind && actor.GetString("owner") == ""
	broad := acc.all && acc.rw
	if e.Record.GetString("kind") != botKind {
		if !independent || e.Record.GetString("owner") != "" || !(isWorkspaceAdmin(actor) || broad) {
			return router.NewForbiddenError("an independent workspace administrator or legacy full person must provision people", nil)
		}
		e.Record.Set("created_by", "")
		return nil
	}
	owner := actor.Id
	if actor.GetString("kind") == botKind {
		owner = actor.GetString("owner")
	}
	// Preserve the domain refusal for an unowned bot trying to own its
	// worker. This lookup is only of the current actor itself, so it cannot
	// disclose another member while refusing a departed owner relationship.
	if owner == "" && actor.GetString("kind") == botKind && e.Record.GetString("owner") == actor.Id {
		if err := checkOwner(e.App, e.Record); err != nil {
			return err
		}
	}
	if owner == "" || e.Record.GetString("owner") != owner || !(acc.hasWrite() || isWorkspaceAdmin(actor)) {
		return router.NewForbiddenError("current authority does not allow provisioning this owned bot", nil)
	}
	creator := ""
	if actor.GetString("kind") == botKind {
		creator = actor.Id
	}
	e.Record.Set("created_by", creator)
	return nil
}
