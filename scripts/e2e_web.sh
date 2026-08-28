#!/usr/bin/env bash
# e2e: `lll serve` web board against an ephemeral PocketBase.
# Covers: board page grouped by the six states with cards in the right
# columns, issue page (detail, comments, forms), actions (/create, /state,
# /comment) persisting to PB and visible via the CLI, server-side validation,
# the /events SSE stream emitting datastar-patch-elements frames on
# CLI-driven changes (board scope and issue scope), static CSS serving, and —
# when playwright-cli is available — a real-browser check that a CLI-created
# issue appears on an open board without reload.
# Standalone (boots its own PB), also invoked by e2e.sh.
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
PB_PORT=$(( (RANDOM % 20000) + 20000 ))
WEB_PORT=$(( (RANDOM % 20000) + 40000 ))
export LLL_URL="http://127.0.0.1:$PB_PORT"
export LLL_TEAM=ENG
WEB="http://127.0.0.1:$WEB_PORT"
PB_LOG="$DATA_DIR/pb.log"
SERVE_LOG="$DATA_DIR/serve.log"
BROWSER_SESSION="e2e-web-$$"

"$PB_BIN" superuser upsert e2e@local.test e2e-password-123 \
  --dir "$DATA_DIR/pb_data" >"$PB_LOG" 2>&1 \
  || { echo "FAIL: creating PB superuser" >&2; cat "$PB_LOG" >&2; exit 1; }

"$PB_BIN" serve --dir "$DATA_DIR/pb_data" \
  --migrationsDir pb/pb_migrations --hooksDir pb/pb_hooks \
  --http "127.0.0.1:$PB_PORT" >"$PB_LOG" 2>&1 &
PB_PID=$!
SERVE_PID=""
CURL_PID=""
cleanup() {
  if command -v playwright-cli >/dev/null 2>&1; then
    playwright-cli -s="$BROWSER_SESSION" close >/dev/null 2>&1 || true
  fi
  kill $CURL_PID $SERVE_PID $PB_PID 2>/dev/null || true
  rm -rf "$DATA_DIR"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $1" >&2
  echo "--- serve log ---" >&2
  tail -20 "$SERVE_LOG" >&2 || true
  echo "--- pocketbase log ---" >&2
  tail -20 "$PB_LOG" >&2 || true
  exit 1
}

assert_contains() { # haystack needle label
  printf '%s' "$1" | grep -qF -- "$2" || fail "$3: expected '$2' in output:
$1"
}

# The column's section markup for a state, for asserting card placement.
column() { # html state
  printf '%s' "$1" | python3 -c '
import sys
html = sys.stdin.read()
state = sys.argv[1]
try:
    print(html.split(f"id=\"col-{state}\"")[1].split("</section>")[0])
except IndexError:
    pass
' "$2"
}

for _ in $(seq 1 100); do
  curl -sf "$LLL_URL/api/health" >/dev/null 2>&1 && break
  sleep 0.1
done
curl -sf "$LLL_URL/api/health" >/dev/null || fail "PocketBase did not start"

curl -sf -X POST "$LLL_URL/api/collections/teams/records" \
  -H 'Content-Type: application/json' \
  -d '{"key":"ENG","name":"Engineering"}' >/dev/null || fail "seeding team"

lis build >/dev/null
LIN=target/bin/lll

"$LIN" issue create -t "Web board issue" --priority 2 >/dev/null
"$LIN" issue create -t "Already in progress" >/dev/null
"$LIN" issue update ENG-2 --state in-progress >/dev/null
"$LIN" issue comment ENG-1 -b "seed comment" >/dev/null

"$LIN" serve --port "$WEB_PORT" >"$SERVE_LOG" 2>&1 &
SERVE_PID=$!
for _ in $(seq 1 100); do
  curl -sf "$WEB/" >/dev/null 2>&1 && break
  sleep 0.1
done
curl -sf "$WEB/" >/dev/null || fail "lll serve did not start"

# --- board page: six columns, cards in the right ones ---
board=$(curl -sf "$WEB/")
for state in backlog todo in-progress in-review done cancelled; do
  assert_contains "$board" "id=\"col-$state\"" "board has column $state"
done
assert_contains "$(column "$board" todo)" "ENG-1" "ENG-1 in todo column"
assert_contains "$(column "$board" todo)" "Web board issue" "ENG-1 title on card"
assert_contains "$(column "$board" in-progress)" "ENG-2" "ENG-2 in in-progress column"
assert_contains "$board" 'id="new-issue"' "board has new-issue form"
assert_contains "$board" "datastar" "board loads Datastar"
curl -sf "$WEB/static/theme.css" >/dev/null || fail "static css served"

