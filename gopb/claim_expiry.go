package gopb

import (
	"fmt"
	"time"

	"github.com/pocketbase/dbx"
	"github.com/pocketbase/pocketbase/core"
)

// LLL-183: a claim is a hold, and a dead agent's hold outlived it. Until now
// the only way back was for a person to notice and run `lll issue release`,
// which is exactly the noticing an unattended fleet cannot do - so an agent
// that crashed at 2am parked its issue until someone read the board.
//
// N = 24 hours, decided on the issue: long enough that a person working
// overnight is never interrupted, short enough that a crash frees its issue by
// morning.
const claimMaxAge = 24 * time.Hour

// Hourly. The sweep is a small indexed read plus a delete or two, and a claim
// that expires up to an hour late costs nothing - the issue was already idle
// for a day. Minutely would be the same work sixty times over.
const claimSweepSchedule = "0 * * * *"

// registerClaimExpiry runs the sweep on PocketBase's own scheduler, which is
// the reason this is server-side and not a CLI verb: it must happen whether or
// not anyone is running lll.
func registerClaimExpiry(app core.App) {
	app.Cron().MustAdd("lllExpireClaims", claimSweepSchedule, func() {
		if _, err := expireClaims(app, time.Now(), claimMaxAge); err != nil {
			app.Logger().Error("expiring stale claims", "error", err)
		}
	})
}

// expireClaims deletes every claim not renewed within maxAge and returns how
// many went.
//
// It clears the issue's assignee exactly when `lll issue release` would - only
// when the assignee is still the holder - so an expired claim leaves the issue
// in the state a deliberate release would have left it in, rather than a third
// state nobody has seen before.
//
// `now` is a parameter so the test does not have to wait a day.
func expireClaims(app core.App, now time.Time, maxAge time.Duration) (int, error) {
	cutoff := now.Add(-maxAge).UTC().Format("2006-01-02 15:04:05.000Z")
	stale, err := app.FindRecordsByFilter(
		// `updated`, not `created`: renewal (LLL-535) moves it, and nothing
		// else writes a claim, so it is when the holder last vouched for it.
		"claims", "updated < {:cutoff}", "updated", 0, 0,
		dbx.Params{"cutoff": cutoff},
	)
	if err != nil {
		return 0, err
	}

	expired := 0
	for _, claim := range stale {
		var announce *core.Record
		// One transaction per claim, not one for the sweep: an issue that has
		// been deleted under its claim must not strand every later claim in a
		// rolled-back batch.
		err := app.RunInTransaction(func(tx core.App) error {
			memberID := claim.GetString("member")
			// claims.issue is a REQUIRED relation, so PocketBase refuses to
			// delete an issue out from under its claim and this lookup cannot
			// miss today. Tolerated anyway: a sweep that errored on one
			// orphan would keep erroring on it every hour.
			if issue, err := tx.FindRecordById("issues", claim.GetString("issue")); err == nil {
				if issue.GetString("assignee") == memberID {
					issue.Set("assignee", "")
					if err := tx.Save(issue); err != nil {
						return err
					}
				}
				announce = issue
			}
			return tx.Delete(claim)
		})
		if err != nil {
			app.Logger().Error("expiring a stale claim", "claim", claim.Id, "error", err)
			continue
		}
		expired++
		// After the release commits, never inside it (LLL-452): the claim is
		// already gone, so a comment that cannot be written must not roll the
		// release back and hand the same claim to the next sweep forever.
		announceExpiry(app, announce, claim, now)
	}
	return expired, nil
}

// announceExpiry leaves the record of a release on the issue itself (LLL-452).
//
// The first sweep on the hosted board released 123 claims and nothing said so;
// the board simply stopped reporting those issues as held. A comment is the
// cheapest honest record, and it goes only on issues somebody might still come
// back to: 119 of those 123 were holds on FINISHED work, where a note would be
// noise on an issue nobody is reading.
//
// The comment has no author. The sweep is not a member and must not mint one -
// LLL-374 is the board with 68 synthetic identities on it - so the body names
// the holder instead, and reads correctly under the "anon" the web renders for
// an authorless comment.
func announceExpiry(app core.App, issue *core.Record, claim *core.Record, now time.Time) {
	if issue == nil {
		return
	}
	switch issue.GetString("state") {
	case "done", "cancelled":
		return
	}

	holder := "an unknown member"
	if member, err := app.FindRecordById("members", claim.GetString("member")); err == nil {
		if name := member.GetString("name"); name != "" {
			holder = name
		}
	}

	comments, err := app.FindCollectionByNameOrId("comments")
	if err != nil {
		app.Logger().Error("announcing a claim expiry", "claim", claim.Id, "error", err)
		return
	}
	comment := core.NewRecord(comments)
	comment.Set("issue", issue.Id)
	comment.Set("body", fmt.Sprintf(
		"Claim released automatically: %s had held it for %s with no activity on the board. "+
			"`lll issue claim` takes it again.",
		holder, roundedAge(claim.GetDateTime("created").Time(), now),
	))
	if err := app.Save(comment); err != nil {
		// Logged, not returned: the release already happened, and the caller
		// counting expiries must not learn about it from a comment failure.
		app.Logger().Error("announcing a claim expiry", "claim", claim.Id, "error", err)
	}
}

// roundedAge is how long a claim stood, in the coarsest unit that is still
// true: "25 hours", "3 days". A reader deciding whether to take the issue back
// does not need the minutes, and a precise duration in a comment invites
// arithmetic nobody asked for.
func roundedAge(created, now time.Time) string {
	hours := int(now.Sub(created).Hours())
	if hours < 48 {
		if hours == 1 {
			return "1 hour"
		}
		return fmt.Sprintf("%d hours", hours)
	}
	return fmt.Sprintf("%d days", hours/24)
}
