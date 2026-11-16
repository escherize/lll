# CI and deployment

Every pull request and main push runs the macOS compiler, unit and full
end-to-end gate with pinned Playwright CLI and its matching bundled Chromium
installed. The gate runs as parallel jobs on separate runners: unit tests,
the core end-to-end script, the binary-only suites with the `lll up` suite,
and the web board suite. With the deployment context that is five macOS jobs,
the most GitHub runs at once on its hosted macOS runners. Together they run what
`mise run gate` runs locally; `scripts/test_ci_parts.py` fails when a part is
missing from the workflow. A job named `gate` passes only when every part and
the deployment context pass.

The browser cache has an explicit job-local path so fixture HOME isolation
does not hide it. `scripts/browser-ci.json` selects that browser. Missing browser tooling
fails the job.

A separate macOS job runs `scripts/prepare-deploy-context.sh`, which archives
the exact checked-out HEAD, emits Go and makes module replacements relative.
It starts with the gate rather than after it, so the Linux job does not wait
for the macOS tests.
The uploaded archive contains everything needed for a Linux build; it does
not contain a developer database, home configuration or `.private` history.

The Linux job builds the production Dockerfile, extracts its static binary,
and runs the existing board suite with `--prebuilt BINARY --require-browser`.
This includes opening the board, observing a CLI-created card without reload,
and the other browser, draft, claim and attachment regressions. Linux needs
no Lisette installation. A failure blocks deployment.

Successful main pushes deploy that same source context to Fly, after the
`gate` job and the Linux job both pass. PRs never
deploy. Main runs are serialized so a newer push cannot cancel a rollout.
Fly rebuilds the verified context on its remote builder.

One-time repository setup: configure `FLY_API_TOKEN` in GitHub Actions secrets
with an app-scoped deploy token for the app in `fly.toml`. Generate it with
`fly tokens create deploy --app escherize-lll --expiry 8760h`, then enter it through GitHub's
secret UI or pipe it into `gh secret set FLY_API_TOKEN`. Do not commit tokens.
Without the secret, the deployment job fails with a setup instruction; the
build and browser evidence remains available.

For a manual deployment, run `mise exec -- bash scripts/fly-deploy.sh` from a
committed checkout. It uses the same context preparation and cleans up its
temporary context when Fly exits. Both paths deploy committed HEAD; local
uncommitted edits are excluded. Keep the volume and restore procedure in
[hosted-recovery.md](hosted-recovery.md) in place before deploying migrations.

Tagged release binaries remain a separate workflow. The server must ship
before clients that require its new claim/assignment endpoints (LLL-276).
