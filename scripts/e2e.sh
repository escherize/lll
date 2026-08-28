#!/usr/bin/env bash
# e2e: ephemeral PocketBase + compiled lin CLI.
# Covers: create/list with ENG-1 style IDs, per-team numbering,
# forged duplicate (team, number) rejection, --help output.
set -euo pipefail
cd "$(dirname "$0")/.."

PB_BIN="${PB_BIN:-pb/pocketbase}"
if [ ! -x "$PB_BIN" ]; then
  PB_BIN="$(command -v pocketbase || true)"
fi
if [ -z "$PB_BIN" ]; then
  echo "pocketbase not found: brew install pocketbase (see pb/README.md)" >&2
  exit 1
fi

DATA_DIR="$(mktemp -d)"
PORT=$(( (RANDOM % 20000) + 20000 ))
URL="http://127.0.0.1:$PORT"
PB_LOG="$DATA_DIR/pb.log"

"$PB_BIN" serve --dir "$DATA_DIR/pb_data" \
  --migrationsDir pb/pb_migrations --hooksDir pb/pb_hooks \
  --http "127.0.0.1:$PORT" >"$PB_LOG" 2>&1 &
PB_PID=$!
cleanup() { kill "$PB_PID" 2>/dev/null || true; rm -rf "$DATA_DIR"; }
trap cleanup EXIT

fail() {
  echo "FAIL: $1" >&2
  echo "--- pocketbase log ---" >&2
  tail -20 "$PB_LOG" >&2 || true
  exit 1
}

assert_contains() { # haystack needle label
  printf '%s' "$1" | grep -qF "$2" || fail "$3: expected '$2' in output:
$1"
}
assert_not_contains() {
  printf '%s' "$1" | grep -qF "$2" && fail "$3: did not expect '$2' in output:
$1" || true
}

for _ in $(seq 1 100); do
  curl -sf "$URL/api/health" >/dev/null 2>&1 && break
  sleep 0.1
done
curl -sf "$URL/api/health" >/dev/null || fail "PocketBase did not start"

json_id() { python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'; }

ENG_ID=$(curl -sf -X POST "$URL/api/collections/teams/records" \
  -H 'Content-Type: application/json' \
  -d '{"key":"ENG","name":"Engineering"}' | json_id)
OPS_ID=$(curl -sf -X POST "$URL/api/collections/teams/records" \
  -H 'Content-Type: application/json' \
  -d '{"key":"OPS","name":"Operations"}' | json_id)
[ -n "$ENG_ID" ] && [ -n "$OPS_ID" ] || fail "seeding teams"

lis build >/dev/null
LIN=target/bin/lin

# --- create + list shows ENG-1 style identifier ---
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue create -t "First engineering issue")
assert_contains "$out" "Created ENG-1: First engineering issue" "create output"

out=$(LIN_URL=$URL "$LIN" issue list)
assert_contains "$out" "ENG-1" "list shows ENG-1"
assert_contains "$out" "First engineering issue" "list shows title"
assert_contains "$out" "todo" "list shows state"

# --- per-team numbering: interleaved creates yield ENG-1, OPS-1, ENG-2 ---
out=$(LIN_URL=$URL LIN_TEAM=OPS "$LIN" issue create -t "First ops issue")
assert_contains "$out" "Created OPS-1" "ops numbering starts at 1"
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue create -t "Second engineering issue")
assert_contains "$out" "Created ENG-2" "eng numbering continues at 2"

out=$(LIN_URL=$URL "$LIN" issue list)
assert_contains "$out" "ENG-1" "list has ENG-1"
assert_contains "$out" "ENG-2" "list has ENG-2"
assert_contains "$out" "OPS-1" "list has OPS-1"
assert_not_contains "$out" "OPS-2" "no OPS-2"

