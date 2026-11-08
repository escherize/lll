package gopb

import (
	"database/sql"
	"errors"
	"net/http"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

// Generic member writes/deletes remain administrator-only. These routes can
// only narrow or remove a bot belonging to the authenticated owner.
func registerBotLifecycle(routes *router.Router[*core.RequestEvent]) {
	routes.GET("/api/lll/bots/lifecycle", func(re *core.RequestEvent) error {
		return re.JSON(http.StatusOK, map[string]bool{"supported": true})
	})
	routes.GET("/api/lll/bots/owned", func(re *core.RequestEvent) error {
		caller, err := lifecycleCaller(re.App, re.Auth)
		if err != nil {
			return err
		}
		name := re.Request.URL.Query().Get("name")
		if name == "" {
			return re.BadRequestError("the bot name is required", nil)
		}
		bot, err := re.App.FindFirstRecordByFilter("members", "name = {:name} && kind = 'bot'", dbx.Params{"name": name})
		if errors.Is(err, sql.ErrNoRows) {
			return missingLifecycleBot()
		}
		if err != nil {
			return re.InternalServerError("could not read the bot", err)
		}
		if err := lifecycleAuthority(re.App, caller, bot); err != nil {
			return err
		}
		referenced, err := botHasReferences(re.App, bot)
		if err != nil {
			return re.InternalServerError("could not check the bot's references", err)
		}
		return re.JSON(http.StatusOK, map[string]any{"id": bot.Id, "name": bot.GetString("name"), "has_references": referenced})
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))
	for _, action := range []string{"disable", "remove"} {
		routes.POST("/api/lll/bots/"+action, func(re *core.RequestEvent) error {
			var body struct {
				ID    string `json:"id"`
				Name  string `json:"name"`
				Force bool   `json:"force"`
			}
			re.Request.Body = http.MaxBytesReader(re.Response, re.Request.Body, 2048)
			if err := re.BindBody(&body); err != nil || body.ID == "" || body.Name == "" {
				return re.BadRequestError("lifecycle actions require the bot id and name from its owned lookup", nil)
			}
			result, err := manageOwnedBot(re.App, re.Auth, body.ID, body.Name, action, body.Force)
			if err != nil {
				return err
			}
			return re.JSON(http.StatusOK, result)
		}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))
	}
}

func missingLifecycleBot() error {
	return router.NewNotFoundError("no bot member by that name", nil)
}

// Re-read the authenticated account inside the writer transaction. A queued
// request must not retain an old ownership grant or a retired credential.
func lifecycleCaller(app core.App, auth *core.Record) (*core.Record, error) {
	if auth == nil || (auth.Collection().Name != "members" && !auth.IsSuperuser()) {
		return nil, router.NewUnauthorizedError("a member or administrator token is required", nil)
	}
	fresh, err := app.FindRecordById(auth.Collection(), auth.Id)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, router.NewUnauthorizedError("the token's account no longer exists", nil)
	}
	if err != nil {
		return nil, router.NewInternalServerError("could not read the acting account", err)
	}
	if fresh.TokenKey() != auth.TokenKey() {
		return nil, router.NewUnauthorizedError("the credential was retired; sign in again", nil)
	}
	return fresh, nil
}

func lifecycleAuthority(app core.App, caller, bot *core.Record) error {
	if bot.GetString("kind") != botKind {
		return missingLifecycleBot()
	}
	if caller.IsSuperuser() || bot.GetString("owner") == caller.Id {
		return nil
	}
	if !rosterSees(app, caller, bot) {
		return missingLifecycleBot()
	}
	return router.NewForbiddenError("only the bot's owner or an administrator can disable or remove it", nil)
}

// Use PocketBase's relation metadata, including future relation fields. An
// existence query is enough; no history content or hidden-team counts leave
// the server, and the execute path checks again under the writer lock.
func botHasReferences(app core.App, bot *core.Record) (bool, error) {
	collections, err := app.FindCollectionReferences(bot.Collection())
	if err != nil {
		return false, err
	}
	for collection, fields := range collections {
		for _, field := range fields {
			relation, ok := field.(*core.RelationField)
			if !ok {
				return false, errors.New("unexpected relation metadata")
			}
			operator := "="
			path := field.GetName()
			if relation.MaxSelect > 1 {
				operator = "?="
				// A direct multi-relation value is its JSON array. Resolve
				// ids before applying exact any-match membership.
				path += ".id"
			}
			rows, err := app.FindRecordsByFilter(collection, path+" "+operator+" {:member}", "", 1, 0, dbx.Params{"member": bot.Id})
			if err != nil {
				return false, err
			}
			if len(rows) > 0 {
				return true, nil
			}
		}
	}
	return false, nil
}

func manageOwnedBot(app core.App, auth *core.Record, id, name, action string, force bool) (map[string]any, error) {
	var result map[string]any
	err := app.RunInTransaction(func(tx core.App) error {
		caller, err := lifecycleCaller(tx, auth)
		if err != nil {
			return err
		}
		bot, err := tx.FindRecordById("members", id)
		if errors.Is(err, sql.ErrNoRows) {
			return missingLifecycleBot()
		}
		if err != nil {
			return router.NewInternalServerError("could not read the bot", err)
		}
		if err := lifecycleAuthority(tx, caller, bot); err != nil {
			return err
		}
		if bot.GetString("name") != name {
			return router.NewApiError(http.StatusConflict, "the bot changed since it was read; look it up again", nil)
		}
		if action == "disable" {
			setAccess(bot, access{all: false, rw: false, teams: []string{}})
			bot.RefreshTokenKey()
			if err := tx.Save(bot); err != nil {
				return router.NewInternalServerError("could not disable the bot", err)
			}
			result = map[string]any{"id": bot.Id, "name": name, "disabled": true}
			return nil
		}
		if action != "remove" {
			return router.NewBadRequestError("unknown bot lifecycle action", nil)
		}
		referenced, err := botHasReferences(tx, bot)
		if err != nil {
			return router.NewInternalServerError("could not check the bot's references", err)
		}
		if referenced && !force {
			return router.NewApiError(http.StatusConflict, "the bot has references; disable it to keep attribution, or explicitly force removal to clear its references", nil)
		}
		if err := tx.Delete(bot); err != nil {
			return router.NewInternalServerError("could not remove the bot", err)
		}
		result = map[string]any{"id": id, "name": name, "removed": true, "had_references": referenced}
		return nil
	})
	return result, err
}
