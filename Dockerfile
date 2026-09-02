# TASK-171: the container lll runs in on Fly. The image carries the checkout
# rather than just the binary, for the web assets' sake; pb_migrations no longer
# needs it. TASK-80 embedded them in the binary (pb/embed.go) and `lll up`
# unpacks them into the data dir on boot, so no pb/ path has to exist at
# runtime. (pb/pb_hooks named here has not existed for a while either - those
# hooks are Go now, in gopb.)
#
# The build stage is PLAIN `go build` over Go that `lis emit` produced on the
# deploying machine — lis never runs in the container, because lis (0.11.3 and
# 0.12.0) cannot bindgen on linux: typedef generation fails for x/term, the
# local path modules, and goldmark-highlighting (finding filed 2026-08-31).
# Consequence: DO NOT `fly deploy` from the checkout — the context must carry
# a fresh `target/` emit with relative replace paths. scripts/fly-deploy.sh
# builds that context; use it.
#
# Deploy (bcm, needs the Fly account):
#   fly apps create <app>
#   fly volumes create lll_data --size 3 --region <region>
#   fly secrets set LLL_TEAM=<key> LLL_ADMIN_EMAIL=<email> LLL_ADMIN_PASSWORD=<pw>
#   fly ips allocate-v4 -a <app>   # dedicated IPv4 (~$2/mo): the tls+http
#                                  # :8091 stanza in fly.toml rides only this
#   scripts/fly-deploy.sh
# The hosted PocketBase API is then https://<app>.fly.dev:8091 (what
# 'lll login --url' and LLL_URL take); the board stays on 443.
# The volume mounts at /data/pb_data (see fly.toml) — without it, every deploy
# wipes the backlog (the single most common way to lose everything here).

# --- build stage: plain go build of the pre-emitted Go ---
# go.mod says `go 1.27`, so the toolchain must be at least that even though
# lis itself runs go 1.25.
FROM golang:1.27-alpine AS build
COPY . /src
WORKDIR /src/target
RUN go build -o .lisette/bin/lll .

# --- runtime stage: the checkout paths + the built binary ---
FROM alpine:3.20
RUN apk add --no-cache ca-certificates curl
COPY --from=build /src /app
WORKDIR /app

ENV LLL_BIND=0.0.0.0
# LLL_TEAM / LLL_ADMIN_EMAIL / LLL_ADMIN_PASSWORD come from fly secrets.
EXPOSE 8090 8100

# data on a Fly volume: one sqlite on one volume is the durability story;
# bin/lll-export on a timer pushing the mirror to git is the backup.
VOLUME /data/pb_data
CMD ["sh", "-c", "target/.lisette/bin/lll up --no-open --pb-dir /data/pb_data --port 8100"]
