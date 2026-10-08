package gopb

import (
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"net/http"
	"regexp"
	"slices"
	"strings"
	"time"

	"github.com/pocketbase/dbx"
	validation "github.com/pocketbase/ozzo-validation/v4"
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
	"github.com/pocketbase/pocketbase/tools/types"
)

// Single-use invite links (LLL-544; doc scoped-access-invites). The invites
// collection is superuser-only (1791810544_invites.js); these two routes are
// the only way in or out.
//
//   - POST /api/lll/invites mints one. Only a superuser or a full member (a
//     person with read-write access to every team) may mint (mayInvite,
//     LLL-629). The grant is still checked against the caller's access.
//   - POST /api/lll/invites/redeem spends one. It needs no auth: the code is
//     the credential, and the visitor has nothing else yet. One transaction
//     kills the code and creates the person member; the member's token comes
//     back only after it commits.

const (
	inviteLifetime = 7 * 24 * time.Hour
	// The board cookie's lifetime (doc: "a joined human's board cookie lasts
	// 1 year"). The token is static: nothing renews it.
	joinedTokenLifetime = 365 * 24 * time.Hour
	// 32 bytes from crypto/rand, base64url without padding: 256 bits.
	inviteCodeBytes = 32
	inviteCodeLen   = 43
	maxInviteTeams  = 50
)

// The refusals a redeemer can get. Each names the fix, because the person
// reading it has no other way to learn what to do.
var (
	errInviteUnknown = errors.New("this invite link is not valid. Check that you opened the whole link; if it still fails, ask whoever invited you for a new link")
	errInviteUsed    = errors.New("this invite link has already been used: each link lets one person join. Ask whoever invited you for a new link")
	errInviteExpired = errors.New("this invite link has expired: links last 7 days. Ask whoever invited you for a new link")
	errInviteVoid    = errors.New("this invite link no longer grants anything: its teams are gone, or whoever made it no longer has the access it grants. Ask them for a new link")
	errNameInvalid   = errors.New("pick a name of up to 40 letters and digits, with single spaces, dots, dashes or underscores between them")
	errNameBot       = errors.New("names starting with 'bot-' are reserved for bot members: pick another name")
)

// joinName is the only thing a redeemer chooses. ASCII only, and one
// separator at a time between letters or digits, so a name cannot imitate
// another member's with look-alike characters, doubled spaces (which HTML
// collapses) or trailing punctuation.
var joinName = regexp.MustCompile(`^[A-Za-z0-9]+([ ._-][A-Za-z0-9]+)*$`)

// newInviteCode is a fresh code and the hash stored for it.
func newInviteCode() (code, hash string, err error) {
	b := make([]byte, inviteCodeBytes)
	if _, err := rand.Read(b); err != nil {
		return "", "", err
	}
	code = base64.RawURLEncoding.EncodeToString(b)
	return code, inviteCodeHash(code), nil
}

// inviteCodeHash is what the database keeps instead of the code. Lookup is
// by this hash through a unique index: the comparison runs on a value the
// caller cannot steer, so its timing says nothing about stored codes.
func inviteCodeHash(code string) string {
	sum := sha256.Sum256([]byte(code))
	return hex.EncodeToString(sum[:])
}

// wellFormedCode reports whether code could be one newInviteCode made.
func wellFormedCode(code string) bool {
	if len(code) != inviteCodeLen {
		return false
	}
	b, err := base64.RawURLEncoding.DecodeString(code)
	return err == nil && len(b) == inviteCodeBytes
}

// inviteGrant is what an invite gives: always a team list, never "all".
type inviteGrant struct {
	teams []string
	rw    bool
}

