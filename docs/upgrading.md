# Predictable client and server upgrades

The CLI and the server are separate binaries. A version-skew warning is
advice, not a compatibility handshake. A Homebrew client may update itself
when its server is newer ([auto-update](cli-contract.md#version-skew-and-auto-update));
a server never does. The covered
1.x CLI spellings, exit codes and JSON fields are in [the contract](cli-contract.md).
A stable CLI contract does not promise that an older server implements every
new capability. Consumers should ignore additional fields and event topics.

## Capability boundaries

| Capability | Client requirement | Server requirement |
|---|---|---|
| Covered 1.x issue reads, relation ids and claim holder | 1.x | A tested 1.x server pair; use the rehearsal below |
| Keyed issue creation | Client with `issue create --idempotency-key` | Authenticated `/api/lll/issues/idempotency` says supported |
| Keyed comments | Client with `issue comment --idempotency-key` | Authenticated `/api/lll/comments/idempotency` says supported; 1.1.0 lacks this route |
| Comment and claim events on query watch | Client with `watch --activity` | Native PocketBase topics; older servers lack reliable claim actor metadata |
| Attributed claim events and comment/claim webhooks | `webhook add --activity`; activity-aware consumer | Server with the claim-actor migration and activity webhook hooks |

Activity is opt-in. Plain watch and existing webhook registrations remain
issue-only. Use `watch --activity` or register a receiver with
`webhook add URL --activity`. New activity webhook registrations check the
authenticated `/api/lll/activity` capability before any POST; an older server
is refused rather than silently creating an issue-only registration.

The server lists what it supports in `GET /.well-known/lll` (`capabilities`),
and the CLI refuses a command whose capability is missing before it writes.
A server without the list (1.1.0 and older, or a board started over an
adopted API) is asked through each feature's support route instead; see [Server capabilities](cli-contract.md#server-capabilities).

Features described in Unreleased may be deployed on main before a published
CLI includes their flags. Check the installed help and the server's
capability list; equal version strings alone do not prove equal capabilities.

An unsupported keyed write is refused **before the POST**. Do not remove the
key and retry automatically: that would give up the duplicate-write guarantee.
A newer watcher must treat an old server's missing release actor as unknown,
not infer that the holder released the claim. Watch is live-only: reconnects
do not replay gaps. `issue list --since` does not catch comment/claim-only
activity; re-read comments and claims when reconciling a complete snapshot.

## Record tested pairs, not a blanket compatibility claim

For each release, retain a report with the exact before/after binary hashes.
`version` alone is insufficient: a candidate may still print the current
release version while containing new commits.

| Client | Server | Rehearsal checks |
|---|---|---|
| Before | Before | Baseline authentication, issue fields, project/label relations, claim and comment |
| After | Before | The same reads; keyed comment safely refused when support is absent |
| Before | After | Existing reads and unkeyed comment creation |
| After | After | Existing reads and keyed comment retry returns the same record |
| Before | Restored before-data backup | Original member token and original data work; later writes are absent |

These rows define the probe, not a claim that all commands or all 1.x pairs
have been tested. The report names the tested binaries and outcomes. It does
not exercise a downstream fleet kit, worker provisioning or production data.

## Rehearse with two explicit binaries

Download the published baseline outside the checkout and build the candidate
through the normal verification gate. Then run:

```sh
python3 scripts/rehearse_upgrade.py \
  --before /path/to/published-lll \
  --after /path/to/candidate-lll \
  --report /tmp/lll-upgrade-report.json
```

The script accepts no service URL or database path. It clears inherited lll
and XDG settings, uses a temporary HOME and loopback listeners, creates only
synthetic records, stops the old server before copying its data, starts the
candidate on that data, and finally starts the old binary on a separate copy
of the pre-upgrade backup. It stops only its own processes and removes its
own temporary data. The report contains versions, binary hashes and checks,
never credentials. Exit 0 means every check passed; an assertion is a failed
rehearsal and should block that release until understood.

## Operator window

1. Declare the exact server/client cut and read its migration and compatibility
   notes. Stop writers and long-running watchers for the upgrade window.
2. Stop the server. Back up the complete data directory (or a consistent volume
   snapshot), keep the previous binary/image and record the restore command.
3. Replace the server binary using a new file followed by rename; never overwrite
   the executable used by running processes. Start the server once, let its
   embedded migrations finish, and verify health plus an authenticated read.
4. Upgrade clients. Reauthenticate if instructed and restart watchers with a
   fresh snapshot, since live streams have no replay guarantee.
5. Record the deployed server version, installed client versions and the probe
   results. A newer-client warning alone proves none of these steps.

If rollback is needed, stop the new server. Do not run the old binary against
an already-migrated database unless a specific downgrade has been tested.
Restore the complete stopped pre-upgrade backup and start its matching old
binary/image. Writes made after the backup will be absent: preserve them
separately before restoring if they are needed. Never run two servers on one
database. For hosted volume recovery use [the recovery runbook](hosted-recovery.md).
Never move a published release tag to repair an upgrade; ship a patch instead.
