#!/usr/bin/env bash
# e2e: `lll up` — one-command runner. Covers: booting its own in-process PB
# (isolated --pb-dir, auto-increment from a taken configured port), the logged
# default admin creds working against the admin API, web-port auto-increment
# with the move printed, SIGINT stopping both servers (one process now: PB
# shuts down gracefully, taking the board with it), and the reuse path (a
# healthy external PB at the configured URL is used, not restarted, and
# survives lll up's exit; that external PB is a second lll up instance), and
# first-boot identity (me guessed from $USER, written to the HOME config —
# never the repo's committed .lll.toml — seeded as a member, and not
# re-guessed once configured), and the TASK-182 board gate: with no
# LLL_BOARD_TOKEN the boot generates one, prints its login URL in the banner,
# and refuses every anonymous request with a 401 that names the fix.
#
# Every lll up here runs with HOME="$E2E_HOME": a first boot writes 'me' to
# the home config now (TASK-168), and a suite must not rewrite the
# developer's own.
set -euo pipefail
. "$(dirname "$0")/lib.sh"   # free_port, wait_ok, fail, assert_*, e2e_begin/end
e2e_begin

DB_PORT=$(free_port 20000 39999)
WEB_PORT=$(free_port 40000 59999)
UP_LOG="$DATA_DIR/up.log"
E2E_LOGS="$UP_LOG"

cleanup() { # exit-status
  # Diagnose first: e2e_diagnose reads the logs, and e2e_end deletes the
  # directory they live in (TASK-121). e2e_reap kills AND waits, so the
  # servers are gone before their --pb-dir is (TASK-153) - this suite runs
  # two `lll up` processes at once, and it is the one whose orphans were
  # actually observed still holding their ports minutes later.
  e2e_diagnose "$1"
  e2e_reap "${UP_PID:-}" "${BLOCK_PID:-}" "${EXT_PB_PID:-}" "${OUTSIDE_PID:-}"
  e2e_end
}
e2e_trap_cleanup cleanup

lis build >/dev/null
LLL=target/.lisette/bin/lll
LLL_ABS="$PWD/$LLL"

# Occupy the configured db port and the web port so both must auto-increment.
python3 -c "
import socket, time
s1 = socket.socket(); s1.bind(('127.0.0.1', $DB_PORT)); s1.listen(1)
s2 = socket.socket(); s2.bind(('127.0.0.1', $WEB_PORT)); s2.listen(1)
time.sleep(60)
" &
BLOCK_PID=$!
sleep 0.5

# --- own path: boots PB on DB_PORT+1, board on WEB_PORT+1, default creds ---
set -m
env -u LLL_ADMIN_EMAIL -u LLL_ADMIN_PASSWORD -u LLL_TOKEN \
  LLL_URL="http://127.0.0.1:$DB_PORT" LLL_TEAM=E2E USER=e2euser HOME="$E2E_HOME" \
  "$LLL" up --no-open --port "$WEB_PORT" --pb-dir "$DATA_DIR/pb_data" >"$UP_LOG" 2>&1 &
UP_PID=$!
set +m

DB2=$((DB_PORT + 1)); WEB2=$((WEB_PORT + 1))
wait_ok "http://127.0.0.1:$DB2/api/health" || fail "own PB not on incremented port $DB2"

# --- TASK-182: no LLL_BOARD_TOKEN here — the boot generates one per boot and
# prints its login URL in the banner. Parse it out; the gate refuses every
# other request, so the suite's own liveness probes must log in like a
# browser does.
BOARD_TOKEN=""
for _ in $(seq 1 100); do
  BOARD_TOKEN=$(sed -n 's/.*[?&]board_token=\([^ )]*\).*/\1/p' "$UP_LOG" | head -1)
  [ -n "$BOARD_TOKEN" ] && break
  sleep 0.1
done
[ -n "$BOARD_TOKEN" ] || fail "banner did not print a board login URL"
BOARD_COOKIE="Cookie: lll_board=$BOARD_TOKEN"
anon=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$WEB2/")
[ "$anon" = "401" ] || fail "anonymous board fetch: expected 401, got $anon"
anon_page=$(curl -s "http://127.0.0.1:$WEB2/")
printf '%s' "$anon_page" | grep -q "board_token" || fail "401 page does not say how to get in"
curl -sf -H "$BOARD_COOKIE" "http://127.0.0.1:$WEB2/" >/dev/null || fail "board not on incremented port $WEB2"
grep -q "admin@local.dev / admin-local-123" "$UP_LOG" || fail "default creds not logged"
grep -q "port $WEB_PORT taken" "$UP_LOG" || fail "web port move not printed"
curl -sf -X POST "http://127.0.0.1:$DB2/api/collections/_superusers/auth-with-password" \
  -H 'Content-Type: application/json' \
  -d '{"identity":"admin@local.dev","password":"admin-local-123"}' >/dev/null \
  || fail "default admin creds do not authenticate"

