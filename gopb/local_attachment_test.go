package gopb

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/security"
)

func TestLocalAttachmentProofUsesLocalSigningKeys(t *testing.T) {
	f := newCreatorFixture(t)
	token, err := f.human.NewAuthToken()
	if err != nil {
		t.Fatal(err)
	}
	if !LocalAttachmentMatches(f.app.DataDir(), token, "ALPHA") {
		t.Fatal("valid local login rejected")
	}
	if !LocalAttachmentMatches(f.app.DataDir(), token, "alpha") {
		t.Fatal("normalized team rejected")
	}
	for _, key := range []string{"", "MISSING", "ALPHA' OR 1=1 --"} {
		if LocalAttachmentMatches(f.app.DataDir(), token, key) {
			t.Fatal("unmatched team accepted")
		}
	}
	other := newCreatorFixture(t)
	foreign, err := other.human.NewAuthToken()
	if err != nil {
		t.Fatal(err)
	}
	if LocalAttachmentMatches(f.app.DataDir(), foreign, "ALPHA") {
		t.Fatal("foreign login accepted")
	}
	claims, err := security.ParseUnverifiedJWT(token)
	if err != nil {
		t.Fatal(err)
	}
	forged, err := security.NewJWT(claims, "foreign-key", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	if LocalAttachmentMatches(f.app.DataDir(), forged, "ALPHA") {
		t.Fatal("copied local claims with a foreign signature accepted")
	}
	f.human.RefreshTokenKey()
	if err := f.app.Save(f.human); err != nil {
		t.Fatal(err)
	}
	if LocalAttachmentMatches(f.app.DataDir(), token, "ALPHA") {
		t.Fatal("revoked token accepted")
	}
}

func TestLocalAttachmentProofRefusesOtherTokenTypesAndExpiry(t *testing.T) {
	f := newCreatorFixture(t)
	for _, kind := range []string{core.TokenTypeFile, core.TokenTypePasswordReset, core.TokenTypeAuth} {
		claims := jwt.MapClaims{core.TokenClaimId: f.human.Id, core.TokenClaimCollectionId: f.members.Id, core.TokenClaimType: kind}
		duration := time.Hour
		if kind == core.TokenTypeAuth {
			duration = -time.Hour
		}
		token, err := security.NewJWT(claims, f.human.TokenKey()+f.members.AuthToken.Secret, duration)
		if err != nil {
			t.Fatal(err)
		}
		if LocalAttachmentMatches(f.app.DataDir(), token, "ALPHA") {
			t.Fatal("non-auth or expired token accepted")
		}
	}
}

func TestLocalAttachmentProofDoesNotCreateMissingDatabase(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "absent")
	for _, token := range []string{"", "not-a-token"} {
		if LocalAttachmentMatches(dir, token, "ALPHA") {
			t.Fatal("invalid proof accepted")
		}
	}
	f := newCreatorFixture(t)
	token, _ := f.human.NewAuthToken()
	if LocalAttachmentMatches(dir, token, "ALPHA") {
		t.Fatal("absent data accepted")
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("proof created the data directory")
	}
}

func TestLocalAttachmentProofLeavesDatabaseBytesUnchanged(t *testing.T) {
	f := newCreatorFixture(t)
	token, err := f.human.NewAuthToken()
	if err != nil {
		t.Fatal(err)
	}
	dir := f.app.DataDir()
	if err := f.app.ResetBootstrapState(); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "data.db")
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !LocalAttachmentMatches(dir, token, "ALPHA") {
		t.Fatal("closed local database refused")
	}
	after, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(before) != string(after) {
		t.Fatal("read-only proof changed database bytes")
	}
	corrupt := t.TempDir()
	corruptPath := filepath.Join(corrupt, "data.db")
	if err := os.WriteFile(corruptPath, []byte("not a database"), 0600); err != nil {
		t.Fatal(err)
	}
	if LocalAttachmentMatches(corrupt, token, "ALPHA") {
		t.Fatal("corrupt database accepted")
	}
	after, err = os.ReadFile(corruptPath)
	if err != nil || string(after) != "not a database" {
		t.Fatal("corrupt database modified")
	}
}
