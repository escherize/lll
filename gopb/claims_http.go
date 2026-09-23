package gopb

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"

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
			Agent  string `json:"agent"`
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
		outcome, err := acquireClaim(re.App, re.Request.PathValue("issue"), body.Member, body.Agent)
		return respondClaim(re, outcome, err)
	}).Bind(apis.RequireAuth("members", core.CollectionNameSuperusers))

	routes.POST("/api/lll/issues/{issue}/release", func(re *core.RequestEvent) error {
		var body struct {
			ClaimID string `json:"claim_id"`
		}
		re.Request.Body = http.MaxBytesReader(re.Response, re.Request.Body, 2048)
		if err := re.BindBody(&body); err != nil {
			return re.BadRequestError("invalid release request", nil)
		}
		if body.ClaimID == "" {
			return re.BadRequestError("release requires the observed claim_id", nil)
		}
		// Any authenticated workspace member may release a hold, matching the
		// existing CLI contract; naming the observed hold prevents stale release.
		unlock := writes.acquire(re.Request.PathValue("issue"))
		defer unlock()
		outcome, err := releaseClaim(re.App, re.Request.PathValue("issue"), body.ClaimID)
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
