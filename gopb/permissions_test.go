package gopb

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

func newPermissionFixture(t *testing.T) (creatorFixture, *core.RequestEvent) {
	t.Helper()
	f := newCreatorFixture(t)
	teams, err := f.app.FindCollectionByNameOrId("teams")
	if err != nil {
		t.Fatal(err)
	}
	f.members.Fields.Add(&core.SelectField{Name: "workspace_role", Values: []string{"member", "admin"}, MaxSelect: 1}, &core.RelationField{Name: "editor_teams", CollectionId: teams.Id, MaxSelect: 999})
	if err = f.app.Save(f.members); err != nil {
		t.Fatal(err)
	}
	events := core.NewBaseCollection("permission_events")
	events.Fields.Add(&core.TextField{Name: "member"}, &core.TextField{Name: "actor"}, &core.TextField{Name: "actor_kind"}, &core.JSONField{Name: "changes", MaxSize: 1 << 20})
	if err = f.app.Save(events); err != nil {
		t.Fatal(err)
	}
	registerPermissionEvents(f.app)
	admin := f.reload(t, f.human)
	setAccess(admin, access{})
	admin.Set("workspace_role", "admin")
	if err = f.app.Save(admin); err != nil {
		t.Fatal(err)
	}
	re := &core.RequestEvent{App: f.app, Auth: admin}
	re.Request = httptest.NewRequest("POST", "/", nil)
	return f, re
}
func permissionEventCount(t *testing.T, app core.App) int {
	t.Helper()
	rows, err := app.FindAllRecords("permission_events")
	if err != nil {
		t.Fatal(err)
	}
	return len(rows)
}

func TestAdministrativeProofDoesNotFollowBroadDataAccess(t *testing.T) {
	f, re := newPermissionFixture(t)
	re.Auth = f.other
	called := false
	_, err := withPermissionManager(re, func(manager permissionManager) ([]permissionMember, error) { called = true; return manager.index() })
	var api *router.ApiError
	if !errors.As(err, &api) || api.Status != http.StatusForbidden || called {
		t.Fatalf("broad data grant became administration: %v", err)
	}
	var empty permissionManager
	if _, err = empty.index(); !errors.Is(err, errClosedIssueAuthority) {
		t.Fatalf("zero manager: %v", err)
	}
}

func TestAdministrativeProofAndPreparedTargetsExpireTogether(t *testing.T) {
	f, re := newPermissionFixture(t)
	var escaped permissionManager
	var target *writableMembership
	before := permissionEventCount(t, f.app)
	_, err := withPermissionManager(re, func(manager permissionManager) (permissionPlan, error) {
		escaped = manager
		snapshot, err := manager.snapshot(f.other.Id)
		if err != nil {
			return permissionPlan{}, err
		}
		target, err = manager.prepare(f.other.Id, permissionChange{revision: snapshot.Revision, team: f.alpha, role: teamViewer, convertAll: true})
		if err != nil {
			return permissionPlan{}, err
		}
		return target.execute(true)
	})
	if err != nil {
		t.Fatal(err)
	}
	if permissionEventCount(t, f.app) != before {
		t.Fatal("preview wrote permission history")
	}
	if !ownAccess(f.reload(t, f.other)).all {
		t.Fatal("preview changed the target grant")
	}
	if _, err = escaped.index(); !errors.Is(err, errClosedIssueAuthority) {
		t.Fatalf("escaped manager: %v", err)
	}
	if _, err = target.execute(false); !errors.Is(err, errClosedIssueAuthority) {
		t.Fatalf("escaped target: %v", err)
	}
}

