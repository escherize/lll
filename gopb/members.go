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
// would have if it knew about ownership. Superuser-only is not enough:
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
		bot, err := re.App.FindFirstRecordByFilter(
			"members", "name = {:name} && kind = 'bot'",
			dbx.Params{"name": body.Name},
		)
		if err != nil {
			return re.BadRequestError("no bot member by that name", nil)
		}
		if !re.HasSuperuserAuth() {
			if re.Auth == nil || re.Auth.Id != bot.GetString("owner") {
				return re.ForbiddenError("only the bot's owner or a superuser can rotate its token", nil)
			}
		}
		// RefreshTokenKey sets an autogenerate modifier: the new key is
		// written on save, which is what strands the old tokens. The fresh
		// token is minted from a re-read so it signs with the persisted key.
		bot.RefreshTokenKey()
		if err := re.App.Save(bot); err != nil {
			return re.InternalServerError("failed to invalidate the previous token", err)
		}
		fresh, err := re.App.FindRecordById("members", bot.Id)
		if err != nil {
			return re.InternalServerError("failed to reload the bot after rotation", err)
		}
		token, err := fresh.NewStaticAuthToken(time.Duration(body.Duration) * time.Second)
		if err != nil {
			return re.InternalServerError("failed to generate the rotated token", err)
		}
		return re.JSON(200, map[string]any{"token": token, "record": fresh})
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))
}
