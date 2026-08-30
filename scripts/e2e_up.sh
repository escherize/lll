#!/usr/bin/env bash
# e2e: `lll up` — one-command runner. Covers: booting its own in-process PB
# (isolated --pb-dir, auto-increment from a taken configured port), the logged
# default admin creds working against the admin API, web-port auto-increment
# with the move printed, SIGINT stopping both servers (one process now: PB
# shuts down gracefully, taking the board with it), and the reuse path (a
# healthy external PB at the configured URL is used, not restarted, and
# survives lll up's exit; that external PB is a second lll up instance), and
# first-boot identity (me guessed from $USER, written to .lll.toml, seeded as
# a member, and not re-guessed once configured).
set -euo pipefail
cd "$(dirname "$0")/.."

# A random port that is actually free. Binding proves it, unlike a liveness
# probe: an occupied port makes a health poll succeed against a STRANGER's
# server, and the suite then dies much later naming something unrelated.
free_port() { # low high
  python3 -c '
import random, socket, sys
lo, hi = int(sys.argv[1]), int(sys.argv[2])
for _ in range(200):
    p = random.randint(lo, hi)
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", p))
    except OSError:
        continue
    finally:
        s.close()
    print(p)
    sys.exit(0)
sys.exit("no free port in range")
' "$1" "$2"
}



DATA_DIR="$(mktemp -d)"

# Hermetic: a developer's repo-root .lll.toml must not leak into assertions.
if [ -f .lll.toml ]; then
  mv .lll.toml "$DATA_DIR/.lll.toml.saved"
  RESTORE_TOML=1
fi
DB_PORT=$(free_port 20000 39999)
WEB_PORT=$(free_port 40000 59999)
UP_LOG="$DATA_DIR/up.log"

cleanup() {
  # A first boot writes one; the developer's own file goes back on top.
  rm -f .lll.toml
  if [ "${RESTORE_TOML:-}" = 1 ] && [ -f "$DATA_DIR/.lll.toml.saved" ]; then
    mv "$DATA_DIR/.lll.toml.saved" .lll.toml
  fi
  kill "${UP_PID:-}" "${BLOCK_PID:-}" "${EXT_PB_PID:-}" 2>/dev/null || true
  rm -rf "$DATA_DIR"
}
trap cleanup EXIT
fail() { echo "FAIL: $1" >&2; tail -20 "$UP_LOG" >&2 || true; exit 1; }

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
env -u LLL_ADMIN_EMAIL -u LLL_ADMIN_PASSWORD \
  LLL_URL="http://127.0.0.1:$DB_PORT" LLL_TEAM=E2E USER=e2euser \
  "$LLL" up --no-open --port "$WEB_PORT" --pb-dir "$DATA_DIR/pb_data" >"$UP_LOG" 2>&1 &
UP_PID=$!
set +m

DB2=$((DB_PORT + 1)); WEB2=$((WEB_PORT + 1))
for _ in $(seq 1 100); do
  curl -sf "http://127.0.0.1:$WEB2/" >/dev/null 2>&1 && break
  sleep 0.1
done
curl -sf "http://127.0.0.1:$DB2/api/health" >/dev/null || fail "own PB not on incremented port $DB2"
curl -sf "http://127.0.0.1:$WEB2/" >/dev/null || fail "board not on incremented port $WEB2"
grep -q "admin@local.dev / admin-local-123" "$UP_LOG" || fail "default creds not logged"
grep -q "port $WEB_PORT taken" "$UP_LOG" || fail "web port move not printed"
curl -sf -X POST "http://127.0.0.1:$DB2/api/collections/_superusers/auth-with-password" \
  -H 'Content-Type: application/json' \
  -d '{"identity":"admin@local.dev","password":"admin-local-123"}' >/dev/null \
  || fail "default admin creds do not authenticate"

