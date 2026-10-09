package gopb

import (
	"database/sql"
	"errors"
	"fmt"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/core"
)

// ClaimOutcome is the committed domain transition, shared by HTTP adapters.
// The caller must authenticate the actor before acquiring a claim.
type ClaimOutcome struct {
	ClaimID         string `json:"claim_id"`
	MemberID        string `json:"member_id"`
	MemberName      string `json:"member_name"`
	Agent           string `json:"agent"`
	Created         string `json:"created"`
	AlreadyOwned    bool   `json:"already_owned"`
	ClearedAssignee bool   `json:"cleared_assignee"`
	// Forced is true when the release took another member's claim and left a
	// comment saying so (LLL-512).
	Forced bool `json:"forced"`
}

// claimRejection is a refusal with a stable code (LLL-645): claim_held,
// needs_force, claim_changed or not_claimed, or "" for a malformed request.
// The code reaches the client at data.code, so clients branch on it rather
// than on the English message.
type claimRejection struct{ code, message string }

func (e *claimRejection) Error() string { return e.message }

func currentClaim(app core.App, issueID string) (*core.Record, error) {
	claim, err := app.FindFirstRecordByFilter("claims", "issue={:issue}", dbx.Params{"issue": issueID})
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	return claim, err
}

// acquireClaim keeps both the exclusive hold and its assignment on the
// serialized writer transaction. A duplicate by its holder repairs assignment
// without replacing the original claim or its creation time.
//
// agent is a self-asserted session label (LLL-521) so agents sharing one
// member token can tell their holds apart. It is coordination, not auth: the
// only refusal it adds is two different non-empty labels on one member. An
// empty label on either side keeps the member-level idempotency.
// agentsDiffer is the one refusal an agent label adds (LLL-521): two
// different non-empty labels on the same member's hold.
func agentsDiffer(held *core.Record, agent string) bool {
	return held.GetString("agent") != "" && agent != "" && held.GetString("agent") != agent
}

func acquireClaim(app core.App, issueID, memberID, agent string) (ClaimOutcome, error) {
	var outcome ClaimOutcome
	err := app.RunInTransaction(func(tx core.App) error {
		issue, err := tx.FindRecordById("issues", issueID)
		if err != nil {
			return err
		}
		member, err := tx.FindRecordById("members", memberID)
		if err != nil {
			return err
		}
		held, err := currentClaim(tx, issueID)
		if err != nil {
			return err
		}
		alreadyOwned := held != nil
		if held != nil && held.GetString("member") != memberID {
			name := rosterName(tx, memberID, held.GetString("member"), "someone else")
			return &claimRejection{"claim_held", fmt.Sprintf("issue is already claimed by %s", name)}
		}
		if held != nil && agentsDiffer(held, agent) {
			return &claimRejection{"claim_held", fmt.Sprintf("issue is already claimed by %s (agent %s)",
				member.GetString("name"), held.GetString("agent"))}
		}
		if held == nil {
			collection, err := tx.FindCollectionByNameOrId("claims")
			if err != nil {
				return err
			}
			held = core.NewRecord(collection)
			held.Set("issue", issueID)
			held.Set("member", memberID)
			held.Set("agent", agent)
			if err := tx.Save(held); err != nil {
				return err
			}
		}
		if issue.GetString("assignee") != memberID {
			issue.Set("assignee", memberID)
			if err := tx.Save(issue); err != nil {
				return err
			}
		}
		outcome = ClaimOutcome{ClaimID: held.Id, MemberID: memberID, MemberName: member.GetString("name"),
			Agent: held.GetString("agent"), Created: held.GetString("created"), AlreadyOwned: alreadyOwned}
		return nil
	})
	if err != nil {
		return ClaimOutcome{}, err
	}
	return outcome, nil
}

// releaser is who asked for a release, as the HTTP adapter authenticated it.
// memberID is empty for a superuser: that token names no member, so it can
// never be the holder and always needs force.
//
// agent is the releasing session's label (LLL-521). The same member under a
// different non-empty label than the holder's is another session, and like
// another member it needs force.
type releaser struct {
	memberID string
	agent    string
	force    bool
	reason   string
}

// byline names a member and, when it has one, its session label.
func byline(name, agent string) string {
	if agent == "" {
		return name
	}
	return fmt.Sprintf("%s (agent %s)", name, agent)
}

