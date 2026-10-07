package gopb

import (
	"crypto/rand"
	"crypto/sha256"
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
	errNameInvalid   = errors.New("pick a name of 1 to 40 letters, digits, spaces, dots, dashes or underscores, starting with a letter or digit")
	errNameBot       = errors.New("names starting with 'bot-' are reserved for bot members: pick another name")
)

// joinName is the only thing a redeemer chooses. ASCII only, so a name
// cannot imitate another member's with look-alike characters.
var joinName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}$`)

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
	if !joinName.MatchString(name) {
		return nil, errNameInvalid
	}
	if !wellFormedCode(code) {
		return nil, errInviteUnknown
	}
	var member *core.Record
	err := app.RunInTransaction(func(tx core.App) error {
		invite, err := tx.FindFirstRecordByData("invites", "code_hash", inviteCodeHash(code))
		if err != nil {
			return errInviteUnknown
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
			if err != nil || !grantAllowed(effectiveAccess(tx, creator), grant) {
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
		taken, err := nameTaken(tx, name)
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
func nameTaken(app core.App, name string) (bool, error) {
	var found []struct {
		Id string `db:"id"`
	}
	err := app.DB().NewQuery("SELECT id FROM members WHERE LOWER(name) = LOWER({:name}) LIMIT 1").
		Bind(dbx.Params{"name": name}).All(&found)
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