func TestApplyingOneAdministrativeProofInvalidatesItsCopies(t *testing.T) {
	f, re := newPermissionFixture(t)
	role := "admin"
	_, err := withPermissionManager(re, func(manager permissionManager) (permissionPlan, error) {
		snapshot, err := manager.snapshot(f.other.Id)
		if err != nil {
			return permissionPlan{}, err
		}
		target, err := manager.prepare(f.other.Id, permissionChange{revision: snapshot.Revision, workspaceRole: &role})
		if err != nil {
			return permissionPlan{}, err
		}
		copied := *target
		applied, err := target.execute(false)
		if err != nil {
			return permissionPlan{}, err
		}
		if _, err = copied.execute(false); !errors.Is(err, errClosedIssueAuthority) {
			t.Fatalf("copied proof remained usable: %v", err)
		}
		return applied, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if !isWorkspaceAdmin(f.reload(t, f.other)) {
		t.Fatal("authorized role change did not commit")
	}
}

func TestAdministrativeProofUsesCurrentRoleAndCredential(t *testing.T) {
	for _, change := range []string{"demoted", "retired"} {
		t.Run(change, func(t *testing.T) {
			f, re := newPermissionFixture(t)
			current := f.reload(t, re.Auth)
			want := http.StatusForbidden
			if change == "demoted" {
				current.Set("workspace_role", "member")
			} else {
				current.RefreshTokenKey()
				want = http.StatusUnauthorized
			}
			if err := f.app.Save(current); err != nil {
				t.Fatal(err)
			}
			called := false
			_, err := withPermissionManager(re, func(manager permissionManager) ([]permissionMember, error) { called = true; return manager.index() })
			var api *router.ApiError
			if !errors.As(err, &api) || api.Status != want || called {
				t.Fatalf("stale actor obtained administrative proof: %v", err)
			}
		})
	}
}

func TestStaleProfileSaveDoesNotInventPermissionEvents(t *testing.T) {
	f, _ := newPermissionFixture(t)
	stale := f.reload(t, f.other)
	changed := f.reload(t, f.other)
	setAccess(changed, access{teams: []string{f.alpha}, editors: []string{f.alpha}})
	if err := f.app.Save(changed); err != nil {
		t.Fatal(err)
	}
	before := permissionEventCount(t, f.app)
	stale.Set("name", "renamed-person")
	if err := f.app.Save(stale); err != nil {
		t.Fatal(err)
	}
	if permissionEventCount(t, f.app) != before {
		t.Fatal("stale profile falsely attributed a previously committed grant change")
	}
	current := ownAccess(f.reload(t, f.other))
	if current.all || !current.writes(f.alpha) || current.sees(f.beta) {
		t.Fatal("stale profile restored a broader grant")
	}
}

func TestPermissionChangeRollsBackWhenItsAuditCannotBeSaved(t *testing.T) {
	f, re := newPermissionFixture(t)
	failure := errors.New("permission audit unavailable")
	f.app.OnRecordCreate("permission_events").BindFunc(func(*core.RecordEvent) error { return failure })
	_, err := withPermissionManager(re, func(manager permissionManager) (permissionPlan, error) {
		snapshot, err := manager.snapshot(f.other.Id)
		if err != nil {
			return permissionPlan{}, err
		}
		target, err := manager.prepare(f.other.Id, permissionChange{revision: snapshot.Revision, team: f.alpha, role: teamViewer, convertAll: true})
		if err != nil {
			return permissionPlan{}, err
		}
		return target.execute(false)
	})
	if err == nil {
		t.Fatal("grant committed without its audit event")
	}
	current := ownAccess(f.reload(t, f.other))
	if !current.all || !current.rw {
		t.Fatal("failed audit left a partial permission mutation")
	}
}

func TestExplicitWildcardConversionPreservesUnchangedCurrentRoles(t *testing.T) {
	for _, role := range []teamRole{teamViewer, teamEditor} {
		t.Run([]string{"none", "viewer", "editor"}[role], func(t *testing.T) {
			f, re := newPermissionFixture(t)
			f.other.Set("mode", modeName(role == teamEditor))
			if err := f.app.Save(f.other); err != nil {
				t.Fatal(err)
			}
			before := permissionEventCount(t, f.app)
			preview, err := withPermissionManager(re, func(manager permissionManager) (permissionPlan, error) {
				snapshot, err := manager.snapshot(f.other.Id)
				if err != nil {
					return permissionPlan{}, err
				}
				proof, err := manager.prepare(f.other.Id, permissionChange{revision: snapshot.Revision, team: f.alpha, role: role, convertAll: true})
				if err != nil {
					return permissionPlan{}, err
				}
				return proof.execute(true)
			})
			if err != nil {
				t.Fatal(err)
			}
			if preview.After.All || !preview.FutureTeamAccessLost || preview.LegacyManagementLost != (role == teamEditor) || preview.Before.Revision == preview.After.Revision {
				t.Fatal("explicit conversion ignored when the selected role stayed the same")
			}
			if permissionEventCount(t, f.app) != before || !ownAccess(f.reload(t, f.other)).all {
				t.Fatal("conversion preview wrote")
			}
			for i, team := range preview.Before.Teams {
				if preview.After.Teams[i].Role != team.Role {
					t.Fatal("current role changed during conversion")
				}
			}
		})
	}
}

func TestWorkspaceAdministrationDoesNotTakeAnotherPersonsBot(t *testing.T) {
	f, re := newPermissionFixture(t)
	bot := f.save(t, "bot-other-owner", botKind, f.other.Id, "", nil)
	err := lifecycleAuthority(f.app, re.Auth, bot)
	var api *router.ApiError
	if !errors.As(err, &api) || (api.Status != http.StatusForbidden && api.Status != http.StatusNotFound) {
		t.Fatalf("Admin acquired another person's bot lifecycle: %v", err)
	}
	if token, _, err := rotateBot(f.app, re.Auth, bot.GetString("name"), 3600); err == nil || token != "" {
		t.Fatal("Admin acquired another person's bot credential")
	}
	if f.reload(t, bot).TokenKey() != bot.TokenKey() {
		t.Fatal("refused Admin rotation retired the owner's credential")
	}
	if err := lifecycleAuthority(f.app, f.other, bot); err != nil {
		t.Fatalf("owner control refused: %v", err)
	}
	token, _, err := rotateBot(f.app, f.other, bot.GetString("name"), 3600)
	if err != nil || !f.tokenWorks(token) {
		t.Fatalf("owner rotation control failed: %v", err)
	}
}