// releaseClaim names the observed hold, so a stale command or page cannot
// release a replacement claim. Assignment is checked from the fresh record
// inside this same transaction; unrelated assignment is preserved.
//
// Only the holder releases without force (LLL-512): in a fleet, a confused
// sibling releasing someone else's hold unlocks an issue another agent is
// still editing. The holder is read from the fresh record inside the
// transaction, so the check and the delete see the same claim.
func releaseClaim(app core.App, issueID, expectedClaimID string, by releaser) (ClaimOutcome, error) {
	var outcome ClaimOutcome
	err := app.RunInTransaction(func(tx core.App) error {
		issue, err := tx.FindRecordById("issues", issueID)
		if err != nil {
			return err
		}
		held, err := currentClaim(tx, issueID)
		if err != nil {
			return err
		}
		if held == nil {
			return &claimRejection{"not_claimed", "is not claimed"}
		}
		if expectedClaimID == "" || held.Id != expectedClaimID {
			return &claimRejection{"claim_changed", "the claim changed; refresh before releasing it"}
		}
		memberID := held.GetString("member")
		name, forced, err := releaseAuthority(tx, held, by)
		if err != nil {
			return err
		}
		cleared := issue.GetString("assignee") == memberID
		if err := tx.Delete(held); err != nil {
			return err
		}
		if cleared {
			issue.Set("assignee", "")
			if err := tx.Save(issue); err != nil {
				return err
			}
		}
		if forced {
			if err := recordForcedRelease(tx, issue, held, by); err != nil {
				return err
			}
		}
		outcome = ClaimOutcome{ClaimID: held.Id, MemberID: memberID, MemberName: name, ClearedAssignee: cleared, Forced: forced}
		return nil
	})
	if err != nil {
		return ClaimOutcome{}, err
	}
	return outcome, nil
}

// closeIssue sets an issue done and, by default, releases its claim in the
// same transaction (D3 of the 1.0 plan, LLL-640). Closing used to keep the
// hold, and agents that forgot the separate release left finished work
// claimed until the 24-hour sweep.
//
// The release follows the one release rule (releaseAuthority): the holder's
// close releases freely; anyone else, a superuser included, needs force, and
// a forced close leaves the forced-release comment. keepClaim keeps the hold,
// and only the holder may: closing another member's claimed issue takes it
// from them, so it releases or is refused. The assignee is kept: a done
// issue still says who did it, and with the claim gone nothing offers it as
// work.
//
// expectedClaimID is the hold the caller observed, "" for none, as on
// /assignment: a claim taken or replaced since the caller looked refuses the
// close rather than closing over it.
func closeIssue(app core.App, issueID, expectedClaimID string, by releaser, keepClaim bool) (ClaimOutcome, error) {
	var outcome ClaimOutcome
	err := app.RunInTransaction(func(tx core.App) error {
		issue, err := tx.FindRecordById("issues", issueID)
		if err != nil {
			return err
		}
		held, err := currentClaim(tx, issueID)
		if err != nil {
			return err
		}
		currentID := ""
		if held != nil {
			currentID = held.Id
		}
		if currentID != expectedClaimID {
			return &claimRejection{"claim_changed", "the claim changed; refresh before closing"}
		}
		if held != nil {
			// releaseAuthority words needs_force and names the holder; the
			// table (TransitionClaim) decides what the close does to the hold.
			name, forced, err := releaseAuthority(tx, held, by)
			if err != nil {
				return err
			}
			effect, refusal := TransitionClaim(VerbClose, issue.GetString("state"), "done", holdOf(held, by), keepClaim, by.force)
			if refusal == "claim_held" {
				return &claimRejection{"claim_held", fmt.Sprintf("the claim is held by %s; only the holder keeps a claim while closing, and closing anyone else's claimed issue releases it",
					byline(name, held.GetString("agent")))}
			}
			outcome = ClaimOutcome{ClaimID: held.Id, MemberID: held.GetString("member"), MemberName: name,
				Agent: held.GetString("agent"), Created: held.GetString("created"), AlreadyOwned: effect == ClaimKept, Forced: forced}
			if effect != ClaimKept {
				if err := tx.Delete(held); err != nil {
					return err
				}
				if effect == ClaimForceReleased {
					if err := recordForcedRelease(tx, issue, held, by); err != nil {
						return err
					}
				}
			}
		}
		issue.Set("state", "done")
		return tx.Save(issue)
	})
	if err != nil {
		return ClaimOutcome{}, err
	}
	return outcome, nil
}

