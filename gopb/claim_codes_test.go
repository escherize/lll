package gopb

import (
	"errors"
	"testing"

	"github.com/pocketbase/pocketbase/tools/router"
)

// LLL-645: every claim refusal carries a stable code, and the HTTP answer
// puts it at data.code, so clients branch on the code instead of the English
// message.
func TestClaimRejectionsCarryStableCodes(t *testing.T) {
	app, issueID, alpha, beta := claimFixture(t)
	held, err := acquireClaim(app, issueID, alpha, "")
	if err != nil {
		t.Fatal(err)
	}
	codeOf := func(err error) string {
		t.Helper()
		var rejected *claimRejection
		if !errors.As(err, &rejected) {
			t.Fatalf("not a claim rejection: %v", err)
		}
		return rejected.code
	}
	if _, err := acquireClaim(app, issueID, beta, ""); codeOf(err) != "claim_held" {
		t.Fatalf("held: %v", err)
	}
	if _, err := releaseClaim(app, issueID, held.ClaimID, releaser{memberID: beta}); codeOf(err) != "needs_force" {
		t.Fatalf("needs force: %v", err)
	}
	if _, err := releaseClaim(app, issueID, "stale", releaser{memberID: alpha}); codeOf(err) != "claim_changed" {
		t.Fatalf("changed: %v", err)
	}
	if _, err := releaseClaim(app, issueID, held.ClaimID, releaser{memberID: alpha}); err != nil {
		t.Fatal(err)
	}
	if _, err := releaseClaim(app, issueID, held.ClaimID, releaser{memberID: alpha}); codeOf(err) != "not_claimed" {
		t.Fatalf("not claimed: %v", err)
	}

	coded := withCode(router.NewBadRequestError("issue is already claimed by Alpha", nil), "claim_held")
	if coded.Data["code"] != "claim_held" {
		t.Fatalf("data.code: %#v", coded.Data)
	}
	if plain := withCode(router.NewBadRequestError("invalid", nil), ""); len(plain.Data) != 0 {
		t.Fatalf("an empty code added data: %#v", plain.Data)
	}
}
