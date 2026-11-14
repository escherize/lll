package gopb

import (
	"net/http"
	"testing"
)

// Authorization parsed before waiting is not proof about the write transaction.
// Each case pauses the real authenticated HTTP request after preflight, changes
// the authoritative member, then checks that no issue/claim write can commit.
func TestClaimRoutesRecheckAuthorityAfterWaitingForIssue(t *testing.T) {
	for _, change := range []string{"read-only", "no-teams", "rotated-token"} {
		t.Run(change, func(t *testing.T) {
			want := http.StatusForbidden
			if change == "no-teams" {
				want = http.StatusNotFound
			}
			if change == "rotated-token" {
				want = http.StatusUnauthorized
			}
			testClaimRoutesRecheckAfterWaiting(t, func(f creatorFixture) {
				member := f.reload(t, f.human)
				switch change {
				case "read-only":
					member.Set("mode", "ro")
				case "no-teams":
					setAccess(member, access{})
				case "rotated-token":
					member.RefreshTokenKey()
				}
				if err := f.app.Save(member); err != nil {
					t.Fatal(err)
				}
			}, want)
		})
	}
}