// mayInvite is true only for a full member: a person with no owner and
// read-write access to every team (LLL-629). A person joined through an
// invite is independent of whoever invited it, so deleting or narrowing the
// inviter does not reach it. Minting is therefore a way to outlive a
// revocation: a scoped guest about to be removed could redeem its own
// invites as extra members. Bots and owned members are refused for the same
// reason: the people they invited would escape their owner's narrowing.
// Redemption asks again, so narrowing a full member voids its unredeemed
// invites.
func mayInvite(creator *core.Record) bool {
	own := ownAccess(creator)
	return creator.GetString("kind") != botKind && creator.GetString("owner") == "" && own.all && own.rw
}

// mayNotInvite is the refusal for a caller mayInvite rejects. It names who
// can mint, so the caller knows whom to ask.
func mayNotInvite(name string) string {
	return "only a person with read-write access to every team, or a superuser, can create invites; " + name +
		" cannot. Ask one of them to run 'lll invite create'; 'lll whoami' shows your access"
}

// grantAllowed reports whether a creator with access acc may grant g.
// A read-only creator may grant nothing: creating a member is a write.
func grantAllowed(acc access, g inviteGrant) bool {
	if !acc.rw || len(g.teams) == 0 {
		return false
	}
	for _, team := range g.teams {
		if !acc.sees(team) {
			return false
		}
	}
	return true
}

// createInvite stores an invite for g, made by creator (nil for a
// superuser), and returns its code. The caller has checked grantAllowed.
func createInvite(app core.App, creator *core.Record, g inviteGrant, now time.Time) (string, *core.Record, error) {
	collection, err := app.FindCollectionByNameOrId("invites")
	if err != nil {
		return "", nil, err
	}
	code, hash, err := newInviteCode()
	if err != nil {
		return "", nil, err
	}
	invite := core.NewRecord(collection)
	invite.Set("code_hash", hash)
	invite.Set("teams", g.teams)
	invite.Set("mode", modeName(g.rw))
	invite.Set("expires", now.Add(inviteLifetime))
	if creator == nil {
		invite.Set("superuser", true)
	} else {
		invite.Set("creator", creator.Id)
	}
	if err := app.Save(invite); err != nil {
		return "", nil, err
	}
	return code, invite, nil
}

func modeName(rw bool) string {
	if rw {
		return "rw"
	}
	return "ro"
}

// redeemInvite spends the invite for code and creates the person member
// named name with exactly the invite's grants. Either both happen or
// neither: a refused name leaves the code alive.
func redeemInvite(app core.App, code, name string, now time.Time) (*core.Record, error) {
	name = strings.TrimSpace(name)
	if strings.HasPrefix(strings.ToLower(name), botPrefix) {
		return nil, errNameBot
	}
	if len(name) > 40 || !joinName.MatchString(name) {
		return nil, errNameInvalid
	}
	if !wellFormedCode(code) {
		return nil, errInviteUnknown
	}
	var member *core.Record
	unlock, err := lockNameWrites()
	if err != nil {
		return nil, err
	}
	defer unlock()
	err = app.RunInTransaction(func(tx core.App) error {
		invite, err := tx.FindFirstRecordByData("invites", "code_hash", inviteCodeHash(code))
		if errors.Is(err, sql.ErrNoRows) {
			return errInviteUnknown
		}
		if err != nil {
			return err
		}
		if !invite.GetDateTime("redeemed").IsZero() {
			return errInviteUsed
		}
		if !now.Before(invite.GetDateTime("expires").Time()) {
			return errInviteExpired
		}
		grant := inviteGrant{teams: invite.GetStringSlice("teams"), rw: invite.GetString("mode") == "rw"}
		if !invite.GetBool("superuser") {
			// The creator's access is read again now: narrowing or deleting
			// the creator voids what it handed out and nobody redeemed yet.
			creator, err := tx.FindRecordById("members", invite.GetString("creator"))
			if err != nil || !mayInvite(creator) || !grantAllowed(effectiveAccess(tx, creator), grant) {
				return errInviteVoid
			}
		} else if len(grant.teams) == 0 {
			return errInviteVoid
		}
		// Kill the code first, conditionally. Transactions are serialized on
		// PocketBase's single writer connection already; this makes the
		// single use hold without relying on that.
		res, err := tx.DB().NewQuery("UPDATE invites SET redeemed = {:now} WHERE id = {:id} AND (redeemed = '' OR redeemed IS NULL)").
			Bind(dbx.Params{"now": types.NowDateTime().String(), "id": invite.Id}).Execute()
		if err != nil {
			return err
		}
		if n, _ := res.RowsAffected(); n != 1 {
			return errInviteUsed
		}
		taken, err := nameTaken(tx, name, "")
		if err != nil {
			return err
		}
		if taken {
			return nameTakenError(name)
		}
		member, err = newJoinedMember(tx, name, grant)
		if nameClash(err) {
			// A rename or create committed between the check above and
			// this save; idx_members_name_nocase refused it. Returning an
			// error rolls back the kill, so the code stays alive.
			return nameTakenError(name)
		}
		if err != nil {
			return err
		}
		_, err = tx.DB().NewQuery("UPDATE invites SET redeemed_by = {:member} WHERE id = {:id}").
			Bind(dbx.Params{"member": member.Id, "id": invite.Id}).Execute()
		return err
	})
	if err != nil {
		return nil, err
	}
	return member, nil
}

