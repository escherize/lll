#!/usr/bin/env bash
# e2e: the `lll up` web board against an ephemeral PocketBase.
# Covers: board page grouped by the six states with cards in the right
# columns, issue page (detail, comments, forms), the app shell's rail (one
# template, same on every page, absent from every broadcast), actions
# (/create, /state,
# /comment) persisting to PB and visible via the CLI, server-side validation,
# the /events SSE stream emitting datastar-patch-elements frames on
# CLI-driven changes (board scope and issue scope), static CSS serving, and —
# when playwright-cli is available — a real-browser check that a CLI-created
# issue appears on an open board without reload, and the zero-JavaScript
# /issues table (server-side sort and filter through query params, honest row
# count, bad params degrading to the flash strip).
# Standalone (boots its own PB), also invoked by e2e.sh.
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
PB_PORT=$(free_port 20000 39999)
WEB_PORT=$(free_port 40000 59999)
export LLL_URL="http://127.0.0.1:$PB_PORT"
export LLL_TEAM=ENG
WEB="http://127.0.0.1:$WEB_PORT"
PB_LOG="$DATA_DIR/pb.log"
SERVE_LOG="$DATA_DIR/serve.log"
BROWSER_SESSION="e2e-web-$$"

# PocketBase is embedded in lll; one `lll up` is both the database and the
# board this suite exercises. Built here because it has to exist first.
lis build >/dev/null
LIN=target/.lisette/bin/lll

# USER is pinned: a first boot seeds a member named after it (task-31), and
# the board assertions must not depend on who runs this suite.
USER=e2e "$LIN" up --no-open --pb-dir "$DATA_DIR/pb_data" --port "$WEB_PORT" \
  </dev/null >"$PB_LOG" 2>&1 &
