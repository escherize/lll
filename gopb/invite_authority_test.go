package gopb

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
)

func TestInviteUnionPreservesEveryUnrelatedAndFutureRole(t *testing.T) {
	universe := []string{"a", "b", "c", "future"}
	ids := func(mask int) []string {
		var out []string
		for i, id := range universe[:3] {
			if mask&(1<<i) != 0 {
				out = append(out, id)
			}
		}
		return out
	}
	for _, all := range []bool{false, true} {
		for _, rw := range []bool{false, true} {
			for read := 0; read < 8; read++ {
				for editors := 0; editors < 8; editors++ {
					for invited := 1; invited < 8; invited++ {
						for _, write := range []bool{false, true} {
							before := access{all: all, rw: rw, teams: ids(read), editors: ids(editors)}
							grant := inviteGrant{teams: ids(invited), rw: write}
							out := mergeInviteAccess(before, grant)
							if out.all != before.all {
								t.Fatal("finite invite changed future coverage")
							}
							for _, id := range universe {
								sees := before.sees(id) || slices.Contains(grant.teams, id)
								writes := before.writes(id) || (grant.rw && slices.Contains(grant.teams, id))
								if out.sees(id) != sees || out.writes(id) != writes {
									t.Fatalf("before=%+v grant=%+v result=%+v team=%s", before, grant, out, id)
								}
							}
						}
					}
				}
			}
		}
	}
}

func TestInviteIssuanceProofCopiesEscapeAndRollback(t *testing.T) {
	f := newInviteFixture(t)
	re := &core.RequestEvent{App: f.app, Auth: f.full}
	var escaped writableInvite
	if _, err := escaped.mint(); !errors.Is(err, errClosedInviteAuthority) {
		t.Fatal(err)
	}
	stopped := errors.New("abort issuance")
	for _, rollback := range []bool{true, false} {
		issued, err := withWritableInvite(re, []string{f.alpha}, "rw", func(proof writableInvite) (issuedInvite, error) {
			escaped = proof
			out, err := proof.mint()
			if err != nil {
				return out, err
			}
			if _, err := escaped.mint(); !errors.Is(err, errClosedInviteAuthority) {
				t.Fatalf("copied proof reused: %v", err)
			}
			if rollback {
				return out, stopped
			}
			return out, nil
		})
		if rollback && !errors.Is(err, stopped) {
			t.Fatal(err)
		}
		if !rollback && err != nil {
			t.Fatal(err)
		}
		if _, err := escaped.mint(); !errors.Is(err, errClosedInviteAuthority) {
			t.Fatalf("escaped proof: %v", err)
		}
		_, err = f.app.FindFirstRecordByData("invites", "code_hash", inviteCodeHash(issued.code))
		if rollback && err == nil {
			t.Fatal("failed transaction minted invitation")
		}
		if !rollback && err != nil {
			t.Fatal(err)
		}
	}
}

func TestInviteIssuerRechecksRetirementAndNarrowingAfterAuthentication(t *testing.T) {
	for _, change := range []string{"unchanged", "retired", "viewer", "hidden"} {
		t.Run(change, func(t *testing.T) {
			f := newInviteFixture(t)
			token, err := f.full.NewAuthToken()
			if err != nil {
				t.Fatal(err)
			}
			entered, resume := make(chan bool, 1), make(chan struct{})
			routes, err := apis.NewRouter(f.app)
			if err != nil {
				t.Fatal(err)
			}
			routes.BindFunc(func(re *core.RequestEvent) error { entered <- re.Auth != nil; <-resume; return re.Next() })
			registerInviteRoutes(routes)
			mux, err := routes.BuildMux()
			if err != nil {
				t.Fatal(err)
			}
			request := httptest.NewRequest(http.MethodPost, "/api/lll/invites", strings.NewReader(`{"teams":["`+f.alpha+`"],"mode":"rw"}`))
			request.Header.Set("Content-Type", "application/json")
			request.Header.Set("Authorization", "Bearer "+token)
			result := make(chan *httptest.ResponseRecorder, 1)
			go func() { out := httptest.NewRecorder(); mux.ServeHTTP(out, request); result <- out }()
			select {
			case authenticated := <-entered:
				if !authenticated {
					close(resume)
					<-result
					t.Fatal("barrier precedes authentication")
				}
			case <-time.After(5 * time.Second):
				close(resume)
				t.Fatal("request never authenticated")
			}
			switch change {
			case "retired":
				f.full.RefreshTokenKey()
			case "viewer":
				f.full.Set("mode", "ro")
			case "hidden":
				f.full.Set("scope", "teams")
				f.full.Set("teams", []string{})
			}
			if err := f.app.Save(f.full); err != nil {
				close(resume)
				<-result
				t.Fatal(err)
			}
			close(resume)
			var out *httptest.ResponseRecorder
			select {
			case out = <-result:
			case <-time.After(5 * time.Second):
				t.Fatal("request never resumed")
			}
			want := http.StatusForbidden
			if change == "unchanged" {
				want = http.StatusOK
			}
			if change == "retired" {
				want = http.StatusUnauthorized
			}
			if out.Code != want {
				t.Fatalf("%d, want%d: %s", out.Code, want, out.Body)
			}
			records, err := f.app.FindAllRecords("invites")
			if err != nil {
				t.Fatal(err)
			}
			count := 0
			if change == "unchanged" {
				count = 1
			}
			if len(records) != count {
				t.Fatal("revoked issuer minted an invitation")
			}
		})
	}
}
