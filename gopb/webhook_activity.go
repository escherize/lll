package gopb

import (
	"encoding/json"
	"github.com/pocketbase/pocketbase/core"
	"slices"
)

// Shared webhook payloads have no viewer credential. Only expand a member
// when every reader of this team may see it, and strip other team ids.
func webhookMember(app core.App, id, team string) *core.Record {
	if id == "" {
		return nil
	}
	member, err := app.FindRecordById("members", id)
	if err != nil || !onTeamRoster(member, team) {
		return nil
	}
	member = member.Clone()
	member.Set("teams", slices.DeleteFunc(slices.Clone(member.GetStringSlice("teams")), func(t string) bool { return t != team }))
	return member
}

func webhookActivityPayload(app core.App, topic, action string, record, issue *core.Record) ([]byte, error) {
	clone := record.Clone()
	actor, agent, source := record.GetString("event_actor"), record.GetString("event_agent"), record.GetString("event_source")
	relation := "event_actor"
	if topic == "comments" {
		actor, agent, source = record.GetString("author"), record.GetString("agent"), record.GetString("author_kind")
		relation = "author"
	}
	expand := map[string]any{"issue": webhookIssue(app, issue)}
	name, kind := "", ""
	if source == "system" || source == "superuser" {
		kind, name = source, source
	} else if actor != "" {
		name = "hidden member"
		if member := webhookMember(app, actor, issue.GetString("team")); member != nil {
			expand[relation] = member
			name, kind = member.GetString("name"), member.GetString("kind")
		}
	}
	// Keep the holder separate from the releaser on claim events.
	if topic == "claims" {
		if holder := webhookMember(app, record.GetString("member"), issue.GetString("team")); holder != nil {
			expand["member"] = holder
		}
	}
	clone.SetExpand(expand)
	key := ""
	if team, err := app.FindRecordById("teams", issue.GetString("team")); err == nil {
		key = team.GetString("key") + "-" + issue.GetString("number")
	}
	return json.Marshal(map[string]any{
		"topic": topic, "action": action, "record": clone, "key": key,
		"author": actor, "author_name": name, "author_kind": kind, "agent": agent,
	})
}