// nameTaken compares without case: "Bryan" must not join beside "bryan".
// exceptID is the member being renamed ("" for a new one), so changing
// only the case of one's own name is not a collision.
func nameTaken(app core.App, name, exceptID string) (bool, error) {
	var found []struct {
		Id string `db:"id"`
	}
	err := app.DB().NewQuery("SELECT id FROM members WHERE LOWER(name) = LOWER({:name}) AND id != {:id} LIMIT 1").
		Bind(dbx.Params{"name": name, "id": exceptID}).All(&found)
	return len(found) > 0, err
}

// nameClash reports whether err is a members name uniqueness violation, as
// PocketBase normalizes it (validators.NormalizeUniqueIndexError).
func nameClash(err error) bool {
	var fields validation.Errors
	if !errors.As(err, &fields) {
		return false
	}
	_, ok := fields["name"]
	return ok
}

func nameTakenError(name string) error {
	return router.NewBadRequestError("the name '"+name+"' is taken on this board: pick another. Your invite link still works", nil)
}

// newJoinedMember saves the person member a redemption creates. Everything
// but the name is fixed here: kind, scope, teams, mode, no owner, and an
// email and password nobody knows (the member signs in by the board cookie;
// a lost cookie means a new invite, per the design doc).
func newJoinedMember(app core.App, name string, g inviteGrant) (*core.Record, error) {
	collection, err := app.FindCollectionByNameOrId("members")
	if err != nil {
		return nil, err
	}
	tag := make([]byte, 12)
	if _, err := rand.Read(tag); err != nil {
		return nil, err
	}
	m := core.NewRecord(collection)
	m.Set("name", name)
	m.SetEmail("joined-" + hex.EncodeToString(tag) + "@members.invalid")
	m.SetRandomPassword()
	m.Set("kind", "person")
	m.Set("owner", "")
	setAccess(m, access{teams: g.teams, rw: g.rw})
	if err := app.Save(m); err != nil {
		return nil, err
	}
	return m, nil
}

// inviteTeamIDs dedupes the requested team ids and checks each exists and
// is one acc sees. A team the caller cannot see gets the answer a missing
// one gets, so the refusal does not confirm it exists.
func inviteTeamIDs(app core.App, acc access, ids []string) ([]string, error) {
	var out []string
	for _, id := range ids {
		if slices.Contains(out, id) {
			continue
		}
		if _, err := app.FindRecordById("teams", id); err != nil || !acc.sees(id) {
			return nil, router.NewBadRequestError("no team with id '"+id+"' that you can see: 'lll team list' shows yours", nil)
		}
		out = append(out, id)
	}
	if len(out) == 0 || len(out) > maxInviteTeams {
		return nil, router.NewBadRequestError("an invite names 1 to 50 teams", nil)
	}
	return out, nil
}

