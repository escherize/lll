package gopb

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"sync"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

type teamRole uint8

const (
	noTeamAccess teamRole = iota
	teamViewer
	teamEditor
)

func parseTeamRole(value string) (teamRole, error) {
	switch value {
	case "none":
		return noTeamAccess, nil
	case "viewer":
		return teamViewer, nil
	case "editor":
		return teamEditor, nil
	}
	return noTeamAccess, router.NewBadRequestError("team role must be none, viewer or editor", nil)
}
func roleOf(a access, team string) string {
	if a.writes(team) {
		return "editor"
	}
	if a.sees(team) {
		return "viewer"
	}
	return "none"
}

type permissionTeam struct {
	ID        string `json:"id"`
	Key       string `json:"key"`
	Name      string `json:"name"`
	Role      string `json:"role"`
	Effective string `json:"effective"`
}
type permissionMember struct {
	ID               string           `json:"id"`
	Name             string           `json:"name"`
	Kind             string           `json:"kind"`
	Owner            string           `json:"owner"`
	CreatedBy        string           `json:"created_by"`
	WorkspaceRole    string           `json:"workspace_role"`
	All              bool             `json:"all"`
	LegacyManagement bool             `json:"legacy_management"`
	DefaultRole      string           `json:"default_role"`
	Teams            []permissionTeam `json:"teams"`
	Revision         string           `json:"revision"`
}
type permissionPlan struct {
	Before               permissionMember `json:"before"`
	After                permissionMember `json:"after"`
	FutureTeamAccessLost bool             `json:"future_team_access_lost"`
	LegacyManagementLost bool             `json:"legacy_management_lost"`
	EventID              string           `json:"event_id,omitempty"`
	Applied              bool             `json:"applied"`
}

func permissionSnapshot(app core.App, member *core.Record) (permissionMember, error) {
	own, eff := ownAccess(member), effectiveAccess(app, member)
	out := permissionMember{ID: member.Id, Name: member.GetString("name"), Kind: member.GetString("kind"), Owner: member.GetString("owner"), CreatedBy: member.GetString("created_by"), WorkspaceRole: member.GetString("workspace_role"), All: own.all, DefaultRole: "none", Teams: []permissionTeam{}}
	if out.WorkspaceRole == "" {
		out.WorkspaceRole = "member"
	}
	out.LegacyManagement = eff.all && eff.rw
	if own.all {
		out.DefaultRole = "viewer"
		if own.rw {
			out.DefaultRole = "editor"
		}
	}
	teams, err := app.FindRecordsByFilter("teams", "", "key", 0, 0)
	if err != nil {
		return out, err
	}
	for _, team := range teams {
		out.Teams = append(out.Teams, permissionTeam{team.Id, team.GetString("key"), team.GetString("name"), roleOf(own, team.Id), roleOf(eff, team.Id)})
	}
	encoded, err := json.Marshal(out)
	if err != nil {
		return out, err
	}
	sum := sha256.Sum256(encoded)
	out.Revision = hex.EncodeToString(sum[:])
	return out, nil
}

// permissionManager is transaction-bound administration evidence. It confers
// grant/roster management only; it cannot read team content through this API.
type permissionManager struct{ scope *permissionScope }
type permissionScope struct {
	mu     sync.Mutex
	active bool
	app    core.App
	actor  *core.Record
}

func withPermissionManager[T any](re *core.RequestEvent, run func(permissionManager) (T, error)) (T, error) {
	var out T
	err := re.App.RunInTransaction(func(tx core.App) error {
		actor, err := lifecycleCaller(tx, re.Auth)
		if err != nil {
			return err
		}
		if !actor.IsSuperuser() && !isWorkspaceAdmin(actor) {
			return router.NewForbiddenError("workspace administrator required; broad team access alone does not grant this role", nil)
		}
		scope := &permissionScope{active: true, app: tx, actor: actor}
		defer func() { scope.mu.Lock(); scope.active = false; scope.mu.Unlock() }()
		out, err = run(permissionManager{scope})
		return err
	})
	return out, err
}
func usePermissionManager[T any](manager permissionManager, run func(*permissionScope) (T, error)) (T, error) {
	var out T
	if manager.scope == nil {
		return out, errClosedIssueAuthority
	}
	s := manager.scope
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.active {
		return out, errClosedIssueAuthority
	}
	return run(s)
}
func (m permissionManager) index() ([]permissionMember, error) {
	return usePermissionManager(m, func(s *permissionScope) ([]permissionMember, error) {
		members, err := s.app.FindRecordsByFilter("members", "", "name", 0, 0)
		if err != nil {
			return nil, err
		}
		out := []permissionMember{}
		for _, member := range members {
			row, err := permissionSnapshot(s.app, member)
			if err != nil {
				return nil, err
			}
			out = append(out, row)
		}
		return out, nil
	})
}
func (m permissionManager) snapshot(id string) (permissionMember, error) {
	return usePermissionManager(m, func(s *permissionScope) (permissionMember, error) {
		member, err := s.app.FindRecordById("members", id)
		if err != nil {
			return permissionMember{}, router.NewNotFoundError("member not found", nil)
		}
		return permissionSnapshot(s.app, member)
	})
}