# --- issue page ---
issue=$(curl -sf "$WEB/issue/ENG-1")
assert_contains "$issue" 'id="issue-detail"' "issue page has detail"
assert_contains "$issue" "Web board issue" "issue page has title"
assert_contains "$issue" "seed comment" "issue page has seed comment"
assert_contains "$issue" 'id="comment-form"' "issue page has comment form"
assert_contains "$issue" 'id="state-form"' "issue page has state control"
curl -s -o /dev/null -w '%{http_code}' "$WEB/issue/ENG-99" | grep -q 404 \
  || fail "unknown issue is a 404"

# --- actions persist to PB and show via the CLI ---
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  -d "title=Created from the board&state=todo" "$WEB/create")
[ "$code" = 204 ] || fail "/create returned $code, want 204"
out=$("$LIN" issue list)
assert_contains "$out" "Created from the board" "web-created issue in lll issue list"

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  -d "key=ENG-3&state=in-review" "$WEB/state")
[ "$code" = 204 ] || fail "/state returned $code, want 204"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" "in-review" "web state change in lll issue view"
board=$(curl -sf "$WEB/")
assert_contains "$(column "$board" in-review)" "ENG-3" "ENG-3 moved to in-review column"

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  -d "key=ENG-3&body=comment from the board" "$WEB/comment")
[ "$code" = 204 ] || fail "/comment returned $code, want 204"
out=$("$LIN" issue comment ENG-3)
assert_contains "$out" "comment from the board" "web comment in lll issue comment"

# --- validation ---
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -d "title=&state=todo" "$WEB/create")
[ "$code" = 400 ] || fail "empty title returned $code, want 400"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -d "key=ENG-3&state=bogus" "$WEB/state")
[ "$code" = 400 ] || fail "bogus state returned $code, want 400"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -d "key=ENG-3&body=" "$WEB/comment")
[ "$code" = 400 ] || fail "empty comment returned $code, want 400"

# --- /events: board scope gets a patch frame after a CLI-driven update ---
EVENTS_FILE="$DATA_DIR/events.txt"
curl -sN "$WEB/events?page=board" >"$EVENTS_FILE" &
CURL_PID=$!
sleep 0.5
"$LIN" issue update ENG-1 --state done >/dev/null
for _ in $(seq 1 50); do
  grep -q "datastar-patch-elements" "$EVENTS_FILE" 2>/dev/null && break
  sleep 0.1
done
kill $CURL_PID 2>/dev/null || true
events=$(cat "$EVENTS_FILE")
assert_contains "$events" "event: datastar-patch-elements" "SSE patch frame emitted"
assert_contains "$events" 'data: elements <main id="board"' "patch morphs #board"
assert_contains "$events" 'id="col-done"' "patch contains the target column"

# --- /events: issue scope gets comments patch after a CLI comment ---
curl -sN "$WEB/events?page=issue&key=ENG-1" >"$EVENTS_FILE" &
CURL_PID=$!
sleep 0.5
"$LIN" issue comment ENG-1 -b "live comment over sse" >/dev/null
for _ in $(seq 1 50); do
  grep -q "live comment over sse" "$EVENTS_FILE" 2>/dev/null && break
  sleep 0.1
done
kill $CURL_PID 2>/dev/null || true
CURL_PID=""
events=$(cat "$EVENTS_FILE")
assert_contains "$events" "event: datastar-patch-elements" "issue-scope patch frame emitted"
assert_contains "$events" 'id="comments"' "patch morphs #comments"
assert_contains "$events" "live comment over sse" "patch carries the new comment"

# --- browser-level: CLI create appears on an open board without reload ---
if command -v playwright-cli >/dev/null 2>&1; then
  playwright-cli -s="$BROWSER_SESSION" open "$WEB/" >/dev/null 2>&1 \
    || fail "playwright: opening board"
  before=$(playwright-cli -s="$BROWSER_SESSION" eval \
    "() => document.querySelectorAll('.card').length" | sed -n '/### Result/{n;p;}')
  "$LIN" issue create -t "Born while browser open" >/dev/null
  sleep 2
  result=$(playwright-cli -s="$BROWSER_SESSION" eval \
    "() => JSON.stringify({cards: document.querySelectorAll('.card').length, navs: performance.getEntriesByType('navigation').length, titles: [...document.querySelectorAll('.card .title')].map(e => e.textContent)})" \
    | sed -n '/### Result/{n;p;}' | tr -d '\\')
  assert_contains "$result" "Born while browser open" "browser: new card appeared"
  assert_contains "$result" '"navs":1' "browser: no reload happened"
  case "$result" in
    *"\"cards\":$((before + 1))"*) ;;
    *) fail "browser: card count did not go from $before to $((before + 1)): $result" ;;
  esac
  playwright-cli -s="$BROWSER_SESSION" close >/dev/null 2>&1 || true
  echo "e2e_web: browser-level realtime check passed"
else
  echo "e2e_web: playwright-cli not found — skipped browser-level check" >&2
fi

echo "e2e_web: all assertions passed"