PB_PID=$!
SERVE_PID=""
CURL_PID=""
cleanup() {
  # `lll up` writes one on a first boot; the developer's own goes back on top.
  rm -f .lll.toml
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
  -d '{"key":"ENG","name":"Engineering"}' >/dev/null || true   # lll up already created ENG

"$LIN" issue create -t "Web board issue" --priority 2 >/dev/null
"$LIN" issue create -t "Already in progress" >/dev/null
"$LIN" issue update ENG-2 --state in-progress >/dev/null
"$LIN" issue comment ENG-1 -b "seed comment" >/dev/null

# the board came up with PocketBase above
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

# --- app shell: one rail template, the same on every page (task-81) ---
# The <nav id="rail"> block, for diffing one page's shell against another's.
rail() { # html
  printf '%s' "$1" | python3 -c '
import sys
html = sys.stdin.read()
try:
    print(html.split("<nav id=\"rail\"")[1].split("</nav>")[0])
except IndexError:
    pass
'
}
board=$(curl -sf "$WEB/")
board_rail=$(rail "$board")
[ -n "$board_rail" ] || fail "board page has no rail"
[ "$board_rail" = "$(rail "$issue")" ] || fail "the rail differs between the board and issue pages:
$(diff <(printf '%s' "$board_rail") <(rail "$issue") || true)"
assert_contains "$board_rail" 'href="/?mine=1"' "rail has a My issues row"
assert_contains "$board_rail" "v0.1.0" "rail footer carries the version"

# ?mine=1 marks the row current and seeds one filter chip. The board fragment
# itself stays unfiltered on purpose: /events broadcasts one #board to every
# board client, so a server-filtered page would be morphed back on the next
# realtime event.
mine=$(curl -sf "$WEB/?mine=1")
assert_contains "$mine" 'title="Issues assigned to e2e" class="active"' \
  "?mine=1 marks the My issues row current"
assert_contains "$mine" 'data-signals:flt="[&#34;assignee:e2e&#34;]"' \
  "?mine=1 seeds the assignee filter chip"
assert_contains "$(column "$mine" todo)" "ENG-1" "?mine=1 leaves the board fragment unfiltered"

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

# --- hard wraps: one newline is a line break, the way GitHub comments do it
# (task-45). CommonMark would collapse it to a space.
"$LIN" issue comment ENG-1 -b "wrapped line one
wrapped line two" >/dev/null
issue=$(curl -sf "$WEB/issue/ENG-1")
assert_contains "$issue" "wrapped line one<br>" "single newline in a comment becomes a line break"

# --- validation: errors arrive as visible flash patches, never silence ---
out=$(curl -s -X POST -d "title=&state=todo" "$WEB/create")
assert_contains "$out" "datastar-patch-elements" "empty title patches flash"
assert_contains "$out" "title is required" "empty title message"
out=$(curl -s -X POST -d "key=ENG-3&state=bogus" "$WEB/state")
assert_contains "$out" "unknown state" "bogus state message"
out=$(curl -s -X POST -d "key=ENG-3&body=" "$WEB/comment")
assert_contains "$out" "comment body is required" "empty comment message"

# --- no team configured: up refuses rather than booting half-configured ---
NOTEAM_PORT=$(free_port 40000 59999)
# The boot above legitimately wrote 'me' (task-31), so the invariant is that
# the refusal changes nothing — not that the file is absent.
TOML_BEFORE=$(cat .lll.toml 2>/dev/null || true)
if out=$(env -u LLL_TEAM LLL_TEAM="" "$LIN" up --no-open --port "$NOTEAM_PORT" </dev/null 2>&1); then
  fail "lll up with no team should exit non-zero, got: $out"
fi
assert_contains "$out" "no team configured" "no-team boot refused"
assert_contains "$out" "LLL_TEAM=ENG" "refusal suggests the existing team"
[ "$(cat .lll.toml 2>/dev/null || true)" = "$TOML_BEFORE" ] \
  || fail "refused boot wrote to .lll.toml: $(cat .lll.toml)"

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
# Broadcasts are fragments, never pages: the shell is composed by the page
# handlers alone, so no broadcast path can construct a rail (task-81).
assert_not_contains "$events" 'id="rail"' "broadcast fragments carry no shell"

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
  # The probe marks the live rail node: a morph that replaced or re-rendered
  # the rail would take the attribute with it (task-81).
  before=$(playwright-cli -s="$BROWSER_SESSION" eval \
    "() => { document.getElementById('rail').dataset.probe = 'kept'; return document.querySelectorAll('.card').length }" \
    | sed -n '/### Result/{n;p;}')
  "$LIN" issue create -t "Born while browser open" >/dev/null
  sleep 2
  result=$(playwright-cli -s="$BROWSER_SESSION" eval \
    "() => JSON.stringify({cards: document.querySelectorAll('.card').length, navs: performance.getEntriesByType('navigation').length, rail: document.getElementById('rail').dataset.probe || 'LOST', titles: [...document.querySelectorAll('.card .title')].map(e => e.textContent)})" \
    | sed -n '/### Result/{n;p;}' | tr -d '\\')
  assert_contains "$result" "Born while browser open" "browser: new card appeared"
  assert_contains "$result" '"navs":1' "browser: no reload happened"
  assert_contains "$result" '"rail":"kept"' "browser: the SSE morph left the rail alone"
  case "$result" in
    *"\"cards\":$((before + 1))"*) ;;
    *) fail "browser: card count did not go from $before to $((before + 1)): $result" ;;
  esac
  playwright-cli -s="$BROWSER_SESSION" close >/dev/null 2>&1 || true
  echo "e2e_web: browser-level realtime check passed"
else
  echo "e2e_web: playwright-cli not found — skipped browser-level check" >&2
fi

# --- issue descriptions render markdown, like comments (task-21) ---
"$LIN" issue update ENG-1 --description '## Heading

Some **bold** text and `code`.

<script>alert(1)</script>' >/dev/null
page=$(curl -sf "$WEB/issue/ENG-1")
assert_contains "$page" '<div class="desc md">' "description uses the shared markdown container"
assert_contains "$page" "<h2>Heading</h2>" "description renders a markdown heading"
assert_contains "$page" "<strong>bold</strong>" "description renders bold"
assert_contains "$page" "<code>code</code>" "description renders inline code"
assert_not_contains "$page" "<script>alert" "raw HTML in a description stays out of the page"

# --- descriptions hard-wrap too, and raw HTML stays dropped (task-45) ---
"$LIN" issue update ENG-1 --description 'desc line one
desc line two

<b>raw</b> markup' >/dev/null
page=$(curl -sf "$WEB/issue/ENG-1")
assert_contains "$page" "desc line one<br>" "single newline in a description becomes a line break"
assert_not_contains "$page" "<b>raw</b>" "raw HTML in a description is still dropped with hard wraps on"