// finishReleases is the finish rule (fleet case 07), the move rows of the
// transition table (TransitionClaim): an issue moved into done or cancelled
// by its claim's holder releases the claim and keeps the assignee, unless
// keepClaim. /assignment and a native PATCH (registerFinishRelease) use it;
// /close reads the close rows of the same table. A move by anyone else
// leaves the claim alone: it is not their hold to give back, and a PATCH
// carries no force and writes no comment.
func finishReleases(held *core.Record, from, to string, by releaser, keepClaim bool) bool {
	effect, _ := TransitionClaim(VerbMove, from, to, holdOf(held, by), keepClaim, false)
	return effect == ClaimReleased
}

// registerFinishRelease applies the finish rule to a native PATCH of an
// issue's state. The PATCH names its session label and opt-out as query
// parameters, ?agent=LABEL and ?keep_claim=true, because its body is the
// record. The claim is deleted in the transaction that saves the issue:
// form.Submit saves through e.App, which is swapped for the transaction.
// serializeRecordUpdates holds the issue's lock, the one the claim routes
// take, so the claim read here cannot change before the save.
func registerFinishRelease(app core.App) {
	app.OnRecordUpdateRequest("issues").BindFunc(func(e *core.RecordRequestEvent) error {
		from, to := e.Record.Original().GetString("state"), e.Record.GetString("state")
		if from == to || e.Auth == nil || e.Auth.Collection().Name != "members" {
			return e.Next()
		}
		query := e.Request.URL.Query()
		by := releaser{memberID: e.Auth.Id, agent: query.Get("agent")}
		if !agentLabelShape.MatchString(by.agent) {
			return e.BadRequestError(agentLabelRule, nil)
		}
		held, err := currentClaim(e.App, e.Record.Id)
		if err != nil {
			return err
		}
		if !finishReleases(held, from, to, by, query.Get("keep_claim") == "true") {
			return e.Next()
		}
		original := e.App
		defer func() { e.App = original }()
		return original.RunInTransaction(func(tx core.App) error {
			e.App = tx
			if err := tx.Delete(held); err != nil {
				return err
			}
			return e.Next()
		})
	})
}

// releaseAuthority is the one release rule (LLL-512, LLL-521), shared by
// /release, /close and an assignment edit that clears the assignee
// (LLL-516): the holder releases freely; another member, a superuser, or the
// holder's member under a different agent label needs force. It returns the
// holder's name as the caller may see it, and whether the release is forced
// and so owes a comment. Without force, a forced release is refused naming
// the holder.
//
// `name` follows the roster (LLL-551): a holder the caller may not see is "a
// hidden member".
func releaseAuthority(tx core.App, held *core.Record, by releaser) (name string, forced bool, err error) {
	memberID := held.GetString("member")
	name = rosterName(tx, by.memberID, memberID, "an unknown member")
	shown := byline(name, held.GetString("agent"))
	otherSession := memberID == by.memberID && agentsDiffer(held, by.agent)
	forced = memberID != by.memberID || otherSession
	if forced && !by.force {
		if otherSession {
			return name, forced, &claimRejection{"needs_force", fmt.Sprintf("the claim is held by %s; releasing another session's claim needs force", shown)}
		}
		return name, forced, &claimRejection{"needs_force", fmt.Sprintf("the claim is held by %s; releasing another member's claim needs force", shown)}
	}
	return name, forced, nil
}

// systemAuthorKind marks a comment the server wrote on its own, with no
// member behind it (LLL-654): today only the claim-expiry note. Tools that
// treated every authorless comment as the human's read this instead of
// guessing. Only the server sets it; registerSystemCommentGuard refuses it
// from any request. A system comment never carries caller-supplied text, so
// the label cannot vouch for words a member chose: the forced-release
// comment, which embeds the releaser's reason, stays the releaser's.
const systemAuthorKind = "system"

// outsideTeam is how a server-written comment names a member that not every
// reader of the issue may see (LLL-633). The body is stored text, so it
// cannot be masked per reader the way relation fields are.
const outsideTeam = "a member outside this team"

// storedName is a member's name as a comment on issue may store it: the name
// when every member who sees the issue's team may see the member
// (onTeamRoster), else outsideTeam (LLL-633). Fallback is for a member that
// no longer exists.
func storedName(app core.App, issue *core.Record, memberID, fallback string) string {
	m, err := app.FindRecordById("members", memberID)
	if err != nil {
		return fallback
	}
	if !onTeamRoster(m, issue.GetString("team")) {
		return outsideTeam
	}
	return m.GetString("name")
}

