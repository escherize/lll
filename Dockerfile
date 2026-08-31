# TASK-171: the container lll runs in on Fly. The image carries the checkout,
# not just the binary: `lll up` reads pb/pb_migrations and pb/pb_hooks from
# disk relative to the WORKDIR, so those paths must exist at runtime.
#
# Deploy (bcm, needs the Fly account):
#   fly apps create <app>
#   fly volumes create lll_data --size 3 --region <region>
#   fly secrets set LLL_TEAM=<key> LLL_ADMIN_EMAIL=<email> LLL_ADMIN_PASSWORD=<pw>
#   fly deploy
# The volume mounts at /data/pb_data (see fly.toml) — without it, every deploy
# wipes the backlog (the single most common way to lose everything here).

# --- build stage: compile lll with the pinned lis toolchain ---
FROM golang:1.27-alpine AS build
RUN apk add --no-cache curl git
# lis via the upstream installer (not a mise plugin; see mise.toml).
RUN curl -LsSf https://github.com/ivov/lisette/releases/download/lisette-v0.11.3/lisette-installer.sh | sh
WORKDIR /src
COPY . .
# TASK-168: a first boot writes 'me' to the home config, never the repo's
# committed .lll.toml; the build itself needs no config.
RUN lis build

# --- runtime stage: the checkout paths + the built binary ---
FROM alpine:3.20
RUN apk add --no-cache ca-certificates curl
COPY --from=build /src /app
COPY --from=build /root/.local/bin/lis /usr/local/bin/lis
WORKDIR /app
# The binary is rebuilt at boot so the checkout and the binary cannot drift.
RUN true

ENV LLL_BIND=0.0.0.0
# LLL_TEAM / LLL_ADMIN_EMAIL / LLL_ADMIN_PASSWORD come from fly secrets.
EXPOSE 8090 8100

# data on a Fly volume: one sqlite on one volume is the durability story;
# bin/lll-export on a timer pushing the mirror to git is the backup.
VOLUME /data/pb_data
CMD ["sh", "-c", "target/.lisette/bin/lll up --no-open --pb-dir /data/pb_data --port 8100"]
