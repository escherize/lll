package gopb

import (
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

// expireClaims deletes every claim older than maxAge and returns how many went.
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
		"claims", "created < {:cutoff}", "created", 0, 0,
		dbx.Params{"cutoff": cutoff},
	)
	if err != nil {
		return 0, err
	}

	expired := 0
	for _, claim := range stale {
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
			}
			return tx.Delete(claim)
		})
		if err != nil {
			app.Logger().Error("expiring a stale claim", "claim", claim.Id, "error", err)
			continue
		}
		expired++
	}
	return expired, nil
}
