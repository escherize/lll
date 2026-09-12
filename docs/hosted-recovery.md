# Hosted database recovery

Maintain this procedure in `docs/hosted-recovery.md` and publish that file's
contents to the hosted `hosted-recovery` wiki document. The repository copy
is available when the board is down; do not maintain two independent versions.

Owner: the project maintainer (Bryan Maass), using the Fly account with machine,
volume and SSH access to `escherize-lll`. Recovery requires Fly access and this
runbook; it does not require the primary lll server to answer. Keep Fly account
recovery credentials in the account's credential manager, never in this repo
or an lll document. Another operator needs the same Fly organization permissions.

The durability strategy is Fly volume snapshots. A scheduled Git/Markdown
export is optional offline access, not a prerequisite or a replacement for
restoring the database. The old `.private` repository remains read-only history.

## Find the recovery point

```sh
fly machine list --app escherize-lll --json
fly volumes list --app escherize-lll --json
fly volumes snapshots list VOLUME_ID --app escherize-lll --json
```

Select the volume mounted by the production machine, not an unattached volume
with the same name. Confirm automatic backups and retention from the live
response. Select a snapshot whose status is `created`, record its timestamp
and ID, and record the deployed image and machine configuration. Snapshot
list order is not a recency guarantee; compare `created_at` values.

If the primary is unavailable, these Fly control-plane operations still give
the recovery inputs. The September 12 drill used the already deployed image;
it did not require a new build or a functioning primary database.

## Restore without accepting production traffic

Create a new volume from the selected snapshot; do not restore over the
production volume:

```sh
fly volumes create lll_restore --app escherize-lll --region ord --size 1 \
  --snapshot-id SNAPSHOT_ID --scheduled-snapshots=false --json --yes
```

Use the returned new volume ID. Size must be at least the source volume's
size. Save a minimal temporary Fly configuration containing only:

```toml
app = "escherize-lll"
primary_region = "ord"
```

Start the deployed image with a sleeping command and no services. Supplying
the minimal config prevents inheriting the public services from `fly.toml`:

```sh
fly machine run DEPLOYED_IMAGE sleep infinity --app escherize-lll \
  --config /tmp/lll-restore.toml --name lll-restore --region ord \
  --volume RESTORE_VOLUME_ID:/data/pb_data --vm-memory 256 --restart no \
  --skip-dns-registration --detach
fly machine list --app escherize-lll --json
```

Before starting lll, verify the new machine's services are empty, DNS
registration is skipped, and its mount names only the restored volume. Use
the new machine ID explicitly on every subsequent command.

Connect to that machine:

```sh
fly ssh console --app escherize-lll --machine RESTORE_MACHINE_ID
```

Inside it, use a temporary HOME and a clean environment to avoid inheriting
production URL settings or identities. Start the image's binary against the
restored mount with `LLL_URL=http://127.0.0.1:8090`, `LLL_BIND=127.0.0.1`,
`LLL_TEAM=LLL`, and temporary `LLL_ADMIN_EMAIL` / `LLL_ADMIN_PASSWORD` values:

```sh
mkdir -p /tmp/restore-home
# Set the two temporary admin values before this command. They apply only
# to the restored database; never change a historical member's password.
env -i PATH="$PATH" HOME=/tmp/restore-home \
  LLL_URL=http://127.0.0.1:8090 LLL_BIND=127.0.0.1 LLL_TEAM=LLL \
  LLL_ADMIN_EMAIL="$LLL_ADMIN_EMAIL" LLL_ADMIN_PASSWORD="$LLL_ADMIN_PASSWORD" \
  /app/target/.lisette/bin/lll up --no-open --pb-dir /data/pb_data --port 8100 \
  >/tmp/restore.log 2>&1 &
curl -sf http://127.0.0.1:8090/api/health
```

Wait for health to succeed; inspect `/tmp/restore.log` if startup fails.
The process listens only on the machine's loopback interface. Do not add public
services for a drill. Use SSH-local curl and CLI commands for verification.

## Verify before deciding to cut over

- Authenticate the temporary superuser through
  `/api/collections/_superusers/auth-with-password` and retain the returned
  token only in the operator's process memory/environment.
- Read teams, issues, docs and comments through `/api/collections/NAME/records`.
  Record counts, sample issue keys and their data. Expand issue teams,
  document issues and comment issues to confirm relations still resolve.
- Create a disposable member only in the restored database and run the real
  `lll login --url http://127.0.0.1:8090 --email ...` flow with a temporary
  HOME. Verify `lll whoami` and a representative `lll issue view KEY`.
- If available, verify an existing member's token against the restored
  database too. Do not print tokens or copy them into the runbook.
- Record the snapshot timestamp, verification time, observed duration and
  expected loss of writes since the recovery point. Do not describe snapshot
  age as zero data loss or a measured drill duration as a guaranteed RTO.

For an actual outage, the owner must select the recovered database as the
new authoritative copy and arrange a single active writer before applying
the public service configuration to the replacement. Preserve the original
volume for investigation. The drill below did not exercise traffic cutover
or automatic failover; it verified the restored database and application.

For a drill, remove only the temporary resources, in this order:

```sh
fly machine destroy RESTORE_MACHINE_ID --app escherize-lll --force
fly volumes destroy RESTORE_VOLUME_ID --app escherize-lll --yes
fly machine list --app escherize-lll --json
fly volumes list --app escherize-lll --json
```

Confirm both temporary IDs are gone and production configuration is unchanged.

## Verified drill: September 12, 2026 (LLL-274)

- Production: machine `080d290a0d7318`, encrypted 1 GiB volume
  `vol_r68dmpqeo8m23k14`, region `ord`. Automatic backups enabled, retention
  30 days, 11 completed snapshots observed. An unrelated unattached volume
  had 5-day retention and was not used or changed.
- Recovery point: `vs_kwXyDeQJ7YZi7wL23R8L`, September 11 at 13:05:05 UTC.
- Image: `registry.fly.io/escherize-lll:deployment-01M224MZHW5GGR1WY8J2PEXG8A`
  (digest `sha256:80798a89f5ac1812fe2a08473af64f2f3f30b57df45796ad113f2f3fd1e30480`).
- Restore volume created at 08:19:23 UTC; initial verification completed at
  08:23:08 UTC, approximately 3 minutes 45 seconds later. Recovery point age
  was approximately 19 hours 18 minutes. This was an operator-driven drill.
- Restored contents: 348 issues, 125 docs, 24 comments. Five sampled issue/team
  relations, five comment/issue relations and the linked doc/issue relation
  in the document sample resolved. `LLL-274` was readable through the CLI.
- Disposable member password login and `whoami` passed. The existing
  `bryan.maass` token also authenticated against the restored member records.
- Temporary machine `784ed161f97d28` and volume `vol_re1kzme3p79z06o4` were
  destroyed after verification. Production configuration was unchanged.