# --- GFM, syntax highlighting, and mermaid (task-42) ---
"$LIN" issue update ENG-1 --description '| pick | why |
| --- | --- |
| goldmark | GFM |

~~dropped~~ and https://example.com/gfm and

- [x] shipped

```go
func main() {}
```

```mermaid
graph TD; A-->B;
```' >/dev/null
page=$(curl -sf "$WEB/issue/ENG-1")
assert_contains "$page" "<th>pick</th>" "GFM table renders as a table"
assert_not_contains "$page" "| pick | why |" "GFM table is not left as literal pipes"
assert_contains "$page" "<del>dropped</del>" "GFM strikethrough renders"
assert_contains "$page" '<a href="https://example.com/gfm">' "GFM autolink renders"
assert_contains "$page" 'type="checkbox"' "GFM task list renders a checkbox"
assert_contains "$page" 'class="chroma"' "fenced code is highlighted server-side"
assert_not_contains "$page" 'style="color:#' "chroma emits classes, not inline colors"
assert_contains "$page" '<code class="language-mermaid">' "a mermaid fence is left plain for the client"
assert_contains "$page" '/static/mermaid-init.js' "the issue page loads the mermaid initializer"
curl -sfI "$WEB/static/mermaid.min.js" >/dev/null || fail "vendored mermaid.min.js is not served"
curl -sfI "$WEB/static/mermaid-init.js" >/dev/null || fail "mermaid-init.js is not served"


# --- /issues: a sortable, filterable, bookmarkable table (task-82) ---
# The point of the table is that its whole state is in the URL, so every
# assertion below is one curl of a URL an agent could type.
issues=$(curl -sf "$WEB/issues") || fail "/issues did not serve"
assert_contains "$issues" '<table id="issues" class="itbl">' "the issues page renders a table"
assert_contains "$issues" 'href="/issue/ENG-1"' "the table links rows to their issue pages"
assert_contains "$issues" 'href="/issues?sort=-created"' "column headers sort server-side through the URL"
assert_contains "$issues" 'href="/issues?sort=-priority"' "priority is a sortable column"
assert_contains "$issues" 'aria-sort="descending"' "the sorting column says so to a screen reader"

# ZERO JavaScript: no script tag, no datastar attributes, no SSE connection.
# A page that subscribed would be morphed into the unfiltered #board.
assert_not_contains "$issues" "<script" "the issues page loads no script"
assert_not_contains "$issues" "data-on:" "the issues page binds no client-side handlers"
assert_not_contains "$issues" "data-init" "the issues page opens no SSE connection"

# Sorting is server-side: ascending and descending disagree about the first row.
first_row() { # url
  curl -sf "$WEB$1" | python3 -c '
import re, sys
keys = re.findall(r"class=\"c-id\"><a href=\"/issue/([A-Z]+-[0-9]+)\"", sys.stdin.read())
print(keys[0] if keys else "")
'
}
asc=$(first_row "/issues?sort=number")
desc=$(first_row "/issues?sort=-number")
[ -n "$asc" ] && [ -n "$desc" ] || fail "the sorted table returned no rows: '$asc' / '$desc'"
[ "$asc" != "$desc" ] || fail "?sort=number and ?sort=-number both start at $asc"
[ "$asc" = "ENG-1" ] || fail "?sort=number should start at ENG-1, got $asc"

# Filters are query params, so a filtered view is a shareable URL.
todo=$(curl -sf "$WEB/issues?state=todo")
assert_contains "$todo" '<option value="todo" selected>' "the chooser shows the filter the URL asked for"
assert_contains "$todo" 'class="itbl-clear"' "a filtered table offers a way back to all issues"
# A dedicated pair, so the filter assertion does not depend on what earlier
# sections left the shared issues in.
"$LIN" issue create -t "Table filter subject" >/dev/null
subject=$("$LIN" issue list --search "Table filter subject" | awk '{print $1}' | head -1)
"$LIN" issue update "$subject" --state in-review >/dev/null
in_review=$(curl -sf "$WEB/issues?state=in-review")
assert_contains "$in_review" "Table filter subject" "?state=in-review keeps the in-review issue"
assert_contains "$in_review" 'value="in-review" selected' "the state chooser reflects the URL"
"$LIN" issue update "$subject" --state done >/dev/null
gone=$(curl -sf "$WEB/issues?state=in-review")
assert_not_contains "$gone" "Table filter subject" "?state=in-review drops it once it moves on"