// recordForcedRelease writes the comment a forced release owes the holder
// (LLL-512). It runs INSIDE the release transaction, the opposite of the
// expiry announcement (LLL-452), and for the reason LLL-452 gave: that comment
// goes after the commit because rolling back an unattended sweep over a comment
// would hand the same claim to the next sweep forever. Here a person or agent
// is waiting on the answer and can retry, and the comment is the price of
// force, not a courtesy - a forced release with no record is the silent
// release this issue exists to stop.
//
// The releaser is the author, so the comment is attributed like any other,
// and its author kind stays a member's: the reason is the releaser's own
// words, so marking it system would let any member put prose in the server's
// voice. A superuser has no member record and the comment goes authorless.
// The body names both parties as storedName allows (LLL-633).
func recordForcedRelease(tx core.App, issue, held *core.Record, by releaser) error {
	actor := "An administrator"
	if by.memberID != "" {
		if _, err := tx.FindRecordById("members", by.memberID); err != nil {
			return err
		}
		name := storedName(tx, issue, by.memberID, "")
		if name == outsideTeam {
			name = "A member outside this team"
		}
		actor = byline(name, by.agent)
	}
	holder := byline(storedName(tx, issue, held.GetString("member"), "an unknown member"), held.GetString("agent"))
	body := fmt.Sprintf("%s force-released %s's claim.", actor, holder)
	if by.reason != "" {
		body += "\n\nReason: " + by.reason
	}
	comments, err := tx.FindCollectionByNameOrId("comments")
	if err != nil {
		return err
	}
	comment := core.NewRecord(comments)
	comment.Set("issue", issue.Id)
	comment.Set("author", by.memberID)
	comment.Set("server_record", true)
	comment.Set("body", body)
	return tx.Save(comment)
}

// renewClaim restarts a hold's expiry clock (LLL-535). The sweep ages a claim
// by `updated`, and nothing but this writes a claim, so saving it unchanged is
// the renewal: the autodate moves and the claim keeps its id and `created`.
// Keeping the id matters - release and assignment name the observed claim_id,
// so a delete-and-recreate would turn every open page's next release into
// "the claim changed".
//
// Only the holder renews, and only the hold it observed: renewing is a promise
// that the work is still alive, which no one else can make. A sibling agent
// on the holder's token is "someone else" when both carry different labels
// (LLL-521), the same test acquireClaim applies.
func renewClaim(app core.App, issueID, expectedClaimID, memberID, agent string) (ClaimOutcome, error) {
	var outcome ClaimOutcome
	err := app.RunInTransaction(func(tx core.App) error {
		held, err := currentClaim(tx, issueID)
		if err != nil {
			return err
		}
		if held == nil {
			return &claimRejection{"not_claimed", "is not claimed"}
		}
		if expectedClaimID == "" || held.Id != expectedClaimID {
			return &claimRejection{"claim_changed", "the claim changed; refresh before renewing it"}
		}
		holderID := held.GetString("member")
		name := rosterName(tx, memberID, holderID, "an unknown member")
		if holderID != memberID {
			return &claimRejection{"claim_held", fmt.Sprintf("the claim is held by %s; only the holder renews it", name)}
		}
		if agentsDiffer(held, agent) {
			return &claimRejection{"claim_held", fmt.Sprintf("the claim is held by %s (agent %s); only the holder renews it",
				name, held.GetString("agent"))}
		}
		if err := tx.Save(held); err != nil {
			return err
		}
		outcome = ClaimOutcome{ClaimID: held.Id, MemberID: holderID, MemberName: name, Agent: held.GetString("agent"), Created: held.GetString("created")}
		return nil
	})
	if err != nil {
		return ClaimOutcome{}, err
	}
	return outcome, nil
}

