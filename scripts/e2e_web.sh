#!/usr/bin/env bash
# e2e: the `lll up` web board against an ephemeral PocketBase.
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

# Hermetic: a developer's repo-root .lll.toml must not leak into assertions.
if [ -f .lll.toml ]; then
  mv .lll.toml "$DATA_DIR/.lll.toml.saved"
  RESTORE_TOML=1
fi
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
  if [ "${RESTORE_TOML:-}" = 1 ] && [ -f "$DATA_DIR/.lll.toml.saved" ]; then
    mv "$DATA_DIR/.lll.toml.saved" .lll.toml
  fi
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
LIN=target/.lisette/bin/lll

"$LIN" issue create -t "Web board issue" --priority 2 >/dev/null
"$LIN" issue create -t "Already in progress" >/dev/null
"$LIN" issue update ENG-2 --state in-progress >/dev/null
"$LIN" issue comment ENG-1 -b "seed comment" >/dev/null

"$LIN" up --no-open --port "$WEB_PORT" >"$SERVE_LOG" 2>&1 &
SERVE_PID=$!
for _ in $(seq 1 100); do
  curl -sf "$WEB/" >/dev/null 2>&1 && break
  sleep 0.1
done
curl -sf "$WEB/" >/dev/null || fail "lll up board did not start"

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

# --- card presentation: relative age + server-rendered hover preview ---
assert_not_contains() { # haystack needle label
  printf '%s' "$1" | grep -qF -- "$2" && fail "$3: did not expect '$2' in output:
$1" || true
}

assert_contains "$board" 'class="age"' "cards carry an age row"
assert_contains "$board" "just now" "card age is relative"
assert_contains "$board" 'class="card-pop"' "cards carry a hover preview"

ENG1_ID=$("$LIN" issue view ENG-1 --json | jq -r '.id')
ENG2_ID=$("$LIN" issue view ENG-2 --json | jq -r '.id')
[ -n "$ENG1_ID" ] && [ -n "$ENG2_ID" ] || fail "resolving issue ids for snippet seeds"
curl -sf -X PATCH "$LLL_URL/api/collections/issues/records/$ENG1_ID" \
  -H 'Content-Type: application/json' \
  -d '{"description":"First preview line.\n\nSecond preview line.\nThird line never previewed."}' >/dev/null
LONG_DESC=$(printf 'a%.0s' $(seq 1 200))
curl -sf -X PATCH "$LLL_URL/api/collections/issues/records/$ENG2_ID" \
  -H 'Content-Type: application/json' \
  -d "{\"description\":\"$LONG_DESC\"}" >/dev/null

board=$(curl -sf "$WEB/")
assert_contains "$board" "First preview line. Second preview line." "snippet joins the first two non-empty lines"
assert_not_contains "$board" "Third line never previewed" "snippet drops lines past the second"
assert_contains "$board" "$(printf 'a%.0s' $(seq 1 159))…" "long snippet truncated with an ellipsis"
assert_not_contains "$board" "$LONG_DESC" "full long description stays off the board"

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
out=$(curl -s -w '\n%{http_code}' -X POST \
  -d "title=Created from the board&state=todo" "$WEB/create")
printf '%s' "$out" | tail -1 | grep -q 200 || fail "/create should return 200"
assert_contains "$out" 'id="flash" class="flash" hidden' "/create success clears flash"
out=$("$LIN" issue list)
assert_contains "$out" "Created from the board" "web-created issue in lll issue list"

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  -d "key=ENG-3&state=in-review" "$WEB/state")
[ "$code" = 200 ] || fail "/state returned $code, want 200"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" "in-review" "web state change in lll issue view"
board=$(curl -sf "$WEB/")
assert_contains "$(column "$board" in-review)" "ENG-3" "ENG-3 moved to in-review column"

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  -d "key=ENG-3&body=comment from the board" "$WEB/comment")
[ "$code" = 200 ] || fail "/comment returned $code, want 200"
out=$("$LIN" issue comment ENG-3)
assert_contains "$out" "comment from the board" "web comment in lll issue comment"