# The count is honest rather than a bare row tally.
assert_contains "$issues" 'class="itbl-count"' "the table states how many issues it is showing"

# A stale bookmark degrades to the unfiltered table plus the flash strip — the
# system's one error voice — never a 500.
bad=$(curl -sf "$WEB/issues?sort=bogus") || fail "a bad sort param returned an error status"
assert_contains "$bad" 'class="flash"' "an unknown sort field is reported in the flash strip"
assert_contains "$bad" "unknown sort field" "the flash names the rejected field"
assert_contains "$bad" '<table id="issues"' "an unknown sort field still serves the table"
bad_state=$(curl -sf "$WEB/issues?state=nope") || fail "a bad state param returned an error status"
assert_contains "$bad_state" "unknown state" "an unknown state is reported too"

# One rail template: the same rows on every page, differing only in which row
# reads as current. Adding this page did not touch the board's template.
issues_rail=$(rail "$issues")
rail_rows() { printf '%s' "$1" | grep -o 'href="[^"]*"' | sort; }
[ "$(rail_rows "$issues_rail")" = "$(rail_rows "$board_rail")" ] \
  || fail "the board and issues rails offer different destinations:
$(diff <(rail_rows "$board_rail") <(rail_rows "$issues_rail") || true)"
assert_contains "$issues_rail" 'href="/issues"' "the rail has an All issues row"
assert_contains "$board_rail" 'href="/issues"' "the board's rail has it too"
assert_contains "$issues_rail" '<a href="/issues" class="active">' "the All issues row is current on its own page"
assert_not_contains "$issues_rail" '<a href="/" class="active">' "and the board row is not"
# --- /settings: server-side, shared, CLI-only things (task-83) ---
# The id of the row a section rendered for a named record, so the assertions
# below can edit and delete the record the page itself is showing.
row_id() { # html kind name
  printf '%s' "$1" | python3 -c '
import re, sys
html, kind, name = sys.stdin.read(), sys.argv[1], sys.argv[2]
m = re.search(r"id=\"set-%s-([a-z0-9]+)\" data-name=\"%s\"" % (kind, re.escape(name)), html)
print(m.group(1) if m else "")
' "$2" "$3"
}

settings=$(curl -sf "$WEB/settings") || fail "/settings did not respond"
assert_contains "$settings" 'id="settings"' "settings page has its morph target"
assert_contains "$(rail "$settings")" 'href="/settings" class="active"' \
  "the rail's Settings row is current on /settings"
assert_contains "$settings" 'id="team-form"' "settings page edits the team"
assert_contains "$settings" 'name="accent"' "settings page edits the team accent"
# Per-browser state and unwritable config must not appear here.
assert_not_contains "$settings" "Hidden columns" "settings does not duplicate the board's per-browser column state"
assert_not_contains "$settings" "pb-dir" "settings does not offer config the running process cannot change"
assert_not_contains "$settings" "$WEB" "settings does not offer the port it is served on"

# Labels, members and projects are creatable and editable from the page.
curl -sf -X POST "$WEB/settings/label" -d 'name=web-made' -d 'color=#4cb782' >/dev/null
"$LIN" label list | grep -q '^web-made	#4cb782' || fail "creating a label from /settings did not reach PocketBase"
LABEL_ID=$(row_id "$(curl -sf "$WEB/settings")" label web-made)
[ -n "$LABEL_ID" ] || fail "/settings did not render the label it just created"
curl -sf -X POST "$WEB/settings/label" -d "id=$LABEL_ID" -d 'name=web-renamed' -d 'color=#8d7ce6' >/dev/null
"$LIN" label list | grep -q '^web-renamed	#8d7ce6' || fail "renaming and recoloring a label from /settings did not persist"
curl -sf -X POST "$WEB/settings/label?del=1" -d "id=$LABEL_ID" >/dev/null
"$LIN" label list | grep -q 'web-renamed' && fail "deleting a label from /settings did not persist" || true

curl -sf -X POST "$WEB/settings/member" -d 'name=Web Member' -d 'email=web@example.com' >/dev/null
"$LIN" member list | grep -q '^Web Member	web@example.com' || fail "creating a member from /settings did not persist"
MEMBER_ID=$(row_id "$(curl -sf "$WEB/settings")" member "Web Member")
curl -sf -X POST "$WEB/settings/member" -d "id=$MEMBER_ID" -d 'name=Web Member' -d 'email=moved@example.com' >/dev/null
"$LIN" member list | grep -q '^Web Member	moved@example.com' || fail "editing a member from /settings did not persist"