func registerInviteRoutes(routes *router.Router[*core.RequestEvent]) {
	routes.POST("/api/lll/invites", func(re *core.RequestEvent) error {
		var body struct {
			Teams []string `json:"teams"`
			Mode  string   `json:"mode"`
		}
		re.Request.Body = http.MaxBytesReader(re.Response, re.Request.Body, 8192)
		if err := re.BindBody(&body); err != nil {
			return re.BadRequestError("send {\"teams\": [team ids], \"mode\": \"ro\" or \"rw\"}", nil)
		}
		if body.Mode != "ro" && body.Mode != "rw" {
			return re.BadRequestError("mode must be \"ro\" or \"rw\"", nil)
		}
		var creator *core.Record
		acc := access{all: true, rw: true}
		if !re.HasSuperuserAuth() {
			creator = re.Auth
			if !mayInvite(creator) {
				return re.ForbiddenError(mayNotInvite(creator.GetString("name")), nil)
			}
			acc = effectiveAccess(re.App, creator)
		}
		teams, err := inviteTeamIDs(re.App, acc, body.Teams)
		if err != nil {
			return err
		}
		grant := inviteGrant{teams: teams, rw: body.Mode == "rw"}
		if !grantAllowed(acc, grant) {
			return re.ForbiddenError("an invite cannot grant more than you hold", nil)
		}
		code, invite, err := createInvite(re.App, creator, grant, time.Now())
		if err != nil {
			return re.InternalServerError("failed to save the invite", err)
		}
		return re.JSON(http.StatusOK, map[string]any{
			"code":    code,
			"teams":   teams,
			"mode":    body.Mode,
			"expires": invite.GetDateTime("expires"),
		})
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))

	routes.POST("/api/lll/invites/redeem", func(re *core.RequestEvent) error {
		var body struct {
			Code string `json:"code"`
			Name string `json:"name"`
		}
		re.Request.Body = http.MaxBytesReader(re.Response, re.Request.Body, 2048)
		if err := re.BindBody(&body); err != nil {
			return re.BadRequestError("send {\"code\": ..., \"name\": ...}", nil)
		}
		member, err := redeemInvite(re.App, body.Code, body.Name, time.Now())
		var apiErr *router.ApiError
		switch {
		case err == nil:
		case errors.Is(err, errInviteUnknown):
			return re.NotFoundError(err.Error(), nil)
		case errors.Is(err, errInviteUsed), errors.Is(err, errInviteExpired), errors.Is(err, errInviteVoid):
			return re.Error(http.StatusGone, err.Error(), nil)
		case errors.Is(err, errNameWriteBusy):
			return re.Error(http.StatusServiceUnavailable, err.Error(), nil)
		case errors.Is(err, errNameInvalid), errors.Is(err, errNameBot):
			return re.BadRequestError(err.Error(), nil)
		case errors.As(err, &apiErr):
			return apiErr
		default:
			return re.InternalServerError("failed to redeem the invite", err)
		}
		token, err := member.NewStaticAuthToken(joinedTokenLifetime)
		if err != nil {
			return re.InternalServerError("the member was created but its token was not; ask whoever invited you to run 'lll token create "+member.GetString("name")+"'", err)
		}
		keys := []string{}
		for _, id := range member.GetStringSlice("teams") {
			if team, err := re.App.FindRecordById("teams", id); err == nil {
				keys = append(keys, team.GetString("key"))
			}
		}
		return re.JSON(http.StatusOK, map[string]any{
			"token": token,
			"name":  member.GetString("name"),
			"teams": keys,
			"mode":  member.GetString("mode"),
		})
	})
}

