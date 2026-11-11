package gopb

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/url"
	"path/filepath"
	"time"

	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/security"
)

// LocalAttachmentMatches proves that a saved member login belongs to the
// named board's existing database. It never boots PocketBase, migrates data,
// creates a missing database or contacts the configured network endpoint.
// SQL only locates PocketBase's persisted signing keys; PocketBase's own JWT
// helpers validate type, signature and expiry, as FindAuthRecordByToken does.
// Unknown schemas and inaccessible/corrupt data fail closed.
func LocalAttachmentMatches(directory, token, team string) bool {
	claims, err := security.ParseUnverifiedJWT(token)
	if err != nil || claims[core.TokenClaimType] != core.TokenTypeAuth || team == "" {
		return false
	}
	id, _ := claims[core.TokenClaimId].(string)
	collection, _ := claims[core.TokenClaimCollectionId].(string)
	if id == "" || collection == "" {
		return false
	}
	path, err := filepath.Abs(filepath.Join(directory, "data.db"))
	if err != nil {
		return false
	}
	dsn := (&url.URL{Scheme: "file", Path: path, RawQuery: "mode=ro"}).String()
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return false
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	var options, key string
	err = db.QueryRowContext(ctx, `SELECT c.options, m.tokenKey
		FROM _collections c JOIN members m ON m.id = ?
		WHERE c.id = ? AND c.name = 'members' AND c.type = 'auth'
		AND EXISTS (SELECT 1 FROM teams WHERE "key" = ? COLLATE NOCASE)`, id, collection, team).Scan(&options, &key)
	if err != nil || key == "" {
		return false
	}
	var auth struct {
		AuthToken struct {
			Secret string `json:"secret"`
		} `json:"authToken"`
	}
	if json.Unmarshal([]byte(options), &auth) != nil || auth.AuthToken.Secret == "" {
		return false
	}
	_, err = security.ParseJWT(token, key+auth.AuthToken.Secret)
	return err == nil
}