# --- first boot settles an identity without asking (task-31) ---
grep -q 'guessed me = "e2euser" from $USER' "$UP_LOG" || fail "first boot did not guess me from \$USER"
grep -q 'created member e2euser' "$UP_LOG" || fail "first boot did not seed the member"
grep -q '^me     e2euser' "$UP_LOG" || fail "first boot did not print me"
grep -q 'me = "e2euser"' .lll.toml || fail "me not written to .lll.toml: $(cat .lll.toml 2>&1)"
curl -sf "http://127.0.0.1:$DB2/api/collections/members/records?filter=name%3D%27e2euser%27" \
  | grep -q '"name":"e2euser"' || fail "seeded member not in the members collection"

# The seeded member is usable as an assignee straight away: the point of it.
out=$(LLL_URL="http://127.0.0.1:$DB2" LLL_TEAM=E2E \
  "$LLL" issue create -t "assign on first boot" --assignee e2euser)
printf '%s' "$out" | grep -q "Created E2E-" || fail "assignment to the seeded member failed: $out"

# SIGINT: the board and the in-process PB must both die with the process.
kill -INT -- "-$UP_PID" 2>/dev/null || kill -INT "$UP_PID"
for _ in $(seq 1 50); do
  curl -sf "http://127.0.0.1:$WEB2/" >/dev/null 2>&1 || break
  sleep 0.1
done
curl -sf "http://127.0.0.1:$WEB2/" >/dev/null 2>&1 && fail "board survived SIGINT"
curl -sf "http://127.0.0.1:$DB2/api/health" >/dev/null 2>&1 && fail "in-process PB survived SIGINT"
UP_PID=""

# --- reuse path: healthy PB at the configured URL is used, and outlives up ---
EXT_PORT=$((DB_PORT + 5))
# A genuinely separate server, so the reuse path is tested against a PocketBase
# this `lll up` did not start: a second lll up, its own process and data dir.
EXT_WEB=$((WEB_PORT + 7))
LLL_URL="http://127.0.0.1:$EXT_PORT" LLL_TEAM=E2E \
  "$LLL_ABS" up --no-open --port "$EXT_WEB" --pb-dir "$DATA_DIR/ext_pb_data" \
  </dev/null >/dev/null 2>&1 &
EXT_PB_PID=$!
for _ in $(seq 1 100); do
  curl -sf "http://127.0.0.1:$EXT_PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.1
done
set -m
LLL_URL="http://127.0.0.1:$EXT_PORT" LLL_TEAM=E2E \
  "$LLL" up --no-open --port "$WEB_PORT" --pb-dir "$DATA_DIR/pb_data" >"$UP_LOG" 2>&1 &
UP_PID=$!
set +m
for _ in $(seq 1 100); do
  curl -sf "http://127.0.0.1:$WEB2/" >/dev/null 2>&1 && break
  sleep 0.1
done
grep -q "(already running)" "$UP_LOG" || fail "reuse path not taken"
# .lll.toml now names me, so a later boot must use it, not guess again.
grep -q "guessed me" "$UP_LOG" && fail "me re-guessed with one already configured"
grep -q "^me     e2euser" "$UP_LOG" || fail "configured me not used on a later boot"
kill -INT -- "-$UP_PID" 2>/dev/null || kill -INT "$UP_PID"
sleep 0.5
UP_PID=""
curl -sf "http://127.0.0.1:$EXT_PORT/api/health" >/dev/null \
  || fail "external PB was killed by lll up's exit"

# --- outside the checkout: fail fast, do not boot an unmigrated PB (task-30) ---
OUTSIDE="$DATA_DIR/outside"
mkdir -p "$OUTSIDE"
if out=$(cd "$OUTSIDE" && LLL_TEAM=E2E "$LLL_ABS" up --no-open --port 45999 </dev/null 2>&1); then
  fail "lll up outside the checkout should exit non-zero, got: $out"
fi
printf '%s' "$out" | grep -qF "pb/pb_migrations/ not found" \
  || fail "outside the checkout should name the missing path, got: $out"
printf '%s' "$out" | grep -qF "checkout root" \
  || fail "outside the checkout should name the fix, got: $out"
if printf '%s' "$out" | grep -qF "Missing collection context"; then
  fail "a 404 leaked through instead of the guard: $out"
fi
[ -z "$(ls -A "$OUTSIDE")" ] || fail "lll up outside the checkout must not create anything, found: $(ls -A "$OUTSIDE")"

echo "e2e_up: all assertions passed"