# --- issue detail editing: /priority and /title persist, validate, render ---
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  -d "key=ENG-3&priority=urgent" "$WEB/priority")
[ "$code" = 200 ] || fail "/priority returned $code, want 200"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" "Priority:  urgent" "web priority change in lll issue view"

out=$(curl -s -X POST -d "key=ENG-3&priority=bogus" "$WEB/priority")
assert_contains "$out" "unknown priority &#39;bogus&#39;" "bogus priority message"
out=$(curl -s -X POST -d "key=ENG-99&priority=high" "$WEB/priority")
assert_contains "$out" "not found" "/priority unknown issue message"

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  --data-urlencode "key=ENG-3" --data-urlencode "title=Renamed from the board" \
  "$WEB/title")
[ "$code" = 200 ] || fail "/title returned $code, want 200"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" "ENG-3 Renamed from the board" "web title change in lll issue view"

out=$(curl -s -X POST --data-urlencode "key=ENG-3" --data-urlencode "title=  " "$WEB/title")
assert_contains "$out" "title is required" "blank title message"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" "ENG-3 Renamed from the board" "blank title left the title alone"

# titles with JSON-hostile characters survive the round trip
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  --data-urlencode "key=ENG-3" --data-urlencode 'title=Quote " and \ slash' \
  "$WEB/title")
[ "$code" = 200 ] || fail "/title with quotes returned $code, want 200"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" 'Quote " and \ slash' "quoted title persisted verbatim"

# issue page markup: priority select (No priority label) + title editor
issue=$(curl -sf "$WEB/issue/ENG-3")
assert_contains "$issue" 'id="prio-form"' "issue page has priority control"
assert_contains "$issue" '>No priority</option>' "priority none reads No priority"
assert_contains "$issue" 'value="urgent" selected' "priority select reflects current value"
assert_contains "$issue" 'id="title-form"' "issue page has title editor"
board=$(curl -sf "$WEB/")
assert_contains "$board" '>No priority</button>' "board filter labels none as No priority"

# --- drag-and-drop path: /state accepts query params with an empty body ---
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$WEB/state?key=ENG-3&state=done")
[ "$code" = 200 ] || fail "query-param /state returned $code, want 200"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" "done" "query-param state change persisted"

# --- markdown comments render; raw HTML stays inert ---
"$LIN" issue comment ENG-1 -b "has **bold** and \`code\` <script>alert(1)</script>" >/dev/null
issue=$(curl -sf "$WEB/issue/ENG-1")
assert_contains "$issue" "<strong>bold</strong>" "markdown bold rendered"
assert_contains "$issue" "<code>code</code>" "markdown code rendered"
printf '%s' "$issue" | grep -qF "<script>alert(1)</script>" && fail "raw HTML not neutralized in comment"

# --- validation: errors arrive as visible flash patches, never silence ---
out=$(curl -s -X POST -d "title=&state=todo" "$WEB/create")
assert_contains "$out" "datastar-patch-elements" "empty title patches flash"
assert_contains "$out" "title is required" "empty title message"
out=$(curl -s -X POST -d "key=ENG-3&state=bogus" "$WEB/state")
assert_contains "$out" "unknown state" "bogus state message"
out=$(curl -s -X POST -d "key=ENG-3&body=" "$WEB/comment")
assert_contains "$out" "comment body is required" "empty comment message"

# --- no team configured: up refuses rather than booting half-configured ---
NOTEAM_PORT=$(( (RANDOM % 20000) + 40000 ))
if out=$(env -u LLL_TEAM LLL_TEAM="" "$LIN" up --no-open --port "$NOTEAM_PORT" </dev/null 2>&1); then
  fail "lll up with no team should exit non-zero, got: $out"