// Wire strings are parsed into this closed operation before a writable target
// can exist. A writableMembership fixes both the member and the desired grant;
// execute accepts no separate member id, role string or database connection.
type permissionChange struct {
	revision      string
	team          string
	role          teamRole
	workspaceRole *string
	convertAll    bool
}
type permissionBody struct {
	Revision      string  `json:"revision"`
	Team          string  `json:"team"`
	Role          string  `json:"role"`
	WorkspaceRole *string `json:"workspace_role"`
	ConvertAll    bool    `json:"convert_all_teams"`
	Preview       bool    `json:"preview"`
}

func parsePermissionBody(re *core.RequestEvent) (permissionChange, bool, error) {
	re.Request.Body = http.MaxBytesReader(re.Response, re.Request.Body, 8192)
	decoder := json.NewDecoder(re.Request.Body)
	decoder.DisallowUnknownFields()
	var body permissionBody
	if err := decoder.Decode(&body); err != nil {
		return permissionChange{}, false, re.BadRequestError("send a revision and one team-role or workspace-role change", nil)
	}
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		return permissionChange{}, false, re.BadRequestError("send exactly one permission change", nil)
	}
	if raw, err := hex.DecodeString(body.Revision); err != nil || len(raw) != 32 {
		return permissionChange{}, false, re.BadRequestError("read the current permission revision before changing access", nil)
	}
	change := permissionChange{revision: body.Revision, team: body.Team, workspaceRole: body.WorkspaceRole, convertAll: body.ConvertAll}
	if body.WorkspaceRole != nil {
		if body.Team != "" || body.Role != "" || body.ConvertAll || (*body.WorkspaceRole != "member" && *body.WorkspaceRole != "admin") {
			return change, false, re.BadRequestError("choose either one team role or workspace role member/admin", nil)
		}
	} else {
		role, err := parseTeamRole(body.Role)
		if err != nil {
			return change, false, err
		}
		if body.Team == "" {
			return change, false, re.BadRequestError("a team id is required", nil)
		}
		change.role = role
	}
	return change, body.Preview, nil
}

type writableMembership struct {
	manager       permissionManager
	member        *core.Record
	next          access
	workspaceRole string
	plan          permissionPlan
	used          bool
	updateAccess  bool
}