# --- forged duplicate (team, number) rejected by unique index ---
status=$(curl -s -o "$DATA_DIR/forged.json" -w '%{http_code}' \
  -X POST "$URL/api/collections/issues/records" \
  -H 'Content-Type: application/json' \
  -d "{\"team\":\"$ENG_ID\",\"number\":1,\"title\":\"forged\",\"state\":\"todo\"}")
[ "$status" = "400" ] || fail "forged duplicate: expected HTTP 400, got $status: $(cat "$DATA_DIR/forged.json")"

# --- team commands ---
out=$(LIN_URL=$URL "$LIN" team list)
assert_contains "$out" "ENG" "team list has ENG"
assert_contains "$out" "Engineering" "team list has name"
assert_contains "$out" "OPS" "team list has OPS"

out=$(LIN_URL=$URL "$LIN" team create -k QA -n "Quality")
assert_contains "$out" "Created team QA: Quality" "team create output"
out=$(LIN_URL=$URL "$LIN" team list)
assert_contains "$out" "QA" "team list has created QA"

out=$(LIN_URL=$URL "$LIN" team view ENG)
assert_contains "$out" "Key:    ENG" "team view key"
assert_contains "$out" "Name:   Engineering" "team view name"
assert_contains "$out" "Issues: 2" "team view issue count"

# --- LIN_TEAM scopes issue list by default ---
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list)
assert_contains "$out" "ENG-1" "scoped list has ENG-1"
assert_not_contains "$out" "OPS-1" "scoped list hides OPS-1"

# --- config init ---
LIN_ABS="$PWD/$LIN"
WORK="$DATA_DIR/work"
FAKEHOME="$DATA_DIR/home"
mkdir -p "$WORK" "$FAKEHOME/.config/lin"

out=$(cd "$WORK" && "$LIN_ABS" config init)
assert_contains "$out" "Wrote .lin.toml" "config init output"
assert_contains "$(cat "$WORK/.lin.toml")" "url = " "template mentions url"
assert_contains "$(cat "$WORK/.lin.toml")" "team = " "template mentions team"
if (cd "$WORK" && "$LIN_ABS" config init >/dev/null 2>&1); then
  fail "config init overwrote an existing .lin.toml"
fi
rm "$WORK/.lin.toml"

# --- config precedence: env > ./.lin.toml > ~/.config/lin/lin.toml ---
printf 'url = "%s"\nteam = "OPS"\n' "$URL" > "$FAKEHOME/.config/lin/lin.toml"

# home file alone supplies url + team
out=$(cd "$WORK" && env -u LIN_URL -u LIN_TEAM HOME="$FAKEHOME" "$LIN_ABS" issue list)
assert_contains "$out" "OPS-1" "home config scopes to OPS"
assert_not_contains "$out" "ENG-1" "home config hides ENG"

# project file beats home file
printf 'url = "%s"\nteam = "ENG"\n' "$URL" > "$WORK/.lin.toml"
out=$(cd "$WORK" && env -u LIN_URL -u LIN_TEAM HOME="$FAKEHOME" "$LIN_ABS" issue list)
assert_contains "$out" "ENG-1" "project config scopes to ENG"
assert_not_contains "$out" "OPS-1" "project config beats home config"

# env beats project file
out=$(cd "$WORK" && env -u LIN_URL LIN_TEAM=OPS HOME="$FAKEHOME" "$LIN_ABS" issue list)
assert_contains "$out" "OPS-1" "env scopes to OPS"
assert_not_contains "$out" "ENG-1" "env beats project config"

# --- help output ---
out=$("$LIN" --help)
assert_contains "$out" "Usage:" "lin --help"
assert_contains "$out" "lin team" "lin --help mentions team"
assert_contains "$out" "lin config" "lin --help mentions config"
out=$("$LIN" issue --help)
assert_contains "$out" "Usage:" "lin issue --help"
out=$("$LIN" team --help)
assert_contains "$out" "Usage:" "lin team --help"
out=$("$LIN" config --help)
assert_contains "$out" "Usage:" "lin config --help"

echo "e2e: all assertions passed"