# TASK-181: the rules are authenticated-only, and the boot says so: up
# applied the superuser token to its own process (seeding + the board's
# server-side writes — the TASK-182 handoff), and the CLI side of this suite
# rides a member token from the same server.
grep -q "auth   rules are authenticated-only" "$UP_LOG" \
  || fail "lll up did not apply the superuser token to its own process"
E2E_TOKEN=$(pb_member_token "http://127.0.0.1:$DB2" e2e-up e2e-up@lll.test e2e-up-pass-123) \
  || fail "bootstrapping the e2e_up member token"
export LLL_TOKEN="$E2E_TOKEN"
AUTH_HDR="Authorization: Bearer $E2E_TOKEN"

# --- first boot settles an identity without asking (task-31) ---
grep -q 'guessed me = "e2euser" from $USER' "$UP_LOG" || fail "first boot did not guess me from \$USER"
grep -q 'created member e2euser' "$UP_LOG" || fail "first boot did not seed the member"
grep -q '^me     e2euser' "$UP_LOG" || fail "first boot did not print me"
# The HOME config, not the repo's: .lll.toml is committed now (TASK-168), and
# booting a server must not put a username into someone else's checkout.
HOME_TOML="$E2E_HOME/.config/lll/lll.toml"
grep -q 'me = "e2euser"' "$HOME_TOML" \
  || fail "me not written to the home config: $(cat "$HOME_TOML" 2>&1)"
[ ! -e .lll.toml ] || fail "first boot wrote the repo's .lll.toml: $(cat .lll.toml)"
curl -sf -H "$AUTH_HDR" "http://127.0.0.1:$DB2/api/collections/members/records?filter=name%3D%27e2euser%27" \
  | grep -q '"name":"e2euser"' || fail "seeded member not in the members collection"

# The seeded member is usable as an assignee straight away: the point of it.
out=$(LLL_URL="http://127.0.0.1:$DB2" LLL_TEAM=E2E \
  "$LLL" issue create -t "assign on first boot" --assignee e2euser)
printf '%s' "$out" | grep -q "Created E2E-" || fail "assignment to the seeded member failed: $out"

# SIGINT: the board and the in-process PB must both die with the process.
# The up may have already exited (it has after the banner, twice on loaded
# runners — TASK-153's orphan class): a kill of nothing is success, the
# assertion below judges whether the external PB outlived it.
kill -INT -- "-$UP_PID" 2>/dev/null || kill -INT "$UP_PID" 2>/dev/null || true
for _ in $(seq 1 50); do
  curl -sf -H "$BOARD_COOKIE" "http://127.0.0.1:$WEB2/" >/dev/null 2>&1 || break
  sleep 0.1
done
curl -sf -H "$BOARD_COOKIE" "http://127.0.0.1:$WEB2/" >/dev/null 2>&1 && fail "board survived SIGINT"
curl -sf "http://127.0.0.1:$DB2/api/health" >/dev/null 2>&1 && fail "in-process PB survived SIGINT"
UP_PID=""

# --- reuse path: healthy PB at the configured URL is used, and outlives up ---
EXT_PORT=$((DB_PORT + 5))
# A genuinely separate server, so the reuse path is tested against a PocketBase
# this `lll up` did not start: a second lll up, its own process and data dir.
EXT_WEB=$((WEB_PORT + 7))
env -u LLL_TOKEN LLL_URL="http://127.0.0.1:$EXT_PORT" LLL_TEAM=E2E HOME="$E2E_HOME" \
  "$LLL_ABS" up --no-open --port "$EXT_WEB" --pb-dir "$DATA_DIR/ext_pb_data" \
  </dev/null >/dev/null 2>&1 &
EXT_PB_PID=$!
wait_ok "http://127.0.0.1:$EXT_PORT/api/health" || fail "the external PB never came up"
set -m
env -u LLL_TOKEN LLL_URL="http://127.0.0.1:$EXT_PORT" LLL_TEAM=E2E HOME="$E2E_HOME" \
  "$LLL" up --no-open --port "$WEB_PORT" --pb-dir "$DATA_DIR/pb_data" >"$UP_LOG" 2>&1 &
