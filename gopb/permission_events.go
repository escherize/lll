package gopb

import (
	"errors"

	"github.com/pocketbase/pocketbase/core"
)

const permissionActorKey = "@lll_permission_actor"
const permissionEventKey = "@lll_permission_event"

var permissionFields = []string{"scope", "teams", "mode", "editor_teams", "workspace_role", "owner", "created_by", "kind"}

type permissionActor struct{ ID, Kind string }

func isWorkspaceAdmin(m *core.Record) bool {
	return m != nil && m.GetString("workspace_role") == "admin" && m.GetString("kind") == "person" && m.GetString("owner") == ""
}
func stampPermissionActor(record, actor *core.Record) {
	kind := "person"
	if actor.IsSuperuser() {
		kind = "superuser"
	} else if actor.GetString("kind") == botKind {
		kind = "bot"
	}
	record.Set(permissionActorKey, permissionActor{actor.Id, kind})
}

func registerPermissionEvents(app core.App) {
	stamp := func(e *core.RecordRequestEvent) error {
		actor, err := lifecycleCaller(e.App, e.Auth)
		if err != nil {
			return err
		}
		stampPermissionActor(e.Record, actor)
		// Explicit administrators provision new people without a data grant.
		if e.Record.IsNew() && isWorkspaceAdmin(actor) && e.Record.GetString("kind") == "person" {
			info, err := e.RequestInfo()
			if err != nil {
				return err
			}
			if _, sent := info.Body["scope"]; !sent {
				setAccess(e.Record, access{})
			}
		}
		return e.Next()
	}
	app.OnRecordCreateRequest("members").BindFunc(stamp)
	app.OnRecordUpdateRequest("members").BindFunc(stamp)
	write := func(e *core.RecordEvent) error {
		if e.Record.Collection().Fields.GetByName("workspace_role") == nil {
			return e.Next()
		}
		original := e.App
		defer func() { e.App = original }()
		return original.RunInTransaction(func(tx core.App) error {
			e.App = tx

			changes := map[string]fieldChange{}
			var before *core.Record
			if !e.Record.IsNew() {
				var err error
				before, err = tx.FindRecordById("members", e.Record.Id)
				if err != nil {
					return err
				}
			}
			for _, field := range permissionFields {
				var from any
				if before != nil {
					from = before.Get(field)
				}
				to := e.Record.Get(field)
				if canonical(from) != canonical(to) {
					changes[field] = fieldChange{From: from, To: to}
				}
			}
			if err := e.Next(); err != nil {
				return err
			}
			if len(changes) == 0 {
				return nil
			}
			collection, err := tx.FindCollectionByNameOrId("permission_events")
			if err != nil {
				return err
			}
			actor, _ := e.Record.GetRaw(permissionActorKey).(permissionActor)
			if actor.Kind == "" {
				actor.Kind = "system"
			}
			event := core.NewRecord(collection)
			event.Set("member", e.Record.Id)
			event.Set("actor", actor.ID)
			event.Set("actor_kind", actor.Kind)
			event.Set("changes", changes)
			if err := tx.Save(event); err != nil {
				return err
			}
			e.Record.Set(permissionEventKey, event.Id)
			return nil
		})
	}
	app.OnRecordCreateExecute("members").BindFunc(write)
	app.OnRecordUpdateExecute("members").BindFunc(write)
	app.OnRecordCreateRequest("permission_events").BindFunc(func(e *core.RecordRequestEvent) error {
		return e.ForbiddenError("permission events are written by the server", nil)
	})
	app.OnRecordUpdate("permission_events").BindFunc(func(e *core.RecordEvent) error { return errors.New("permission events are append-only") })
}
