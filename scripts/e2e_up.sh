#!/usr/bin/env bash
# e2e: `lll up` — one-command runner. Covers: booting its own PB (isolated
# --pb-dir, auto-increment from a taken configured port), the logged default
# admin creds working against the admin API, web-port auto-increment with the
# move printed, SIGINT to the process group stopping both processes, and the
# reuse path (healthy PB at the configured URL is used, not restarted, and
# survives lll up's exit).
set -euo pipefail
cd "$(dirname "$0")/.."

PB_BIN="${PB_BIN:-pb/pocketbase}"
if [ ! -x "$PB_BIN" ]; then
  PB_BIN="$(command -v pocketbase || true)"
fi
[ -n "$PB_BIN" ] || { echo "pocketbase not found" >&2; exit 1; }
export PB_BIN

DATA_DIR="$(mktemp -d)"
DB_PORT=$(( (RANDOM % 20000) + 20000 ))
WEB_PORT=$(( (RANDOM % 20000) + 40000 ))
UP_LOG="$DATA_DIR/up.log"

cleanup() {
  kill "${UP_PID:-}" "${BLOCK_PID:-}" "${EXT_PB_PID:-}" 2>/dev/null || true
  rm -rf "$DATA_DIR"
}
trap cleanup EXIT
fail() { echo "FAIL: $1" >&2; tail -20 "$UP_LOG" >&2 || true; exit 1; }

lis build >/dev/null
LLL=target/bin/lll

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
  LLL_URL="http://127.0.0.1:$DB_PORT" LLL_TEAM="" \
  "$LLL" up --port "$WEB_PORT" --pb-dir "$DATA_DIR/pb_data" >"$UP_LOG" 2>&1 &
UP_PID=$!
set +m

DB2=$((DB_PORT + 1)); WEB2=$((WEB_PORT + 1))
for _ in $(seq 1 100); do
  curl -sf "http://127.0.0.1:$WEB2/" >/dev/null 2>&1 && break
  sleep 0.1
done
curl -sf "http://127.0.0.1:$DB2/api/health" >/dev/null || fail "own PB not on incremented port $DB2"
curl -sf "http://127.0.0.1:$WEB2/" >/dev/null || fail "board not on incremented port $WEB2"
grep -q "defaulting to admin@local.dev" "$UP_LOG" || fail "default creds not logged"
grep -q "port $WEB_PORT taken" "$UP_LOG" || fail "web port move not printed"
curl -sf -X POST "http://127.0.0.1:$DB2/api/collections/_superusers/auth-with-password" \
  -H 'Content-Type: application/json' \
  -d '{"identity":"admin@local.dev","password":"admin-local-123"}' >/dev/null \
  || fail "default admin creds do not authenticate"

# SIGINT the process group: both lll and its child PB must die.
kill -INT -- "-$UP_PID" 2>/dev/null || kill -INT "$UP_PID"
for _ in $(seq 1 50); do
  curl -sf "http://127.0.0.1:$WEB2/" >/dev/null 2>&1 || break
  sleep 0.1
done
curl -sf "http://127.0.0.1:$WEB2/" >/dev/null 2>&1 && fail "board survived SIGINT"
curl -sf "http://127.0.0.1:$DB2/api/health" >/dev/null 2>&1 && fail "child PB survived SIGINT"
UP_PID=""

# --- reuse path: healthy PB at the configured URL is used, and outlives up ---
EXT_PORT=$((DB_PORT + 5))
"$PB_BIN" serve --dir "$DATA_DIR/pb_data" --migrationsDir pb/pb_migrations \
  --hooksDir pb/pb_hooks --http "127.0.0.1:$EXT_PORT" >/dev/null 2>&1 &
EXT_PB_PID=$!
for _ in $(seq 1 100); do
  curl -sf "http://127.0.0.1:$EXT_PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.1
done
set -m
LLL_URL="http://127.0.0.1:$EXT_PORT" LLL_TEAM="" \
  "$LLL" up --port "$WEB_PORT" --pb-dir "$DATA_DIR/pb_data" >"$UP_LOG" 2>&1 &
UP_PID=$!
set +m
for _ in $(seq 1 100); do
  curl -sf "http://127.0.0.1:$WEB2/" >/dev/null 2>&1 && break
  sleep 0.1
done
grep -q "using running pocketbase" "$UP_LOG" || fail "reuse path not taken"
kill -INT -- "-$UP_PID" 2>/dev/null || kill -INT "$UP_PID"
sleep 0.5
UP_PID=""
curl -sf "http://127.0.0.1:$EXT_PORT/api/health" >/dev/null \
  || fail "external PB was killed by lll up's exit"

echo "e2e_up: all assertions passed"
