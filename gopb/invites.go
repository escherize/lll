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
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
	"github.com/pocketbase/pocketbase/tools/types"
)

// Single-use invite links (LLL-544; doc scoped-access-invites). The invites
// collection is superuser-only (1791810544_invites.js); these two routes are
// the only way in or out.
//
//   - POST /api/lll/invites mints one. The caller's effective access bounds
//     what it may grant: every team must be one it sees, and only a
//     read-write caller may mint at all ("an invite can only grant teams and
//     modes its creator holds").
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

// mayInvite is false for a bot or any member with an owner. A person
// joined through an invite has no owner, so nothing would keep it within
// the owner's access: narrowing or deleting the owner, or rotating a leaked
// bot token, would leave the people it invited untouched.
func mayInvite(creator *core.Record) bool {
	return creator.GetString("kind") != botKind && creator.GetString("owner") == ""
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
	err := app.RunInTransaction(func(tx core.App) error {
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
				return re.ForbiddenError("bots and owned members cannot invite people: run 'lll invite create' with your own token", nil)
			}
			acc = effectiveAccess(re.App, creator)
			if !acc.rw {
				return re.ForbiddenError("read-only access: "+creator.GetString("name")+" cannot invite anyone. 'lll whoami' shows your access; ask the person who invited you for read-write", nil)
			}
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

// registerMemberNameGuard holds every non-superuser RENAME to the rule a
// redeemer gets (joinName, at most 40 characters, unique regardless of
// case), so the anti-impersonation rule cannot be undone after joining: a
// member may PATCH its own name (1791700000_bot_owner_scope.js). A person
// may not take the bot- prefix; a bot keeps it (checkMemberKind). Only a
// name that changes is checked, so a member whose name predates the rule
// can still edit its other fields. Superusers are not held to it.
//
// Creates are not checked: only a full member or a superuser creates a
// person, and 'lll member add -n "Tim O'Brien"' is supported (e2e.sh).
func registerMemberNameGuard(app core.App) {
	app.OnRecordUpdateRequest("members").BindFunc(func(e *core.RecordRequestEvent) error {
		if e.HasSuperuserAuth() || e.Record.GetString("name") == e.Record.Original().GetString("name") {
			return e.Next()
		}
		name := e.Record.GetString("name")
		if e.Record.GetString("kind") != botKind && strings.HasPrefix(strings.ToLower(name), botPrefix) {
			return e.BadRequestError(errNameBot.Error(), nil)
		}
		if len(name) > 40 || !joinName.MatchString(name) {
			return e.BadRequestError(errNameInvalid.Error(), nil)
		}
		taken, err := nameTaken(e.App, name, e.Record.Id)
		if err != nil {
			return err
		}
		if taken {
			return e.BadRequestError("the name '"+name+"' is taken on this board: pick another", nil)
		}
		return e.Next()
	})
}
