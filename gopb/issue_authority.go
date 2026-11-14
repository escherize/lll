package gopb

import (
	"errors"
	"sync"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

var errClosedIssueAuthority = errors.New("issue write authority is outside its transaction")

// writableIssue is evidence for this actor, this resource and this transaction.
// It exposes operations, not a record/id or a privileged database handle. It is
// deliberately not a bearer credential or a serializable grant. Construction
// lives in withWritableIssue, after acquiring the route's issue lock.
// Go cannot express GDP's generative scope statically: copies share the lease,
// which closes before the transaction commits. The zero value has no authority.
type writableIssue struct{ scope *issueWriteScope }
type issueWriteScope struct {
	mu      sync.Mutex
	active  bool
	app     core.App
	actor   *core.Record
	issueID string
}

// withWritableIssue parses current authorization inside the database writer.
// The proof and all mutations share that transaction, so committed revocation,
// token retirement, owner narrowing and archive state cannot be missed while a
// route was waiting on its issue lock. Errors escape before the HTTP response.
func withWritableIssue[T any](re *core.RequestEvent, write func(writableIssue) (T, error)) (T, error) {
	var out T
	err := re.App.RunInTransaction(func(tx core.App) error {
		actor, err := lifecycleCaller(tx, re.Auth)
		if err != nil {
			return err
		}
		issue, err := tx.FindRecordById("issues", re.Request.PathValue("issue"))
		if err != nil {
			return router.NewNotFoundError("", nil)
		}
		acc := effectiveAccess(tx, actor)
		team := issue.GetString("team")
		if !acc.sees(team) {
			return router.NewNotFoundError("", nil)
		}
		if !acc.writes(team) {
			return router.NewForbiddenError(readOnlyRefusal(actor), nil)
		}
		if err := archivedRefusal(tx, actor, team); err != nil {
			return err
		}
		scope := &issueWriteScope{active: true, app: tx, actor: actor, issueID: issue.Id}
		defer func() { scope.mu.Lock(); scope.active = false; scope.mu.Unlock() }()
		out, err = write(writableIssue{scope: scope})
		return err
	})
	return out, err
}

func useIssueWrite[T any](proof writableIssue, write func(*issueWriteScope) (T, error)) (T, error) {
	var empty T
	if proof.scope == nil {
		return empty, errClosedIssueAuthority
	}
	scope := proof.scope
	scope.mu.Lock()
	defer scope.mu.Unlock()
	if !scope.active {
		return empty, errClosedIssueAuthority
	}
	return write(scope)
}

func (proof writableIssue) assign(expected string, fields assignmentFields, by releaser, keep bool) (ClaimOutcome, error) {
	return useIssueWrite(proof, func(s *issueWriteScope) (ClaimOutcome, error) {
		if err := fields.refsInScope(&core.RequestEvent{App: s.app, Auth: s.actor}); err != nil {
			return ClaimOutcome{}, err
		}
		return updateAssignment(s.app, s.issueID, expected, fields, s.stamp(by), keep)
	})
}
func (proof writableIssue) claim(member, agent string, by releaser) (ClaimOutcome, error) {
	return useIssueWrite(proof, func(s *issueWriteScope) (ClaimOutcome, error) {
		if !s.actor.IsSuperuser() && member != s.actor.Id {
			return ClaimOutcome{}, router.NewForbiddenError("claim member must match the authenticated member", nil)
		}
		return acquireClaim(s.app, s.issueID, member, agent, s.stamp(by))
	})
}
func (proof writableIssue) release(expected string, by releaser) (ClaimOutcome, error) {
	return useIssueWrite(proof, func(s *issueWriteScope) (ClaimOutcome, error) {
		return releaseClaim(s.app, s.issueID, expected, s.stamp(by))
	})
}
func (proof writableIssue) close(expected string, by releaser, keep bool) (ClaimOutcome, error) {
	return useIssueWrite(proof, func(s *issueWriteScope) (ClaimOutcome, error) {
		return closeIssue(s.app, s.issueID, expected, s.stamp(by), keep)
	})
}
func (proof writableIssue) renew(expected string, by releaser) (ClaimOutcome, error) {
	return useIssueWrite(proof, func(s *issueWriteScope) (ClaimOutcome, error) {
		return renewClaim(s.app, s.issueID, expected, s.stamp(by))
	})
}

func (proof writableIssue) appendReference(reference string, by releaser) (referenceOutcome, error) {
	return useIssueWrite(proof, func(s *issueWriteScope) (referenceOutcome, error) {
		return appendReference(s.app, s.issueID, reference, s.stamp(by))
	})
}

// Attribution comes from the proven actor. Agent labels and forced-operation
// explanations remain request context; they do not identify the member.
func (s *issueWriteScope) stamp(by releaser) releaser {
	by.memberID = ""
	if !s.actor.IsSuperuser() {
		by.memberID = s.actor.Id
	}
	return by
}
