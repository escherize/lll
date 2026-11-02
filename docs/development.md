# Developing lll

Install the Lisette toolchain, then let mise provision Go and jq and start the
board:

```sh
curl -LsSf https://github.com/ivov/lisette/releases/latest/download/lisette-installer.sh | sh
mise install && mise run dev
```

```sh
mise run build     # binary at target/.lisette/bin/lll
mise run test      # unit tests
mise run e2e       # full e2e: CLI + watch + web board + lll up
mise run gate      # build, test and e2e: what a change must pass to land
```

Markup and CSS are embedded, so edits need a rebuild.
`mise run scratch -- --no-open` starts an isolated test board.

Layout: `src/` is the Lisette source (`commands/` has one file per noun),
`pb/` the PocketBase schema and migrations, `gopb/` the Go module embedding
PocketBase, and `web/` the templates and CSS.

Related references: [api.md](api.md) (the board API),
[claim-transactions.md](claim-transactions.md) (claim operations),
[ci-deployment.md](ci-deployment.md) (CI and deployment),
[hosted-recovery.md](hosted-recovery.md) (database recovery) and
[export-mirror.md](export-mirror.md) (`lll export`).

## Architecture

```
lll CLI ── REST ──> PocketBase (embedded; sqlite + migrations)
                        │ realtime SSE (JSON records)
browser <── HTML/SSE ── lll up web board (Datastar fragment morphing)
```

The CLI calls PocketBase's REST API with no SDK. The board holds one
PocketBase realtime subscription and pushes re-rendered fragments to each
page over SSE; [Datastar](https://data-star.dev) morphs them into the DOM.

lll is written in [Lisette](https://github.com/ivov/lisette), which compiles
to Go. The binary embeds PocketBase, the schema migrations and the web assets.