fi
assert_contains "$out" "no team configured" "no-team boot refused"
assert_contains "$out" "LLL_TEAM=ENG" "refusal suggests the existing team"
[ -f .lll.toml ] && fail "refused boot must not write .lll.toml"

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

# --- dnd v2: manual ordering (sort field, /state?before=, fractional midpoints) ---
# Card keys of a column in rendered order, e.g. "ENG-4,ENG-5".
col_order() { # html state
  column "$1" "$2" | grep -o 'ENG-[0-9]*' | awk '!seen[$0]++' | paste -sd, -
}
issue_id() { # title
  "$LIN" issue list --json | jq -r ".items[] | select(.title==\"$1\") | .id"
}

# New issues land at the end of their column in creation order (hook default).
"$LIN" issue create -t "Order A" >/dev/null # ENG-4
"$LIN" issue create -t "Order B" >/dev/null # ENG-5
"$LIN" issue create -t "Order C" >/dev/null # ENG-6
board=$(curl -sf "$WEB/")
got=$(col_order "$board" todo)
[ "$got" = "ENG-4,ENG-5,ENG-6" ] || fail "new issues in creation order: got '$got'"

A_ID=$(issue_id "Order A"); B_ID=$(issue_id "Order B")
[ -n "$A_ID" ] && [ -n "$B_ID" ] || fail "resolving Order A/B record ids"

# Reorder to the top of the column.
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$WEB/state?key=ENG-6&state=todo&before=$A_ID")
[ "$code" = 200 ] || fail "/state with before returned $code, want 200"
got=$(col_order "$(curl -sf "$WEB/")" todo)
[ "$got" = "ENG-6,ENG-4,ENG-5" ] || fail "reorder to top: got '$got'"

# Reorder to the middle (fractional midpoint between two neighbors).
curl -s -o /dev/null -X POST "$WEB/state?key=ENG-6&state=todo&before=$B_ID"
got=$(col_order "$(curl -sf "$WEB/")" todo)
[ "$got" = "ENG-4,ENG-6,ENG-5" ] || fail "reorder to middle: got '$got'"

# No `before` means end of column.
curl -s -o /dev/null -X POST "$WEB/state?key=ENG-4&state=todo"
got=$(col_order "$(curl -sf "$WEB/")" todo)
[ "$got" = "ENG-6,ENG-5,ENG-4" ] || fail "reorder to end: got '$got'"

# Cross-column drop with a position: state and sort change in one action.
curl -s -o /dev/null -X POST "$WEB/state?key=ENG-2&state=todo&before=$B_ID"
board=$(curl -sf "$WEB/")
got=$(col_order "$board" todo)
[ "$got" = "ENG-6,ENG-2,ENG-5,ENG-4" ] || fail "cross-column drop with position: got '$got'"
printf '%s' "$(column "$board" in-progress)" | grep -qF "ENG-2" \
  && fail "ENG-2 still in in-progress column after cross-column drop" || true

# --json mirrors the board order: sort drives todo's rendered sequence.
got=$("$LIN" issue list --json | jq -r '[.items[] | select(.state=="todo")] | sort_by(.sort) | map(.title) | join(",")')
[ "$got" = "Order C,Already in progress,Order B,Order A" ] \
  || fail "--json sort order: got '$got'"

# A stale drop target (deleted between drop and request) falls back to column end.
"$LIN" issue create -t "Doomed" >/dev/null # ENG-7
DOOMED_ID=$(issue_id "Doomed")
"$LIN" issue delete ENG-7 --force >/dev/null
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$WEB/state?key=ENG-6&state=todo&before=$DOOMED_ID")
[ "$code" = 200 ] || fail "/state with stale before returned $code, want 200"
got=$(col_order "$(curl -sf "$WEB/")" todo)
[ "$got" = "ENG-2,ENG-5,ENG-4,ENG-6" ] || fail "stale before falls back to end: got '$got'"

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