func (manager permissionManager) prepare(id string, change permissionChange) (*writableMembership, error) {
	return usePermissionManager(manager, func(s *permissionScope) (*writableMembership, error) {
		member, err := s.app.FindRecordById("members", id)
		if err != nil {
			return nil, router.NewNotFoundError("member not found", nil)
		}
		before, err := permissionSnapshot(s.app, member)
		if err != nil {
			return nil, err
		}
		if before.Revision != change.revision {
			return nil, router.NewApiError(http.StatusConflict, "permissions changed; read and preview again", nil)
		}
		next := ownAccess(member)
		updateAccess := false
		workspaceRole := before.WorkspaceRole
		if change.workspaceRole != nil {
			workspaceRole = *change.workspaceRole
			if workspaceRole == "admin" && (member.GetString("kind") != "person" || member.GetString("owner") != "") {
				return nil, router.NewBadRequestError("only an independent person can be a workspace administrator", nil)
			}
			if workspaceRole == "member" && before.WorkspaceRole == "admin" && !s.actor.IsSuperuser() {
				others, err := s.app.FindRecordsByFilter("members", `workspace_role = 'admin' && kind = 'person' && owner = '' && id != {:id}`, "", 1, 0, dbx.Params{"id": member.Id})
				if err != nil {
					return nil, err
				}
				if len(others) == 0 {
					return nil, router.NewApiError(http.StatusConflict, "promote another administrator before removing the last administrator", nil)
				}
			}
		} else {
			if _, err := s.app.FindRecordById("teams", change.team); err != nil {
				return nil, router.NewBadRequestError("team not found", nil)
			}
			wanted := []string{"none", "viewer", "editor"}[change.role]
			if roleOf(next, change.team) != wanted {
				if next.all && !change.convertAll {
					return nil, withCode(router.NewBadRequestError("this replaces an all-current-and-future-team grant; preview with convert_all_teams and confirm that future-team coverage is lost", nil), "confirm_all_team_conversion")
				}
				readable, editors := []string{}, []string{}
				for _, team := range before.Teams {
					role := team.Role
					if team.ID == change.team {
						role = wanted
					}
					if role != "none" {
						readable = append(readable, team.ID)
					}
					if role == "editor" {
						editors = append(editors, team.ID)
					}
				}
				next = access{teams: readable, editors: editors}
				updateAccess = true
			}
		}
		planned := core.NewRecord(member.Collection())
		planned.Load(member.PublicExport())
		planned.Id = member.Id
		if updateAccess {
			setAccess(planned, next)
		}
		planned.Set("workspace_role", workspaceRole)
		if err := checkOwner(s.app, planned); err != nil {
			return nil, err
		}
		after, err := permissionSnapshot(s.app, planned)
		if err != nil {
			return nil, err
		}
		return &writableMembership{manager: manager, member: member, next: next, workspaceRole: workspaceRole, updateAccess: updateAccess, plan: permissionPlan{Before: before, After: after, FutureTeamAccessLost: before.All && !next.all, LegacyManagementLost: before.LegacyManagement && !after.LegacyManagement}}, nil
	})
}
func (proof *writableMembership) execute(preview bool) (permissionPlan, error) {
	if proof == nil {
		return permissionPlan{}, errClosedIssueAuthority
	}
	return usePermissionManager(proof.manager, func(s *permissionScope) (permissionPlan, error) {
		if proof.used {
			return permissionPlan{}, errClosedIssueAuthority
		}
		if preview {
			return proof.plan, nil
		}
		proof.used = true
		// A transaction can apply one administrative mutation through this manager.
		// All prepared/copy values share this lease; one cannot reuse an earlier
		// proof after a self-demotion or another grant change in the same callback.
		s.active = false
		if proof.updateAccess {
			setAccess(proof.member, proof.next)
		}
		proof.member.Set("workspace_role", proof.workspaceRole)
		stampPermissionActor(proof.member, s.actor)
		if err := s.app.Save(proof.member); err != nil {
			return permissionPlan{}, err
		}
		after, err := permissionSnapshot(s.app, proof.member)
		if err != nil {
			return permissionPlan{}, err
		}
		out := proof.plan
		out.After = after
		out.EventID = proof.member.GetString(permissionEventKey)
		out.Applied = true
		return out, nil
	})
}

func registerPermissionRoutes(routes *router.Router[*core.RequestEvent]) {
	routes.GET("/api/lll/permissions/support", func(re *core.RequestEvent) error {
		return re.JSON(http.StatusOK, map[string]any{"supported": true, "version": 2})
	})
	routes.GET("/api/lll/permissions", func(re *core.RequestEvent) error {
		rows, err := withPermissionManager(re, func(manager permissionManager) ([]permissionMember, error) { return manager.index() })
		if err != nil {
			return err
		}
		return re.JSON(http.StatusOK, map[string]any{"members": rows})
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))
	routes.GET("/api/lll/permissions/{member}", func(re *core.RequestEvent) error {
		row, err := withPermissionManager(re, func(manager permissionManager) (permissionMember, error) {
			return manager.snapshot(re.Request.PathValue("member"))
		})
		if err != nil {
			return err
		}
		return re.JSON(http.StatusOK, row)
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))
	routes.POST("/api/lll/permissions/{member}", func(re *core.RequestEvent) error {
		change, preview, err := parsePermissionBody(re)
		if err != nil {
			return err
		}
		plan, err := withPermissionManager(re, func(manager permissionManager) (permissionPlan, error) {
			target, err := manager.prepare(re.Request.PathValue("member"), change)
			if err != nil {
				return permissionPlan{}, err
			}
			return target.execute(preview)
		})
		if err != nil {
			return err
		}
		return re.JSON(http.StatusOK, plan)
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))
}
