package gopb

import (
	"errors"
	"net/http/httptest"
	"testing"

	"github.com/pocketbase/pocketbase/core"
)

func authorityFixture(t *testing.T) (creatorFixture, *core.Record, *core.RequestEvent) {
	t.Helper()
	f := newCreatorFixture(t)
	collection := core.NewBaseCollection("issues")
	collection.Fields.Add(&core.TextField{Name: "team"}, &core.TextField{Name: "refs"})
	if err := f.app.Save(collection); err != nil {
		t.Fatal(err)
	}
	issue := core.NewRecord(collection)
	issue.Set("team", f.alpha)
	if err := f.app.Save(issue); err != nil {
		t.Fatal(err)
	}
	re := &core.RequestEvent{App: f.app, Auth: f.human}
	re.Request = httptest.NewRequest("POST", "/", nil)
	re.Request.SetPathValue("issue", issue.Id)
	return f, issue, re
}

func TestWritableIssueZeroAndEscapedValuesHaveNoAuthority(t *testing.T) {
	f, issue, re := authorityFixture(t)
	var escaped writableIssue
	if _, err := escaped.appendReference("gh#zero", releaser{}); !errors.Is(err, errClosedIssueAuthority) {
		t.Fatalf("zero proof: %v", err)
	}
	_, err := withWritableIssue(re, func(proof writableIssue) (referenceOutcome, error) {
		escaped = proof
		return proof.appendReference("gh#authorized", releaser{memberID: f.human.Id})
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = escaped.appendReference("gh#escaped", releaser{}); !errors.Is(err, errClosedIssueAuthority) {
		t.Fatalf("escaped proof: %v", err)
	}
	stored, err := f.app.FindRecordById("issues", issue.Id)
	if err != nil {
		t.Fatal(err)
	}
	if stored.GetString("refs") != "gh#authorized" {
		t.Fatalf("unproven write committed: %q", stored.GetString("refs"))
	}
}

func TestWritableIssueClosesAndRollsBackOnCallbackError(t *testing.T) {
	f, issue, re := authorityFixture(t)
	stopped := errors.New("abort operation")
	var escaped writableIssue
	_, err := withWritableIssue(re, func(proof writableIssue) (referenceOutcome, error) {
		escaped = proof
		if _, err := proof.appendReference("gh#rolled-back", releaser{}); err != nil {
			return referenceOutcome{}, err
		}
		return referenceOutcome{}, stopped
	})
	if !errors.Is(err, stopped) {
		t.Fatalf("callback error: %v", err)
	}
	if _, err = escaped.appendReference("gh#escaped", releaser{}); !errors.Is(err, errClosedIssueAuthority) {
		t.Fatalf("failed scope proof: %v", err)
	}
	stored, err := f.app.FindRecordById("issues", issue.Id)
	if err != nil {
		t.Fatal(err)
	}
	if stored.GetString("refs") != "" {
		t.Fatal("failed authorized operation committed a partial write")
	}
}

func TestWritableIssueCannotBeParsedForHiddenOrMissingResources(t *testing.T) {
	f, _, re := authorityFixture(t)
	f.human.Set("scope", "teams")
	f.human.Set("teams", []string{f.beta})
	if err := f.app.Save(f.human); err != nil {
		t.Fatal(err)
	}
	called := false
	_, err := withWritableIssue(re, func(proof writableIssue) (referenceOutcome, error) {
		called = true
		return proof.appendReference("gh#denied", releaser{})
	})
	if err == nil || called {
		t.Fatal("hidden issue supplied write authority")
	}
	re.Request.SetPathValue("issue", "missing")
	_, err = withWritableIssue(re, func(proof writableIssue) (referenceOutcome, error) {
		called = true
		return proof.appendReference("gh#denied", releaser{})
	})
	if err == nil || called {
		t.Fatal("missing issue supplied write authority")
	}
}

func TestWritableIssueBindsClaimAndAuditIdentity(t *testing.T) {
	f, _, re := authorityFixture(t)
	_, err := withWritableIssue(re, func(proof writableIssue) (ClaimOutcome, error) {
		return proof.claim(f.other.Id, "worker", releaser{memberID: f.other.Id})
	})
	if err == nil {
		t.Fatal("write authority accepted another member as the claim holder")
	}
	_, err = withWritableIssue(re, func(proof writableIssue) (referenceOutcome, error) {
		return useIssueWrite(proof, func(s *issueWriteScope) (referenceOutcome, error) {
			by := s.stamp(releaser{memberID: f.other.Id, agent: "worker"})
			if by.memberID != f.human.Id || by.agent != "worker" {
				t.Fatal("actor proof did not bind attribution")
			}
			return referenceOutcome{}, nil
		})
	})
	if err != nil {
		t.Fatal(err)
	}
}
