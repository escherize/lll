package gopb

import "github.com/pocketbase/pocketbase/core"

// The actor is not necessarily the holder: forced releases must identify the
// releasing session, expiry the system, and a direct admin write the admin.
// For deletion these schema fields are set on the event's record without an
// extra Save, so no spurious renewal is emitted. PocketBase's realtime Fresh
// copy keeps schema fields but drops unknown custom data.
func claimEventActor(record *core.Record, member, agent, source string) {
	record.Set("event_actor", member)
	record.Set("event_agent", agent)
	record.Set("event_source", source)
}

func claimEventBy(record *core.Record, by releaser) {
	source := "member"
	if by.memberID == "" {
		source = "superuser"
	}
	claimEventActor(record, by.memberID, by.agent, source)
}

// Raw claim writes are superuser-only. Discard submitted attribution even
// there: these fields describe the authenticated writer, not request data.
func registerClaimEventActors(app core.App) {
	stamp := func(e *core.RecordRequestEvent) error {
		member, source := "", ""
		if e.Auth != nil {
			if e.Auth.Collection().Name == "members" {
				member, source = e.Auth.Id, "member"
			} else if e.HasSuperuserAuth() {
				source = "superuser"
			}
		}
		claimEventActor(e.Record, member, "", source)
		return e.Next()
	}
	app.OnRecordCreateRequest("claims").BindFunc(stamp)
	app.OnRecordUpdateRequest("claims").BindFunc(stamp)
	app.OnRecordDeleteRequest("claims").BindFunc(stamp)
}