UP_PID=$!
set +m
BOARD_TOKEN2=""
for _ in $(seq 1 100); do
  BOARD_TOKEN2=$(sed -n 's/.*[?&]board_token=\([^ )]*\).*/\1/p' "$UP_LOG" | head -1)
  [ -n "$BOARD_TOKEN2" ] && break
  sleep 0.1
done
[ -n "$BOARD_TOKEN2" ] || fail "the reuse boot did not print a board login URL"
curl -sf -H "Cookie: lll_board=$BOARD_TOKEN2" "http://127.0.0.1:$WEB2/" >/dev/null \
  || fail "reuse-path board not serving (or gate broke)"
grep -q "(already running)" "$UP_LOG" || fail "reuse path not taken"
grep -q "auth   rules are authenticated-only" "$UP_LOG" \
  || fail "the reuse path did not authenticate against the external server"
# The home config now names me, so a later boot must use it, not guess again.
grep -q "guessed me" "$UP_LOG" && fail "me re-guessed with one already configured"
grep -q "^me     e2euser" "$UP_LOG" || fail "configured me not used on a later boot"
# The up may have already exited (it has after the banner, twice on loaded
# runners — TASK-153's orphan class): a kill of nothing is success, the
# assertion below judges whether the external PB outlived it.
kill -INT -- "-$UP_PID" 2>/dev/null || kill -INT "$UP_PID" 2>/dev/null || true
sleep 0.5
UP_PID=""
curl -sf "http://127.0.0.1:$EXT_PORT/api/health" >/dev/null \
  || fail "external PB was killed by lll up's exit"

# --- outside the checkout: BOOTS, because the migrations ship in the binary ---
# task-30 asserted the opposite here: `lll up` outside the checkout had to fail
# fast, naming pb/pb_migrations, rather than boot a database with no collections
# whose first API call returned 404 "Missing collection context". TASK-80 keeps
# that goal and removes the need for the guard - pb/embed.go carries the
# migrations, so there is no directory to be missing. The property under test is
# unchanged (never an unmigrated database); only the mechanism moved, so the
# assertion is inverted rather than deleted.
OUTSIDE="$DATA_DIR/outside"
mkdir -p "$OUTSIDE"
# Two ports, because they are two servers: --port is the BOARD, and PocketBase
# takes the one LLL_URL names. Passing one number for both makes `lll up` print
# "port N taken - board moving to N+1" and the assertions then talk to whichever
# server answered first.
OUT_PB_PORT=$(free_port 40000 49999)
OUT_WEB_PORT=$(free_port 50000 59999)
OUT_URL="http://127.0.0.1:$OUT_PB_PORT"
OUT_LOG="$DATA_DIR/outside.log"
# `env -u LLL_TOKEN` like the blocks above: the suite is still carrying a token
# minted against an EARLIER PocketBase, and this boot is a different server. A
# stale token does not fail as an auth error - `up` gets refused while seeding
# and reports "could not create team 'E2E' and none exists to reuse", which
# names the team and never mentions auth. Filed separately; here, just do not
# hand it a token from another database.
# TASK-250: `exec`, so $! is the SERVER and not the subshell wrapping it.
# Without it, e2e_reap killed the subshell and left `lll up` running with a
# --pb-dir that e2e_end then deleted — orphans holding ports indefinitely,
# four of them found alive on a developer machine after a day of runs.
( cd "$OUTSIDE" && exec env -u LLL_TOKEN LLL_TEAM=E2E HOME="$E2E_HOME" LLL_URL="$OUT_URL" \
    "$LLL_ABS" up --no-open --port "$OUT_WEB_PORT" --pb-dir "$OUTSIDE/pb_data" </dev/null ) \
  >"$OUT_LOG" 2>&1 &
OUTSIDE_PID=$!
wait_ok "$OUT_URL/api/health" 150 \
  || fail "lll up outside the checkout should boot now that migrations are embedded: $(cat "$OUT_LOG")"
# Migrated, not merely listening: an empty database answers /api/health too, and
# a collection query is what task-30's 404 actually came from.
out=$(curl -sf "$OUT_URL/api/collections/teams/records" \
  -H "Authorization: Bearer $(pb_superuser_token "$OUT_URL")" 2>&1) \
  || fail "the teams collection should exist outside the checkout, got: $out (log: $(cat "$OUT_LOG"))"
printf '%s' "$out" | grep -qF "Missing collection context" \
  && fail "booted unmigrated outside the checkout: $out"
e2e_reap "$OUTSIDE_PID"

echo "e2e_up: all assertions passed"
