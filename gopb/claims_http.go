package gopb

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strings"

	validation "github.com/pocketbase/ozzo-validation/v4"
	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/router"
)

func registerClaimRoutes(routes *router.Router[*core.RequestEvent], writes *issueWriteLocks) {
	routes.POST("/api/lll/issues/{issue}/assignment", func(re *core.RequestEvent) error {
		var body struct {
			ClaimID *string         `json:"claim_id"`
			Fields  json.RawMessage `json:"fields"`
		}
		re.Request.Body = http.MaxBytesReader(re.Response, re.Request.Body, 8<<20)
		if err := re.BindBody(&body); err != nil || body.ClaimID == nil {
			return re.BadRequestError("assignment update requires the observed claim_id and fields", nil)
		}
		fields, err := parseAssignmentFields(body.Fields)
		if err != nil {
			return re.BadRequestError("invalid assignment update fields", err)
		}
		unlock := writes.acquire(re.Request.PathValue("issue"))
		defer unlock()
		outcome, err := updateAssignment(re.App, re.Request.PathValue("issue"), *body.ClaimID, fields)
		return respondClaim(re, outcome, err)
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))

	routes.POST("/api/lll/issues/{issue}/claim", func(re *core.RequestEvent) error {
		var body struct {
			Member string `json:"member"`
		}
		re.Request.Body = http.MaxBytesReader(re.Response, re.Request.Body, 2048)
		if err := re.BindBody(&body); err != nil {
			return re.BadRequestError("invalid claim request", nil)
		}
		if re.HasSuperuserAuth() {
			if body.Member == "" {
				return re.BadRequestError("superuser claim requires a member", nil)
			}
		} else {
			if body.Member != "" && body.Member != re.Auth.Id {
				return re.ForbiddenError("claim member must match the authenticated member", nil)
			}
			body.Member = re.Auth.Id
		}
		unlock := writes.acquire(re.Request.PathValue("issue"))
		defer unlock()
		outcome, err := acquireClaim(re.App, re.Request.PathValue("issue"), body.Member)
		return respondClaim(re, outcome, err)
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))

	routes.POST("/api/lll/issues/{issue}/release", func(re *core.RequestEvent) error {
		var body struct {
			ClaimID string `json:"claim_id"`
			Force   bool   `json:"force"`
			Reason  string `json:"reason"`
		}
		// 8 KiB, not the claim route's 2: the optional reason is prose.
		re.Request.Body = http.MaxBytesReader(re.Response, re.Request.Body, 8<<10)
		if err := re.BindBody(&body); err != nil {
			return re.BadRequestError("invalid release request", nil)
		}
		if body.ClaimID == "" {
			return re.BadRequestError("release requires the observed claim_id", nil)
		}
		// The holder releases freely; anyone else needs force, and a forced
		// release leaves a comment (LLL-512). Naming the observed hold still
		// prevents a stale release.
		//
		// A superuser gets no exemption. Its token names no member, so it is
		// never the holder, and the fleet operator holding admin credentials
		// is exactly who should say so out loud: force costs one flag, and
		// the comment is the only record the release happened. (A superuser
		// can still DELETE the record directly - claims.deleteRule is null,
		// not "nobody" - but that is the admin API, not the release path.)
		by := releaser{force: body.Force, reason: strings.TrimSpace(body.Reason)}
		if !re.HasSuperuserAuth() {
			by.memberID = re.Auth.Id
		}
		unlock := writes.acquire(re.Request.PathValue("issue"))
		defer unlock()
		outcome, err := releaseClaim(re.App, re.Request.PathValue("issue"), body.ClaimID, by)
		return respondClaim(re, outcome, err)
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))

	routes.POST("/api/lll/issues/{issue}/renew", func(re *core.RequestEvent) error {
		var body struct {
			ClaimID string `json:"claim_id"`
		}
		re.Request.Body = http.MaxBytesReader(re.Response, re.Request.Body, 2048)
		if err := re.BindBody(&body); err != nil || body.ClaimID == "" {
			return re.BadRequestError("renew requires the observed claim_id", nil)
		}
		// A superuser token names no member, so it is never the holder and
		// renewClaim refuses it with the holder's name.
		memberID := ""
		if !re.HasSuperuserAuth() {
			memberID = re.Auth.Id
		}
		unlock := writes.acquire(re.Request.PathValue("issue"))
		defer unlock()
		outcome, err := renewClaim(re.App, re.Request.PathValue("issue"), body.ClaimID, memberID)
		return respondClaim(re, outcome, err)
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))
}

func respondClaim(re *core.RequestEvent, outcome ClaimOutcome, err error) error {
	if err == nil {
		return re.JSON(http.StatusOK, outcome)
	}
	// A rejected claim is a claim-only concept: someone else holds it. Everything
	// below it is the shared shape.
	var rejected *claimRejection
	if errors.As(err, &rejected) {
		return re.BadRequestError(rejected.Error(), nil)
	}
	return writeFailure(re, err, "issue or member no longer exists", "invalid issue fields", "claim transaction failed")
}

// writeFailure maps a failed transaction onto a response. The lll routes that
// write inside a transaction - claims and references - had the same three
// branches with different nouns, and had drifted into checking them in
// different orders, so the nouns are the parameters and the order is fixed
// here: the most specific error first.
func writeFailure(re *core.RequestEvent, err error, missing, invalidMsg, failed string) error {
	var invalid validation.Errors
	if errors.As(err, &invalid) {
		return re.BadRequestError(invalidMsg, invalid)
	}
	if errors.Is(err, sql.ErrNoRows) {
		return re.BadRequestError(missing, nil)
	}
	return re.InternalServerError(failed, err)
}
