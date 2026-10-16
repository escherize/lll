package gopb

import (
	"net/http"
	"strings"
	"time"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

// Bot members (LLL-407, after Vikunja's bot users) are automation identities:
// kind "bot", owned by the human member who created them, token-only. The
// guarantees below live server-side because every CLI rule has a curl
// workaround: the reserved prefix, the dead password door, and the owner
// check on rotation are all enforced where the database is.
const (
	botKind   = "bot"
	botPrefix = "bot-"
)

// registerMemberGuards binds the bot-member policy to members writes and to
// password auth. Create and update (not the Request variants) so direct
// saves, seeding and superuser calls all pass the same check; the auth hook
// is password-auth-only, so impersonation - the bot credential path - is
// untouched.
func registerMemberGuards(app core.App) {
	app.OnRecordCreate("members").BindFunc(func(e *core.RecordEvent) error {
		if err := checkMemberKind(e.Record, true); err != nil {
			return err
		}
		return e.Next()
	})
	app.OnRecordUpdate("members").BindFunc(func(e *core.RecordEvent) error {
		if err := checkMemberKind(e.Record, false); err != nil {
			return err
		}
		return e.Next()
	})
	// Which bot created a bot is the server's word (LLL-709), like an
	// issue's creator (provenance.go): a bot's create records the bot, and a
	// person's records nobody. A bot with no owner records nobody either, so
	// checkOwner refuses it exactly as before: a bot cannot own a bot. The
	// rules refuse created_by in a member's body; this overwrite is the
	// second lock. checkCreator then holds the new bot to its creator's owner
	// and access. A superuser names one or not.
	app.OnRecordCreateRequest("members").BindFunc(func(e *core.RecordRequestEvent) error {
		if isMember(e) {
			createdBy := ""
			if e.Auth.GetString("kind") == botKind && e.Auth.GetString("owner") != "" && e.Record.GetString("kind") == botKind {
				createdBy = e.Auth.Id
			}
			e.Record.Set("created_by", createdBy)
		}
		return e.Next()
	})
	app.OnRecordAuthWithPasswordRequest("members").BindFunc(func(e *core.RecordAuthWithPasswordRequestEvent) error {
		// Fires after the identity lookup and before the password check, so
		// the refusal names the account kind instead of grading a password a
		// bot must never have.
		if e.Record != nil && e.Record.GetString("kind") == botKind {
			return e.ForbiddenError(
				"bot members cannot sign in with a password - they are token-only accounts; use the minted LLL_TOKEN (see 'lll bot')",
				nil,
			)
		}
		return e.Next()
	})
}

// registerMemberUpdateTx runs a member update through the records API in
// one transaction (LLL-709 review F5, LLL-713). PocketBase saves outside
// one, and reads outside the write, so keepCommitted's re-read of the
// stored row could itself be stale by the time the row is written. In a
// transaction the read and the write hold the one write connection
// together.
//
// Register it after registerMemberNameGuard (review F6): the name lock
// (nameWrites) is always taken before the write connection, by a rename,
// a bot create and a redemption alike. Holding the transaction while a
// rename waited for the name lock, against a bot create holding the name
// lock while it waited for the connection, stalled every write for the
// lock's 5s timeout.
func registerMemberUpdateTx(app core.App) {
	app.OnRecordUpdateRequest("members").BindFunc(func(e *core.RecordRequestEvent) error {
		return e.App.RunInTransaction(func(tx core.App) error {
			e.App = tx
			return e.Next()
		})
	})
}

// checkMemberKind enforces the reserved bot- prefix, in both directions:
//
//   - a bot member must carry the prefix, on create and on update, so the
//     badge and the attribution stay trustworthy;
//   - a non-bot signup must not take the prefix. Create only: members named
//     bot-* that predate the kind field exist on hosted boards as ordinary
//     members, and an update-time rule would refuse their next profile edit.
func checkMemberKind(record *core.Record, creating bool) error {
	name := record.GetString("name")
	isBot := record.GetString("kind") == botKind
	if isBot && !strings.HasPrefix(name, botPrefix) {
		return router.NewBadRequestError(
			"bot member names are reserved to the '"+botPrefix+"' prefix - got '"+name+"'; see 'lll bot'",
			nil,
		)
	}
	if !isBot && creating && strings.HasPrefix(name, botPrefix) {
		return router.NewBadRequestError(
			"the '"+botPrefix+"' name prefix is reserved for bot members - create one with 'lll bot "+name+"', or pick another name",
			nil,
		)
	}
	return nil
}

// registerBotRoutes adds the bot token lifecycle: rotation re-mints the
// bot's static token and invalidates every earlier one (PocketBase signs
// tokens with the record's tokenKey, so refreshing it kills the old
// credentials at the next request).
//
// Authorization is superuser or the bot's owner - the same rule impersonate
// would have if it knew about ownership - or the bot that created it. Superuser-only is not enough:
// the human who created the bot is the one who saw a token leak.
func registerBotRoutes(routes *router.Router[*core.RequestEvent]) {
	routes.POST("/api/lll/bots/rotate", func(re *core.RequestEvent) error {
		var body struct {
			Name     string `json:"name"`
			Duration int64  `json:"duration"`
		}
		re.Request.Body = http.MaxBytesReader(re.Response, re.Request.Body, 2048)
		if err := re.BindBody(&body); err != nil || body.Name == "" {
			return re.BadRequestError("rotate requires the bot member's name", nil)
		}
		if body.Duration < 0 {
			return re.BadRequestError("duration must be 0 or more", nil)
		}
		token, fresh, err := rotateBot(re.App, re.Auth, re.HasSuperuserAuth(), body.Name, body.Duration)
		if err != nil {
			return err
		}
		return re.JSON(200, map[string]any{"token": token, "record": fresh})
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))
}

// rotateBot authorizes auth to rotate the bot named name, refreshes its
// token key and mints a token from the persisted record. Errors are
// *router.ApiError, ready to return from the route.
//
// One transaction, reading the caller and the bot inside it (LLL-709
// review F1): auth is the record the request authenticated with, read
// before a concurrent revocation or narrowing may have committed, and Save
// writes every column, so a stale copy would overwrite a committed detach
// or narrowing and mint a token for it.
func rotateBot(app core.App, auth *core.Record, superuser bool, name string, duration int64) (string, *core.Record, error) {
	var token string
	var fresh *core.Record
	err := app.RunInTransaction(func(tx core.App) error {
		caller := auth
		if auth != nil && !auth.IsSuperuser() {
			reread, err := tx.FindRecordById("members", auth.Id)
			if err != nil {
				return router.NewUnauthorizedError("the token's member no longer exists", nil)
			}
			caller = reread
		}
		var err error
		token, fresh, err = rotateBotIn(tx, caller, superuser, name, duration)
		return err
	})
	if err != nil {
		return "", nil, err
	}
	return token, fresh, nil
}

func rotateBotIn(app core.App, auth *core.Record, superuser bool, name string, duration int64) (string, *core.Record, error) {
	bot, err := app.FindFirstRecordByFilter(
		"members", "name = {:name} && kind = 'bot'",
		dbx.Params{"name": name},
	)
	if err != nil {
		return "", nil, router.NewBadRequestError("no bot member by that name", nil)
	}
	// The bot that created this one (LLL-709) mints its token too: it
	// needs the first one to hand to its worker, and it already holds
	// every token it minted. Never past its own access right now.
	// Only while the creator still shares the bot's human owner: a
	// creator re-owned or left without an owner rotates nothing.
	createdByCaller := auth != nil && bot.GetString("created_by") != "" && auth.Id == bot.GetString("created_by") &&
		auth.GetString("owner") != "" && auth.GetString("owner") == bot.GetString("owner")
	if createdByCaller && !effectiveAccess(app, auth).rw {
		return "", nil, router.NewForbiddenError("a read-only bot cannot rotate the bots it created; ask their owner", nil)
	}
	if createdByCaller && !effectiveAccess(app, auth).covers(effectiveAccess(app, bot)) {
		return "", nil, router.NewForbiddenError("this bot has wider access than you; ask an admin to narrow it, or rotate it with superuser credentials", nil)
	}
	if !superuser && !createdByCaller {
		if auth == nil || auth.Id != bot.GetString("owner") {
			// A bot outside the caller's roster answers like a missing
			// one, so the refusal does not confirm a hidden name (LLL-551).
			if auth == nil || !rosterSees(app, auth, bot) {
				return "", nil, router.NewBadRequestError("no bot member by that name", nil)
			}
			return "", nil, router.NewForbiddenError("only the bot's owner or a superuser can rotate its token", nil)
		}
		// A fresh token for a bot wider than its owner would hand the
		// owner access it no longer has (narrowed after minting the bot).
		if !accessCovers(auth, bot) {
			return "", nil, router.NewForbiddenError("this bot has wider access than you; ask an admin to narrow it, or rotate it with superuser credentials", nil)
		}
	}
	// RefreshTokenKey sets an autogenerate modifier: the new key is
	// written on save, which is what strands the old tokens. The fresh
	// token is minted from a re-read so it signs with the persisted key.
	bot.RefreshTokenKey()
	if err := app.Save(bot); err != nil {
		return "", nil, router.NewInternalServerError("failed to invalidate the previous token", err)
	}
	fresh, err := app.FindRecordById("members", bot.Id)
	if err != nil {
		return "", nil, router.NewInternalServerError("failed to reload the bot after rotation", err)
	}
	token, err := fresh.NewStaticAuthToken(time.Duration(duration) * time.Second)
	if err != nil {
		return "", nil, router.NewInternalServerError("failed to generate the rotated token", err)
	}
	return token, fresh, nil
}