curl -sf -X POST "$WEB/settings/project" -d 'name=Web Project' -d 'status=planned' >/dev/null
"$LIN" project list | grep -q '^Web Project	planned' || fail "creating a project from /settings did not persist"
PROJECT_ID=$(row_id "$(curl -sf "$WEB/settings")" project "Web Project")
curl -sf -X POST "$WEB/settings/project" -d "id=$PROJECT_ID" -d 'name=Web Project' -d 'status=started' >/dev/null
"$LIN" project list | grep -q '^Web Project	started' || fail "changing a project status from /settings did not persist"

# Validation speaks through the one flash strip, and writes nothing.
assert_contains "$(curl -sf -X POST "$WEB/settings/label" -d 'name=   ')" \
  'id="flash"' "an empty label name answers with the flash strip"
assert_contains "$(curl -sf -X POST "$WEB/settings/label" -d 'name=x' -d 'color=nope')" \
  'not a #rrggbb colour' "a malformed colour is refused"
assert_contains "$(curl -sf -X POST "$WEB/settings/project" -d "id=$PROJECT_ID" -d 'name=Web Project' -d 'status=bogus')" \
  "unknown project status" "an unknown project status is refused"
"$LIN" label list | grep -q '^x	' && fail "a refused label write still created a record" || true

# --- the team accent drives --accent and the favicon (task-83) ---
# Nothing stored means DESIGN.md's canonical orange, so theme.css's own
# tokens are left byte-identical: the injected rule is empty.
assert_contains "$(curl -sf "$WEB/")" '<style id="accent"></style>' \
  "an unset accent overrides nothing"
assert_contains "$(curl -sf "$WEB/")" 'id="favicon"' "the board carries a generated favicon"

curl -sf -X POST "$WEB/settings/team" -d 'name=Engineering' -d 'accent=#3ea0f0' >/dev/null
for page in "/" "/issue/ENG-1" "/settings"; do
  html=$(curl -sf "$WEB$page")
  assert_contains "$html" '--accent:#3ea0f0' "$page wears the team accent"
  # The whole family is derived from that one hex, so hover, ink, deep and
  # dim move with it instead of staying orange.
  assert_contains "$html" '--accent-hover:#55abf2' "$page derives the hover accent"
  assert_contains "$html" '--accent-ink:#061018' "$page derives the ink accent"
  assert_contains "$html" '--accent-dim:rgba(62,160,240,0.16)' "$page derives the dim accent"
  assert_contains "$html" 'fill=%27%233ea0f0%27' "$page draws its favicon in the team accent"
  assert_not_contains "$html" 'fill=%27%23f0883e%27' "$page's favicon is not the default orange"
done

# A save answers with the head fragment too, so an open page recolors without
# a reload.
saved=$(curl -sf -X POST "$WEB/settings/team" -d 'name=Engineering' -d 'accent=#3ea0f0')
assert_contains "$saved" 'id="settings"' "a settings save patches the page body back"
assert_contains "$saved" 'id="accent"' "a settings save patches the head's accent rule"

# An unparseable stored accent falls back rather than emitting broken CSS.
# The field's max of 7 already keeps a whole CSS rule from fitting, so this
# writes the longest junk PocketBase will accept.
TEAM_ID=$(curl -sf "$LLL_URL/api/collections/teams/records?filter=$(python3 -c "import urllib.parse;print(urllib.parse.quote(\"key='ENG'\"))")" | jq -r '.items[0].id')
curl -sf -X PATCH "$LLL_URL/api/collections/teams/records/$TEAM_ID" \
  -H 'Content-Type: application/json' -d '{"accent":"};z{a:b"}' >/dev/null
assert_contains "$(curl -sf "$WEB/")" '<style id="accent"></style>' \
  "an unparseable stored accent falls back to the canonical orange"

# Choosing the canonical orange back stores nothing, so theme.css decides again.
curl -sf -X POST "$WEB/settings/team" -d 'name=Engineering' -d 'accent=#f0883e' >/dev/null
assert_contains "$(curl -sf "$WEB/")" '<style id="accent"></style>' \
  "picking the default orange clears the stored accent"

echo "e2e_web: all assertions passed"
