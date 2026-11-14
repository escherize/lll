package gopb

import (
	"errors"
	"sync"
	"time"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/types"
)

var errClosedInviteAuthority = errors.New("invite issuance authority is outside its transaction or already consumed")

type issuedInvite struct {
	code    string
	teams   []string
	expires types.DateTime
}
type writableInvite struct{ scope *inviteIssueScope }
type inviteIssueScope struct {
	mu      sync.Mutex
	active  bool
	app     core.App
	creator *core.Record
	grant   inviteGrant
}

// Parse the entire issuance command and current grant-management authority
// under one writer. The value can mint only this grant as this issuer; it
// exposes neither a general-purpose app nor a separately supplied creator.
func withWritableInvite(re *core.RequestEvent, ids []string, mode string, write func(writableInvite) (issuedInvite, error)) (issuedInvite, error) {
	var out issuedInvite
	err := re.App.RunInTransaction(func(tx core.App) error {
		actor, err := lifecycleCaller(tx, re.Auth)
		if err != nil {
			return err
		}
		if mode != "ro" && mode != "rw" {
			return re.BadRequestError("mode must be \"ro\" or \"rw\"", nil)
		}
		var creator *core.Record
		acc := access{all: true, rw: true}
		if !actor.IsSuperuser() {
			creator = actor
			if !mayInvite(creator) {
				return re.ForbiddenError(mayNotInvite(creator.GetString("name")), nil)
			}
			acc = inviteAuthority(tx, creator)
		}
		teams, err := inviteTeamIDs(tx, acc, ids)
		if err != nil {
			return err
		}
		grant := inviteGrant{teams: teams, rw: mode == "rw"}
		if !grantAllowed(acc, grant) {
			return re.ForbiddenError("an invite cannot grant more than you hold", nil)
		}
		scope := &inviteIssueScope{active: true, app: tx, creator: creator, grant: grant}
		defer func() { scope.mu.Lock(); scope.active = false; scope.mu.Unlock() }()
		out, err = write(writableInvite{scope: scope})
		return err
	})
	return out, err
}
func (proof writableInvite) mint() (issuedInvite, error) {
	if proof.scope == nil {
		return issuedInvite{}, errClosedInviteAuthority
	}
	s := proof.scope
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.active {
		return issuedInvite{}, errClosedInviteAuthority
	}
	s.active = false
	code, record, err := createInvite(s.app, s.creator, s.grant, time.Now())
	if err != nil {
		return issuedInvite{}, err
	}
	return issuedInvite{code: code, teams: record.GetStringSlice("teams"), expires: record.GetDateTime("expires")}, nil
}