// registerClaimedIssueDeleteGuard refuses an API delete of a claimed issue
// (LLL-662). claims.issue cascades, so the delete used to drop the hold with
// no force and no record: the silent release LLL-512 forbids. The claim goes
// first, through /release and its rule (the holder freely, anyone else with
// force and a comment), then the issue; 'lll issue delete --force' does both.
// A cascade from deleting a team or member is not a request on issues and is
// unaffected. serializeRecordUpdates holds the issue's lock across the
// request, the same lock the claim routes take, so no claim lands between
// this check and the delete.
func registerClaimedIssueDeleteGuard(app core.App) {
	app.OnRecordDeleteRequest("issues").BindFunc(func(e *core.RecordRequestEvent) error {
		held, err := currentClaim(e.App, e.Record.Id)
		if err != nil {
			return err
		}
		if held == nil {
			return e.Next()
		}
		viewerID := ""
		if e.Auth != nil && !e.Auth.IsSuperuser() {
			viewerID = e.Auth.Id
		}
		name := rosterName(e.App, viewerID, held.GetString("member"), "an unknown member")
		return e.BadRequestError(fmt.Sprintf("the issue is claimed by %s; release the claim before deleting the issue (another member's claim needs force)",
			byline(name, held.GetString("agent"))), nil)
	})
}

// registerSystemCommentGuard keeps author_kind the server's word (LLL-654):
// no request may set it, and no request may edit a comment the server wrote,
// so "system" on a comment always means the words are the server's. Only a
// superuser may delete one (ownComment).
//
// server_record marks every comment the server writes, the forced-release
// record as well as the expiry note. A forced release is attributed to its
// releaser and carries the releaser's reason, so it is not system, but it is
// the record LLL-512 requires: no request may edit it, and no member, the
// releaser included, may delete it, or the forcer could make the release
// silent after the fact.
//
// It also binds a member's comment to that member, the way issue creators
// and doc authors are bound (provenance.go). The comments rules check only
// team write access, so a member could post as anyone, or as no one, and an
// authorless comment shaped like the expiry note, or one in another member's
// name shaped like a forced release, read as the real record. A member's
// create is authored by that member, whatever the body says, and no member
// may move a comment's author. A superuser names no member and keeps
// choosing the author, as imports need.
func registerSystemCommentGuard(app core.App) {
	app.OnRecordCreateRequest("comments").BindFunc(func(e *core.RecordRequestEvent) error {
		if e.Record.GetString("author_kind") != "" || e.Record.GetBool("server_record") {
			return e.BadRequestError("author_kind and server_record are set by the server only", nil)
		}
		if e.Auth != nil && e.Auth.Collection().Name == "members" {
			e.Record.Set("author", e.Auth.Id)
		}
		return e.Next()
	})
	app.OnRecordUpdateRequest("comments").BindFunc(func(e *core.RecordRequestEvent) error {
		if e.Record.Original().GetString("author_kind") == systemAuthorKind || e.Record.Original().GetBool("server_record") {
			return e.BadRequestError("a server-written comment cannot be edited", nil)
		}
		if e.Record.GetString("author_kind") != "" || e.Record.GetBool("server_record") {
			return e.BadRequestError("author_kind and server_record are set by the server only", nil)
		}
		if e.Auth != nil && e.Auth.Collection().Name == "members" &&
			e.Record.GetString("author") != e.Record.Original().GetString("author") {
			return e.BadRequestError("a comment's author cannot be changed", nil)
		}
		// LLL-678: a comment stays on the issue it was written on, whoever
		// asks, a superuser included. Moving one would put words under an
		// issue they were not written about, and across teams it would carry
		// them out of the team that can read them.
		if e.Record.GetString("issue") != e.Record.Original().GetString("issue") {
			return e.BadRequestError("a comment stays on the issue it was written on; its issue cannot be changed", nil)
		}
		if err := ownComment(e); err != nil {
			return err
		}
		return e.Next()
	})
	app.OnRecordDeleteRequest("comments").BindFunc(func(e *core.RecordRequestEvent) error {
		if e.Auth != nil && e.Auth.Collection().Name == "members" && e.Record.GetBool("server_record") {
			return e.ForbiddenError("a server-written comment can be deleted only by an administrator", nil)
		}
		if err := ownComment(e); err != nil {
			return err
		}
		return e.Next()
	})
}

// ownComment is the rule for changing a comment: a member edits or deletes
// only a comment it authored. The comments rules check only team write
// access, so before this any team writer could rewrite another member's words
// under that member's name, a forced-release record included, or delete
// them. A bot and its owner are different authors. An authorless comment (the
// expiry note, a superuser's) is no member's. A superuser names no member and
// keeps moderating.
func ownComment(e *core.RecordRequestEvent) error {
	if e.Auth == nil || e.Auth.Collection().Name != "members" {
		return nil
	}
	if e.Record.Original().GetString("author") == e.Auth.Id {
		return nil
	}
	return e.ForbiddenError("only a comment's author can change or delete it", nil)
}