// registerMemberNameGuard holds a non-superuser's name choices to the rule
// a redeemer gets (joinName, at most 40 characters, unique regardless of
// case), so an invited member cannot impersonate anyone in attribution:
//
//   - a rename, because a member may PATCH its own name
//     (1791700000_bot_owner_scope.js). Only a name that changes is checked,
//     so a member whose name predates the rule can still edit other fields.
//   - the create of a bot, because a scoped read-write member (an invited
//     one included) may create a bot it owns. 'bot-NAME' passes the rule.
//
// A person may not take the bot- prefix; a bot keeps it (checkMemberKind).
// Superusers are not held to it, and person creates are not checked: only a
// full member or a superuser creates a person, and
// 'lll member add -n "Tim O'Brien"' is supported (e2e.sh).
func registerMemberNameGuard(app core.App) {
	app.OnRecordUpdateRequest("members").BindFunc(func(e *core.RecordRequestEvent) error {
		if e.HasSuperuserAuth() || e.Record.GetString("name") == e.Record.Original().GetString("name") {
			return e.Next()
		}
		return checkedNameWrite(e)
	})
	app.OnRecordCreateRequest("members").BindFunc(func(e *core.RecordRequestEvent) error {
		if e.HasSuperuserAuth() || e.Record.GetString("kind") != botKind {
			return e.Next()
		}
		return checkedNameWrite(e)
	})
}

// nameWrites serializes every checked member-name write in this process -
// renames, bot creates and redemptions - across its check and its save.
// Without it two writes can both pass the check before either saves. The
// case-folded unique index (idx_members_name_nocase) also refuses that,
// but a board holding older case pairs has no index yet, and there the
// lock is the only thing that keeps a new pair from forming (which would
// keep ensureNameIndex from ever adding it).
//
// It is a one-slot channel, not a sync.Mutex, so every wait is bounded
// (lockNameWrites). And no holder can nest a second checked write: the
// holder's e.Next() is one record save, and the only way PocketBase nests
// request handling - /api/batch, where sub-request i+1 runs inside sub-
// request i's e.Next() - is refused before the lock is taken
// (checkedNameWrite). Redemption takes the lock outside any request chain.
var nameWrites = make(chan struct{}, 1)

const nameWriteWait = 5 * time.Second

var errNameWriteBusy = errors.New("the board is busy saving another member's name: try again in a moment")

// lockNameWrites takes nameWrites, waiting at most nameWriteWait. The
// returned func releases it.
func lockNameWrites() (func(), error) {
	select {
	case nameWrites <- struct{}{}:
		return func() { <-nameWrites }, nil
	case <-time.After(nameWriteWait):
		return nil, errNameWriteBusy
	}
}

// checkedNameWrite checks e's name and saves it under nameWrites. A batch
// sub-request is refused: it runs inside the previous sub-request's save,
// so a second checked write in one batch would wait on the lock its own
// batch holds (the Batch API is off by default and lll never enables it;
// the pocketbase skill says to keep it off).
func checkedNameWrite(e *core.RecordRequestEvent) error {
	if info, err := e.RequestInfo(); err != nil || info.Context == core.RequestInfoContextBatch {
		return e.BadRequestError("member names cannot be set in a batch request: send each create or rename on its own", nil)
	}
	unlock, err := lockNameWrites()
	if err != nil {
		return e.Error(http.StatusServiceUnavailable, err.Error(), nil)
	}
	defer unlock()
	if err := checkChosenName(e.App, e.Record); err != nil {
		return err
	}
	return e.Next()
}

// checkChosenName applies the join name rule to m's name.
func checkChosenName(app core.App, m *core.Record) error {
	name := m.GetString("name")
	if m.GetString("kind") != botKind && strings.HasPrefix(strings.ToLower(name), botPrefix) {
		return router.NewBadRequestError(errNameBot.Error(), nil)
	}
	if len(name) > 40 || !joinName.MatchString(name) {
		return router.NewBadRequestError(errNameInvalid.Error(), nil)
	}
	taken, err := nameTaken(app, name, m.Id)
	if err != nil {
		return err
	}
	if taken {
		return router.NewBadRequestError("the name '"+name+"' is taken on this board: pick another", nil)
	}
	return nil
}
