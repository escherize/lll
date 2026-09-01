#!/usr/bin/env bash
# e2e: the `lll up` web board against an ephemeral PocketBase.
# Covers: board page grouped by the six states with cards in the right
# columns, issue page (detail, comments, forms), the app shell's rail (one
# template, same on every page, absent from every broadcast), actions
# (/create, /state,
# /comment) persisting to PB and visible via the CLI, server-side validation,
# the /events SSE stream emitting datastar-patch-elements frames on
# CLI-driven changes (board scope and issue scope), workspace-wide favorites
# patching the rail's own group on every open page, static CSS serving, and —
# when playwright-cli is available — a real-browser check that a CLI-created
# issue appears on an open board without reload, and the zero-JavaScript
# /issues table (server-side sort and filter through query params, honest row
# count, bad params degrading to the flash strip), /search filtering as it is
# typed (results patched in with no page load, the address bar following the
# query, the X clearing both), the /projects list with its rail row, issue
# counts and project filter on /issues, and the create-more dialog keeping
# its state through back-to-back creates (task-159).
# Standalone (boots its own PB), also invoked by e2e.sh.
set -euo pipefail
. "$(dirname "$0")/lib.sh"   # free_port, wait_ok, fail, assert_*, e2e_begin/end
e2e_begin

PB_PORT=$(free_port 20000 39999)
WEB_PORT=$(free_port 40000 59999)
export LLL_URL="http://127.0.0.1:$PB_PORT"
export LLL_TEAM=ENG
WEB="http://127.0.0.1:$WEB_PORT"
# --- TASK-182: the board is gated --------------------------------------------
# Every route — pages, POSTs, /events, /static — answers only requests that
# carry the board token. The suite pins its own (LLL_BOARD_TOKEN) so the
# assertions are deterministic; the generated-token path (a fresh token per
# boot, printed as a login URL in the banner) is e2e_up.sh's section. The
# cookie is the browser's one login; wcurl is every authenticated request
# below. Anonymous curls stay plain `curl`.
BOARD_TOKEN=lll-web-e2e-board-token
BOARD_COOKIE="Cookie: lll_board=$BOARD_TOKEN"
wcurl() { curl -H "$BOARD_COOKIE" "$@"; }
PB_LOG="$DATA_DIR/pb.log"
SERVE_LOG="$DATA_DIR/serve.log"
E2E_LOGS="$SERVE_LOG $PB_LOG"
BROWSER_SESSION="e2e-web-$$"

# PocketBase is embedded in lll; one `lll up` is both the database and the
# board this suite exercises. Built here because it has to exist first.
lis build >/dev/null
LIN=target/.lisette/bin/lll

# USER is pinned: a first boot seeds a member named after it (task-31), and
# the board assertions must not depend on who runs this suite. HOME is pinned
# because that first boot WRITES 'me' to the home config now (TASK-168).
env -u LLL_TOKEN LLL_BOARD_TOKEN="$BOARD_TOKEN" USER=e2e HOME="$E2E_HOME" "$LIN" up --no-open \
  --pb-dir "$DATA_DIR/pb_data" --port "$WEB_PORT" \
  </dev/null >"$PB_LOG" 2>&1 &
PB_PID=$!
SERVE_PID=""
CURL_PID=""
cleanup() {
  if command -v playwright-cli >/dev/null 2>&1; then
    playwright-cli -s="$BROWSER_SESSION" close >/dev/null 2>&1 || true
  fi
  kill $CURL_PID $SERVE_PID $PB_PID 2>/dev/null || true
  e2e_end
}
trap cleanup EXIT

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

wait_ok "$LLL_URL/api/health" || fail "PocketBase did not start"

# --- TASK-181: the suite rides a member token --------------------------------
# The rules refuse tokenless requests now. The board itself keeps rendering
# because `lll up` defaults ITS process to the superuser token (the TASK-182
# handoff); the CLI verbs and the direct PB fixtures below use the member
# token a human login would get.
WEB_TOKEN=$(pb_member_token "$LLL_URL" web-e2e web-e2e@lll.test web-e2e-pass-123) \
  || fail "bootstrapping the web e2e member token"
[ -n "$WEB_TOKEN" ] && [ "$WEB_TOKEN" != "null" ] || fail "pb_member_token returned no token"
export LLL_TOKEN="$WEB_TOKEN"
AUTH_HDR="Authorization: Bearer $WEB_TOKEN"

curl -sf -H "$AUTH_HDR" -X POST "$LLL_URL/api/collections/teams/records" \
  -H 'Content-Type: application/json' \
  -d '{"key":"ENG","name":"Engineering"}' >/dev/null || true   # lll up already created ENG

"$LIN" issue create -t "Web board issue" --priority 2 >/dev/null
"$LIN" issue create -t "Already in progress" >/dev/null
"$LIN" issue update ENG-2 --state in-progress >/dev/null
"$LIN" issue comment ENG-1 -b "seed comment" >/dev/null
# A member with no issues, for the filter-that-matches-nothing assertions:
# a valid value the catalogue can name, carrying zero board cards (task-116).
"$LIN" member add -n "No Issues Here" >/dev/null

# the board came up with PocketBase above
wcurl -sf "$WEB/" >/dev/null || fail "lll up board did not start"

# --- TASK-182: the gate refuses the anonymous and admits the cookie ----------
anon_code=$(curl -s -o /dev/null -w '%{http_code}' "$WEB/")
[ "$anon_code" = "401" ] || fail "anonymous board fetch: expected 401, got $anon_code"
anon_page=$(curl -s "$WEB/")
assert_contains "$anon_page" "board_token" "401 page says how to get in"
assert_contains "$anon_page" "LLL_BOARD_TOKEN" "401 page names the env override"

# A POST with no token is refused before any write happens.
anon_post=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  -d "key=ENG-1&body=anonymous comment" "$WEB/comment")
[ "$anon_post" = "401" ] || fail "anonymous POST: expected 401, got $anon_post"

# The SSE endpoint sits behind the same gate.
anon_sse=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$WEB/events?page=board")
[ "$anon_sse" = "401" ] || fail "anonymous /events: expected 401, got $anon_sse"

# Static assets too: the 401 page is self-contained, so nothing else serves.
anon_static=$(curl -s -o /dev/null -w '%{http_code}' "$WEB/static/theme.css")
[ "$anon_static" = "401" ] || fail "anonymous /static: expected 401, got $anon_static"

# The query param is the bootstrap handoff: a GET that logs in with it is
# handed the cookie and redirected to the same URL without the token, so the
# token does not linger in the address bar.
login=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' "$WEB/?board_token=$BOARD_TOKEN")
assert_contains "$login" "303" "query-param login redirects"
assert_contains "$login" "$WEB/" "redirect strips the token from the URL"
login_hdrs=$(curl -si "$WEB/?board_token=$BOARD_TOKEN")
assert_contains "$login_hdrs" "Set-Cookie: lll_board=$BOARD_TOKEN" \
  "query-param login sets the board cookie"
assert_not_contains "$login_hdrs" "board_token=$BOARD_TOKEN" "redirect URL drops the token"

# TASK-202: a stale cookie must not veto a valid ?board_token= (and the valid
# link refreshes the cookie); a stale cookie alone stays refused.
stale=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: lll_board=STALE_TOKEN_FROM_A_PAST_BOOT" "$WEB/?board_token=$BOARD_TOKEN")
[ "$stale" = "303" ] || fail "stale cookie + valid token: expected 303, got $stale"
curl -s -D - -o /dev/null -H "Cookie: lll_board=STALE_TOKEN_FROM_A_PAST_BOOT" "$WEB/?board_token=$BOARD_TOKEN" \
  | grep -qi "^set-cookie: lll_board=$BOARD_TOKEN" || fail "valid token did not refresh the stale cookie"
stale_only=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: lll_board=STALE_TOKEN_FROM_A_PAST_BOOT" "$WEB/")
[ "$stale_only" = "401" ] || fail "stale cookie alone: expected 401, got $stale_only"

# With the cookie, the gate lets everything through — the first authenticated
# fetch below is the suite's own liveness probe.

# --- board page: six columns, cards in the right ones ---
board=$(wcurl -sf "$WEB/")
for state in backlog todo in-progress in-review done cancelled; do
  assert_contains "$board" "id=\"col-$state\"" "board has column $state"
done
assert_contains "$(column "$board" todo)" "ENG-1" "ENG-1 in todo column"
assert_contains "$(column "$board" todo)" "Web board issue" "ENG-1 title on card"
assert_contains "$(column "$board" in-progress)" "ENG-2" "ENG-2 in in-progress column"
assert_contains "$board" 'id="new-issue"' "board has new-issue form"
assert_contains "$board" "datastar" "board loads Datastar"
wcurl -sf "$WEB/static/theme.css" >/dev/null || fail "static css served"

# --- card presentation: relative age + server-rendered hover preview ---
assert_contains "$board" 'class="age"' "cards carry an age row"
assert_contains "$board" "just now" "card age is relative"
assert_contains "$board" 'class="card-pop"' "cards carry a hover preview"

ENG1_ID=$("$LIN" issue view ENG-1 --json | jq -r '.id')
ENG2_ID=$("$LIN" issue view ENG-2 --json | jq -r '.id')
[ -n "$ENG1_ID" ] && [ -n "$ENG2_ID" ] || fail "resolving issue ids for snippet seeds"
curl -sf -H "$AUTH_HDR" -X PATCH "$LLL_URL/api/collections/issues/records/$ENG1_ID" \
  -H 'Content-Type: application/json' \
  -d '{"description":"First preview line.\n\nSecond preview line.\nThird line never previewed."}' >/dev/null
LONG_DESC=$(printf 'a%.0s' $(seq 1 200))
curl -sf -H "$AUTH_HDR" -X PATCH "$LLL_URL/api/collections/issues/records/$ENG2_ID" \
  -H 'Content-Type: application/json' \
  -d "{\"description\":\"$LONG_DESC\"}" >/dev/null

board=$(wcurl -sf "$WEB/")
assert_contains "$board" "First preview line. Second preview line." "snippet joins the first two non-empty lines"
assert_not_contains "$board" "Third line never previewed" "snippet drops lines past the second"
assert_contains "$board" "$(printf 'a%.0s' $(seq 1 159))…" "long snippet truncated with an ellipsis"
assert_not_contains "$board" "$LONG_DESC" "full long description stays off the board"

# --- issue page ---
issue=$(wcurl -sf "$WEB/issue/ENG-1")
assert_contains "$issue" 'id="issue-detail"' "issue page has detail"
assert_contains "$issue" "Web board issue" "issue page has title"
assert_contains "$issue" "seed comment" "issue page has seed comment"
assert_contains "$issue" 'id="comment-form"' "issue page has comment form"
assert_contains "$issue" 'id="state-form"' "issue page has state control"
wcurl -s -o /dev/null -w '%{http_code}' "$WEB/issue/ENG-99" | grep -q 404 \
  || fail "unknown issue is a 404"

# --- TASK-205: the work-site slot on the web surfaces -------------------------
# `issue start` stamps work_branch/work_host/work_path; the props panel shows
# the whole site and the board hover shows the branch, both straight off the
# issue's own fields (so SSE morphs carry them for free). The fields are
# seeded the fixture way (a direct PATCH) — the start->stamp write path is
# e2e.sh's section. Without a claim the site is history and renders dimmed
# "(last seen)"; a claim row makes it current.
curl -sf -H "$AUTH_HDR" -X PATCH "$LLL_URL/api/collections/issues/records/$ENG2_ID" \
  -H 'Content-Type: application/json' \
  -d '{"work_branch":"eng-2-already-in-progress","work_host":"webhost","work_path":"/tmp/wt-eng-2"}' >/dev/null
issue=$(wcurl -sf "$WEB/issue/ENG-2")
assert_contains "$issue" '>Work</span>' "props panel has a Work row"
assert_contains "$issue" "eng-2-already-in-progress @ webhost:/tmp/wt-eng-2" "props panel shows the site"
assert_contains "$issue" "(last seen)" "an unclaimed site renders as last seen"
board=$(wcurl -sf "$WEB/")
assert_contains "$board" 'class="cp-work work-stale"' "hover preview carries the branch, dimmed"
assert_contains "$board" "eng-2-already-in-progress" "hover preview shows the branch"

# a claim makes the site current: no dimming on either surface
W205_MID=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/members/records?perPage=1" | jq -r '.items[0].id')
W205_CLAIM=$(curl -sf -H "$AUTH_HDR" -X POST "$LLL_URL/api/collections/claims/records" \
  -H 'Content-Type: application/json' \
  -d "{\"issue\":\"$ENG2_ID\",\"member\":\"$W205_MID\"}" | jq -r '.id')
[ -n "$W205_CLAIM" ] && [ "$W205_CLAIM" != "null" ] || fail "seeding the work-site claim"
issue=$(wcurl -sf "$WEB/issue/ENG-2")
assert_contains "$issue" "eng-2-already-in-progress @ webhost:/tmp/wt-eng-2" "props panel keeps the site"
assert_not_contains "$issue" "(last seen)" "a claimed site is not dimmed"
board=$(wcurl -sf "$WEB/")
assert_contains "$board" 'class="cp-work"' "hover branch is undimmed while claimed"
# put the claim back so later sections see the board they always saw
curl -sf -H "$AUTH_HDR" -X DELETE "$LLL_URL/api/collections/claims/records/$W205_CLAIM" >/dev/null

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
board=$(wcurl -sf "$WEB/")
board_rail=$(rail "$board")
[ -n "$board_rail" ] || fail "board page has no rail"
[ "$board_rail" = "$(rail "$issue")" ] || fail "the rail differs between the board and issue pages:
$(diff <(printf '%s' "$board_rail") <(rail "$issue") || true)"
assert_contains "$board_rail" 'href="/?assignee=e2e"' \
  "rail has a My issues row (the board's own URL encoding)"
assert_contains "$board_rail" 'id="rail-views"' "rail carries the saved views group"
assert_contains "$board_rail" "v0.1.0" "rail footer carries the version"

# The FAVORITES group ships in the rail even when empty, and says out loud
# that a star belongs to the workspace — auth is deferred (task-32), so the
# UI must not imply these are private.
assert_contains "$board_rail" 'id="rail-favorites"' "rail carries the favorites group"
assert_contains "$board_rail" "Shared by everyone here" "favorites are labelled shared, not personal"
assert_contains "$board_rail" "Star an issue to pin it here for the whole workspace." \
  "empty favorites group explains the star"

# My issues is a URL, not a special mode: the rail row is the board at
# /?assignee=e2e (the board's own query-param encoding — there is no
# ?mine=1 any more). The page marks the row current and seeds the chip the
# URL implies.
mine=$(wcurl -sf "$WEB/?assignee=e2e")
assert_contains "$mine" '<a href="/?assignee=e2e" title="Issues assigned to e2e" class="active">' \
  "the My issues URL marks the My issues row current"
assert_contains "$mine" 'data-signals:flt="[&#34;assignee:e2e&#34;]"' \
  "the My issues URL seeds the assignee filter chip"
# ...and because the columns are server-filtered by the URL's filter, an
# issue outside the filter is absent from the fragment entirely — the
# client-side $flt data-show guard exists for the SSE morphs, not the
# first paint.
assert_not_contains "$(column "$mine" todo)" "ENG-1" \
  "a URL-filtered board filters its own columns"

# A filter whose valid value matches nothing still renders its chip (active,
# count 0) and the bar says so out loud — the rescue affordance lives
# wherever the URL can point. "No Issues Here" is a real member; the board
# just carries no card for them (task-116's ?mine=1 scenario).
nomatch=$(wcurl -sf "$WEB/?assignee=No+Issues+Here")
assert_contains "$nomatch" 'No issues match these filters.' \
  "a filter matching nothing says so in the filter bar"
assert_contains "$nomatch" '<span class="dim">Assignee</span> No Issues Here <svg' \
  "a filter matching nothing still renders its own chip"

# A value the catalogue cannot name is dropped with a readable flash, never
# a 500 and never a silently half-applied filter.
nomember=$(wcurl -sf "$WEB/?assignee=nobody")
assert_contains "$nomember" "no member named &#39;nobody&#39;" \
  "an unknown assignee is said out loud in the flash"


# Hidden lanes ride the same URL: ?hide=done hides the done lane, and the
# lane's hide signal is seeded from the query param, not localStorage.
hidden=$(wcurl -sf "$WEB/?hide=done")
unhidden=$(wcurl -sf "$WEB/")
assert_contains "$unhidden" 'class="main"' "an unhidden board renders no lane hidden"
assert_not_contains "$unhidden" 'class="main hc-done"' \
  "the done lane is present on an unhidden board"
# The binding expression for the hidden class is rendered on every board;
# what differs is the class attribute and the seeded signal value.
assert_contains "$unhidden" "'hc-done': \$hide_done" "the lane's hide binding exists"
assert_contains "$hidden" "\$hide_done = true" "?hide=done seeds the lane's hide signal"
# The query lives in the URL, so a result is shareable and curl-able.
search=$(wcurl -sf "$WEB/search?q=Already")
assert_contains "$search" "ENG-2" "search finds the matching issue"
assert_contains "$search" "Already in progress" "search result carries the title"
# The proof that this is not the board's client-side filter: a non-matching
# issue is ABSENT from the markup, not shipped and hidden with CSS.
assert_not_contains "$search" "ENG-1" "search omits non-matching issues from the markup"
assert_not_contains "$search" 'id="board"' "search results are not the board fragment"
assert_not_contains "$search" "/events" "the search page opens no SSE stream to be morphed by"
assert_contains "$search" 'value="Already"' "the query round-trips into the field"
assert_contains "$board_rail" 'href="/search"' "rail has a Search row"
assert_contains "$(rail "$search")" 'href="/search" class="active"' \
  "the search page marks its own rail row current"
empty=$(wcurl -sf "$WEB/search?q=zzzznope")
assert_contains "$empty" "No issue title matches" "an empty result says so"
assert_not_contains "$empty" "ENG-1" "an empty result lists nothing"
assert_contains "$(wcurl -sf "$WEB/search")" 'class="search-bar"' \
  "/search with no query still renders the field"

# Typing (task-110) asks the SAME handler for the results fragment alone, as
# one datastar-patch-elements event, so the list on screen and the list that
# URL serves are rendered from one q by one code path.
assert_contains "$search" "data-bind:q" "the field binds the query to a signal"
assert_contains "$search" 'class="search-clear" href="/search"' \
  "the field carries an X back to the empty page"
frag=$(wcurl -sf "$WEB/search?fragment=1&q=Already")
assert_contains "$frag" "event: datastar-patch-elements" \
  "the live fragment is a datastar patch"
assert_contains "$frag" 'id="search-results"' \
  "the live fragment patches the results by id"
assert_contains "$frag" "ENG-2" "the live fragment carries the match"
assert_not_contains "$frag" "ENG-1" "the live fragment omits non-matching issues"
assert_not_contains "$frag" 'class="rail"' "the live fragment is not a whole page"
assert_contains "$(wcurl -sf "$WEB/search?fragment=1")" "Searches every issue" \
  "the live fragment with an empty query is the empty state"

# --- actions persist to PB and show via the CLI ---
out=$(wcurl -s -w '\n%{http_code}' -X POST \
  -d "title=Created from the board&state=todo" "$WEB/create")
printf '%s' "$out" | tail -1 | grep -q 200 || fail "/create should return 200"
assert_contains "$out" 'id="flash" class="flash" hidden' "/create success clears flash"
out=$("$LIN" issue list)
assert_contains "$out" "Created from the board" "web-created issue in lll issue list"

code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST \
  -d "key=ENG-3&state=in-review" "$WEB/state")
[ "$code" = 200 ] || fail "/state returned $code, want 200"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" "in-review" "web state change in lll issue view"
board=$(wcurl -sf "$WEB/")
assert_contains "$(column "$board" in-review)" "ENG-3" "ENG-3 moved to in-review column"

code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST \
  -d "key=ENG-3&body=comment from the board" "$WEB/comment")
[ "$code" = 200 ] || fail "/comment returned $code, want 200"
out=$("$LIN" issue comment ENG-3)
assert_contains "$out" "comment from the board" "web comment in lll issue comment"

# --- issue detail editing: /priority and /title persist, validate, render ---
code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST \
  -d "key=ENG-3&priority=urgent" "$WEB/priority")
[ "$code" = 200 ] || fail "/priority returned $code, want 200"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" "Priority:  urgent" "web priority change in lll issue view"

out=$(wcurl -s -X POST -d "key=ENG-3&priority=bogus" "$WEB/priority")
assert_contains "$out" "unknown priority &#39;bogus&#39;" "bogus priority message"
out=$(wcurl -s -X POST -d "key=ENG-99&priority=high" "$WEB/priority")
assert_contains "$out" "not found" "/priority unknown issue message"

code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST \
  --data-urlencode "key=ENG-3" --data-urlencode "title=Renamed from the board" \
  "$WEB/title")
[ "$code" = 200 ] || fail "/title returned $code, want 200"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" "ENG-3 Renamed from the board" "web title change in lll issue view"

out=$(wcurl -s -X POST --data-urlencode "key=ENG-3" --data-urlencode "title=  " "$WEB/title")
assert_contains "$out" "title is required" "blank title message"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" "ENG-3 Renamed from the board" "blank title left the title alone"

# titles with JSON-hostile characters survive the round trip
code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST \
  --data-urlencode "key=ENG-3" --data-urlencode 'title=Quote " and \ slash' \
  "$WEB/title")
[ "$code" = 200 ] || fail "/title with quotes returned $code, want 200"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" 'Quote " and \ slash' "quoted title persisted verbatim"

# --- /emoji: the picker's write path, including the way back to none ---
code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST \
  --data-urlencode "key=ENG-3" --data-urlencode "emoji=🚀" "$WEB/emoji")
[ "$code" = 200 ] || fail "/emoji returned $code, want 200"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" "Emoji:     🚀" "web emoji change in lll issue view"

# A picker with no way back to none is a trap: an empty value clears it.
code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST \
  --data-urlencode "key=ENG-3" --data-urlencode "emoji=" "$WEB/emoji")
[ "$code" = 200 ] || fail "/emoji clear returned $code, want 200"
out=$("$LIN" issue view ENG-3)
if printf '%s' "$out" | grep -q "^Emoji:"; then
  fail "empty emoji did not clear the marker"
fi

out=$(wcurl -s -X POST --data-urlencode "key=ENG-3" \
  --data-urlencode "emoji=not one emoji" "$WEB/emoji")
assert_contains "$out" "an issue takes one emoji" "sentence-shaped emoji rejected"
out=$(wcurl -s -X POST --data-urlencode "key=ENG-99" --data-urlencode "emoji=🚀" "$WEB/emoji")
assert_contains "$out" "not found" "/emoji unknown issue message"

# issue page markup: the picker ships with the page, searchable by name, and
# its chrome is sprite icons — the glyphs are only the candidates themselves.
issue=$(wcurl -sf "$WEB/issue/ENG-3")
assert_contains "$issue" 'id="emo-pop"' "issue page carries the emoji picker"
assert_contains "$issue" 'class="emo-trigger"' "properties panel has the picker trigger"
assert_contains "$issue" 'placeholder="Search by name"' "picker searches by name"
assert_contains "$issue" 'data-n="bug insect beetle broken"' "candidates carry search terms"
assert_contains "$issue" 'Remove emoji' "picker offers the way back to none"
assert_contains "$issue" 'href="#ic-close"' "picker chrome uses the shared sprite"
# The catalogue is page-only: a broadcast of #issue-detail must not carry it.
assert_contains "$(printf '%s' "$issue" | sed -n '/id="issue-detail"/,/<\/article>/p')" \
  "class=\"emo-trigger\"" "the trigger is inside the morph boundary"
if printf '%s' "$issue" | sed -n '/id="issue-detail"/,/<\/article>/p' | grep -q 'emo-cell'
then
  fail "the emoji grid leaked inside #issue-detail"
fi

# issue page markup: priority select (No priority label) + title editor
issue=$(wcurl -sf "$WEB/issue/ENG-3")
assert_contains "$issue" 'id="prio-form"' "issue page has priority control"
assert_contains "$issue" '>No priority</option>' "priority none reads No priority"
assert_contains "$issue" 'value="urgent" selected' "priority select reflects current value"
assert_contains "$issue" 'id="title-form"' "issue page has title editor"
board=$(wcurl -sf "$WEB/")
assert_contains "$board" 'Priority</span> No priority <span class="count">' \
  "board filter labels none as No priority (a navigation, not a button)"

# --- TASK-151: the issue page edits Assignee, Project and Labels ---
# The Properties panel gets the same controls the create dialog has: a
# select per scalar relation, chip checkboxes for the rel-multi. Every
# write below is re-verified by re-fetching the page — and the page only
# ever changes through the /events issue-detail broadcast, so those
# re-fetches are the repaint proof (AC#4); the POST itself answers with
# the flash strip alone.
"$LIN" project create -n "Panel Project" --status planned >/dev/null
"$LIN" label create -n "props-label" -c '#4cb782' >/dev/null
"$LIN" member add -n "Panel Member" >/dev/null
PANEL_PROJECT=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/projects/records?perPage=200" \
  | jq -r '.items[] | select(.name=="Panel Project") | .id')
PANEL_MEMBER=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/members/records?perPage=200" \
  | jq -r '.items[] | select(.name=="Panel Member") | .id')
PANEL_LABEL=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/labels/records?perPage=200" \
  | jq -r '.items[] | select(.name=="props-label") | .id')
[ -n "$PANEL_PROJECT" ] && [ -n "$PANEL_MEMBER" ] && [ -n "$PANEL_LABEL" ] \
  || fail "resolving Panel fixtures (project/member/label) for the issue page tests"

# AC#1: POST /project moves ENG-3 into a project; the re-fetched page
# links the new project.
code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST \
  --data-urlencode "key=ENG-3" --data-urlencode "project=$PANEL_PROJECT" "$WEB/project")
[ "$code" = 200 ] || fail "/project returned $code, want 200"
issue=$(wcurl -sf "$WEB/issue/ENG-3")
assert_contains "$issue" 'href="/issues?project=Panel&#43;Project"' "issue page links the new project"
assert_contains "$issue" "value=\"$PANEL_PROJECT\" selected" "project select reflects the move"
assert_contains "$("$LIN" issue view ENG-3)" "Project:   Panel Project" "POST /project persisted"

# AC#2: the assignee is changeable from the issue page, and back to none.
code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST \
  --data-urlencode "key=ENG-3" --data-urlencode "assignee=$PANEL_MEMBER" "$WEB/assignee")
[ "$code" = 200 ] || fail "/assignee returned $code, want 200"
issue=$(wcurl -sf "$WEB/issue/ENG-3")
assert_contains "$issue" "value=\"$PANEL_MEMBER\" selected" "assignee select reflects the change"
assert_contains "$("$LIN" issue view ENG-3)" "Assignee:  Panel Member" "POST /assignee persisted"
code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST \
  --data-urlencode "key=ENG-3" --data-urlencode "assignee=" "$WEB/assignee")
[ "$code" = 200 ] || fail "/assignee clear returned $code, want 200"
assert_contains "$("$LIN" issue view ENG-3)" "Assignee:  none" "empty assignee unassigns"

# The page renders all three editors from the catalogues.
issue=$(wcurl -sf "$WEB/issue/ENG-3")
assert_contains "$issue" 'id="assignee-form"' "issue page has an assignee select"
assert_contains "$issue" 'id="project-form"' "issue page has a project select"
assert_contains "$issue" 'id="labels-form"' "issue page has the label chips"

# AC#3: add a label, then remove it — the form posts the whole set, so
# removal is a POST with no labels at all.
code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST \
  --data-urlencode "key=ENG-3" --data-urlencode "labels=$PANEL_LABEL" "$WEB/labels")
[ "$code" = 200 ] || fail "/labels add returned $code, want 200"
issue=$(wcurl -sf "$WEB/issue/ENG-3")
assert_contains "$issue" ">props-label</span>" "the added label renders as a chip"
assert_contains "$issue" "value=\"$PANEL_LABEL\" checked" "the added label comes back checked"
assert_contains "$("$LIN" issue view ENG-3)" "Labels:    props-label" "POST /labels persisted"
code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST \
  --data-urlencode "key=ENG-3" "$WEB/labels")
[ "$code" = 200 ] || fail "/labels clear returned $code, want 200"
assert_contains "$("$LIN" issue view ENG-3)" "Labels:    none" "empty /labels removed the label"
issue=$(wcurl -sf "$WEB/issue/ENG-3")
if printf '%s' "$issue" | grep -q "value=\"$PANEL_LABEL\" checked"; then
  fail "empty /labels left the chip checked"
fi

# --- related findings on the issue page (TASK-103): unprompted, server-
# rendered with the page. A finding whose area names a label the issue
# carries surfaces with no link and no click; a finding explicitly linked
# to the issue always shows; an issue with no matches renders no section at
# all — no empty-heading clutter.
printf 'Migrations collide when two agents mint one.' | "$LIN" doc new \
  -s web-migrations -t "Migration collisions" -k finding -a props -p "pb/pb_migrations" -b - >/dev/null
printf 'Bindgen needs darwin.' | "$LIN" doc new -s darwin-only -t "Gate is darwin-only" -k finding -p "gopb" -b - >/dev/null
"$LIN" issue link ENG-2 darwin-only >/dev/null
"$LIN" label create -n props >/dev/null
"$LIN" issue update ENG-1 --label props >/dev/null

issue=$(wcurl -sf "$WEB/issue/ENG-1")
assert_contains "$issue" 'id="related-findings"' "issue page renders the related findings section"
assert_contains "$issue" "web-migrations" "an area-matched finding surfaces unprompted"
assert_not_contains "$issue" "darwin-only" "an unlinked, unmatched finding stays off the issue"
issue=$(wcurl -sf "$WEB/issue/ENG-2")
assert_contains "$issue" "darwin-only" "a linked finding shows on its own issue's page"

# The raw form carries the same list — everything is curl-able (task-104).
raw=$(wcurl -sf "$WEB/issue/ENG-1?raw")
assert_contains "$raw" "## Related findings" "issue raw carries related findings"
assert_contains "$raw" "web-migrations (props): Migration collisions" "issue raw lists the finding"

issue=$(wcurl -sf "$WEB/issue/ENG-3")
if printf '%s' "$issue" | grep -q 'id="related-findings"'; then
  fail "an issue with no matches renders no findings section"
fi

# Unknown ids are refused, in the flash strip's voice.
out=$(wcurl -s -X POST --data-urlencode "key=ENG-3" --data-urlencode "project=bogus" "$WEB/project")
assert_contains "$out" "unknown project" "unknown project message"
out=$(wcurl -s -X POST --data-urlencode "key=ENG-3" --data-urlencode "assignee=nosuchid" "$WEB/assignee")
assert_contains "$out" "unknown member" "unknown member message"
out=$(wcurl -s -X POST --data-urlencode "key=ENG-3" --data-urlencode "labels=nosuchid" "$WEB/labels")
assert_contains "$out" "unknown label" "unknown label message"

# AC#4: the repaint is the existing broadcast. The write path (the POST)
# answers with the flash strip alone — no markup, so the page cannot have
# been repainted by the response — and the issue-scope SSE frame is what
# carries the new value to the open page.
PANEL_EVENTS="$DATA_DIR/events-panel.txt"
wcurl -sN "$WEB/events?page=issue&key=ENG-3" >"$PANEL_EVENTS" &
PANEL_PID=$!
sleep 0.5
wcurl -s -o /dev/null -X POST --data-urlencode "key=ENG-3" \
  --data-urlencode "project=$PANEL_PROJECT" "$WEB/project"
for _ in $(seq 1 50); do
  grep -q 'id="project-form"' "$PANEL_EVENTS" 2>/dev/null && break
  sleep 0.1
done
kill $PANEL_PID 2>/dev/null || true
PANEL_PID=""
panel_events=$(cat "$PANEL_EVENTS")
assert_contains "$panel_events" 'id="issue-detail"' "issue broadcast morphs #issue-detail"
assert_contains "$panel_events" "value=\"$PANEL_PROJECT\" selected" \
  "the broadcast carries the repainted editor"
resp=$(wcurl -s -X POST --data-urlencode "key=ENG-3" --data-urlencode "assignee=$PANEL_MEMBER" "$WEB/assignee")
assert_contains "$resp" 'id="flash"' "the write path answers with the flash strip"
assert_not_contains "$resp" 'id="issue-detail"' "the POST ships no markup — no double update"

# --- drag-and-drop path: /state accepts query params with an empty body ---
code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST "$WEB/state?key=ENG-3&state=done")
[ "$code" = 200 ] || fail "query-param /state returned $code, want 200"
out=$("$LIN" issue view ENG-3)
assert_contains "$out" "done" "query-param state change persisted"

# --- markdown comments render; raw HTML stays inert ---
"$LIN" issue comment ENG-1 -b "has **bold** and \`code\` <script>alert(1)</script>" >/dev/null
issue=$(wcurl -sf "$WEB/issue/ENG-1")
assert_contains "$issue" "<strong>bold</strong>" "markdown bold rendered"
assert_contains "$issue" "<code>code</code>" "markdown code rendered"
printf '%s' "$issue" | grep -qF "<script>alert(1)</script>" && fail "raw HTML not neutralized in comment"

# --- hard wraps: one newline is a line break, the way GitHub comments do it
# (task-45). CommonMark would collapse it to a space.
"$LIN" issue comment ENG-1 -b "wrapped line one
wrapped line two" >/dev/null
issue=$(wcurl -sf "$WEB/issue/ENG-1")
assert_contains "$issue" "wrapped line one<br>" "single newline in a comment becomes a line break"

# --- validation: errors arrive as visible flash patches, never silence ---
out=$(wcurl -s -X POST -d "title=&state=todo" "$WEB/create")
assert_contains "$out" "datastar-patch-elements" "empty title patches flash"
assert_contains "$out" "title is required" "empty title message"
out=$(wcurl -s -X POST -d "key=ENG-3&state=bogus" "$WEB/state")
assert_contains "$out" "unknown state" "bogus state message"
out=$(wcurl -s -X POST -d "key=ENG-3&body=" "$WEB/comment")
assert_contains "$out" "comment body is required" "empty comment message"

# --- no team configured: up refuses rather than booting half-configured ---
NOTEAM_PORT=$(free_port 40000 59999)
# The invariant is that the refusal changes nothing — not that the file is
# absent. HOME is pinned so the developer's own config cannot supply a team
# and turn the refusal into a boot: config layers now (TASK-168).
TOML_BEFORE=$(cat .lll.toml 2>/dev/null || true)
if out=$(env -u LLL_TEAM LLL_TEAM="" HOME="$E2E_HOME" "$LIN" up --no-open --port "$NOTEAM_PORT" </dev/null 2>&1); then
  fail "lll up with no team should exit non-zero, got: $out"
fi
assert_contains "$out" "no team configured" "no-team boot refused"
assert_contains "$out" "LLL_TEAM=ENG" "refusal suggests the existing team"
[ "$(cat .lll.toml 2>/dev/null || true)" = "$TOML_BEFORE" ] \
  || fail "refused boot wrote to .lll.toml: $(cat .lll.toml)"

# --- /events: board scope gets a patch frame after a CLI-driven update ---
EVENTS_FILE="$DATA_DIR/events.txt"
wcurl -sN "$WEB/events?page=board" >"$EVENTS_FILE" &
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
wcurl -sN "$WEB/events?page=issue&key=ENG-1" >"$EVENTS_FILE" &
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
board=$(wcurl -sf "$WEB/")
got=$(col_order "$board" todo)
[ "$got" = "ENG-4,ENG-5,ENG-6" ] || fail "new issues in creation order: got '$got'"

A_ID=$(issue_id "Order A"); B_ID=$(issue_id "Order B")
[ -n "$A_ID" ] && [ -n "$B_ID" ] || fail "resolving Order A/B record ids"

# Reorder to the top of the column.
code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST "$WEB/state?key=ENG-6&state=todo&before=$A_ID")
[ "$code" = 200 ] || fail "/state with before returned $code, want 200"
got=$(col_order "$(wcurl -sf "$WEB/")" todo)
[ "$got" = "ENG-6,ENG-4,ENG-5" ] || fail "reorder to top: got '$got'"

# Reorder to the middle (fractional midpoint between two neighbors).
wcurl -s -o /dev/null -X POST "$WEB/state?key=ENG-6&state=todo&before=$B_ID"
got=$(col_order "$(wcurl -sf "$WEB/")" todo)
[ "$got" = "ENG-4,ENG-6,ENG-5" ] || fail "reorder to middle: got '$got'"

# No `before` means end of column.
wcurl -s -o /dev/null -X POST "$WEB/state?key=ENG-4&state=todo"
got=$(col_order "$(wcurl -sf "$WEB/")" todo)
[ "$got" = "ENG-6,ENG-5,ENG-4" ] || fail "reorder to end: got '$got'"

# Cross-column drop with a position: state and sort change in one action.
wcurl -s -o /dev/null -X POST "$WEB/state?key=ENG-2&state=todo&before=$B_ID"
board=$(wcurl -sf "$WEB/")
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
code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST "$WEB/state?key=ENG-6&state=todo&before=$DOOMED_ID")
[ "$code" = 200 ] || fail "/state with stale before returned $code, want 200"
got=$(col_order "$(wcurl -sf "$WEB/")" todo)
[ "$got" = "ENG-2,ENG-5,ENG-4,ENG-6" ] || fail "stale before falls back to end: got '$got'"

# --- browser-level: CLI create appears on an open board without reload ---
if command -v playwright-cli >/dev/null 2>&1; then
  # The gate: the browser logs in through the banner's handoff URL once —
  # the 303 sets the cookie — and every later navigation rides it.
  playwright-cli -s="$BROWSER_SESSION" open "$WEB/?board_token=$BOARD_TOKEN" >/dev/null 2>&1 \
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
  # --- Board, My issues, Board (task-109) in the URL era ---
  # The original bug: a seeded chip hid every card while rendering NO chip to
  # explain or undo it. Chip and filter signal are both derived from the URL
  # now, so the sequence asserts the affordance survives the whole round
  # trip: filter, leave, come back, clear.
  seq_probe() { # -> {visible, chips}
    playwright-cli -s="$BROWSER_SESSION" eval \
      "() => JSON.stringify({visible: [...document.querySelectorAll('.card')].filter(c => c.offsetParent !== null).length, chips: [...document.querySelectorAll('.flt-chip')].filter(c => c.offsetParent !== null).length})" \
      | sed -n '/### Result/{n;p;}' | tr -d '\\'
  }
  # Datastar mounts on load; settle before probing so a slow box does not
  # read the chips before the signals exist.
  seq_goto() { playwright-cli -s="$BROWSER_SESSION" goto "$1" >/dev/null 2>&1 || fail "playwright: goto $1"; sleep 0.5; }

  # One issue actually assigned to `me`, so the filter has something to match.
  "$LIN" issue create -t "Assigned to me" --assignee e2e >/dev/null

  seq_goto "$WEB/"
  playwright-cli -s="$BROWSER_SESSION" eval "() => localStorage.clear()" >/dev/null 2>&1
  seq_goto "$WEB/"
  step1=$(seq_probe)
  all=$(printf '%s' "$step1" | sed -n 's/.*"visible":\([0-9]*\).*/\1/p')
  [ "${all:-0}" -gt 0 ] || fail "task-109 step 1: board opened with no visible cards ($step1)"
  assert_contains "$step1" '"chips":0' "task-109 step 1: Board opens unfiltered"

  seq_goto "$WEB/?assignee=e2e"
  step2=$(seq_probe)
  assert_contains "$step2" '"chips":1' "task-109 step 2: My issues shows the assignee chip"
  mine_visible=$(printf '%s' "$step2" | sed -n 's/.*"visible":\([0-9]*\).*/\1/p')
  [ "${mine_visible:-0}" -lt "$all" ] \
    || fail "task-109 step 2: My issues did not actually filter ($step2 vs $all)"

  # Coming back to a bare / restores the LAST VIEW from localStorage — a
  # convenience only, and the chip comes back WITH it, visibly. The URL is
  # what is restored, so the address bar says what the board is filtered by.
  seq_goto "$WEB/"
  step3=$(seq_probe)
  assert_contains "$step3" '"chips":1' \
    "task-109 step 3: the restored view brings its chip back, visibly"
  restored=$(playwright-cli -s="$BROWSER_SESSION" eval "() => location.pathname + location.search" \
    | sed -n '/### Result/{n;p;}' | tr -d '\\')
  assert_contains "$restored" "/?assignee=e2e" \
    "task-109 step 3: the restore lands on the view's own URL"
  assert_contains "$step3" "\"visible\":$mine_visible" \
    "task-109 step 3: the restored view actually filters"

  # The chip IS the undo: clicking it toggles its value out of the URL.
  playwright-cli -s="$BROWSER_SESSION" click ".flt-chip" >/dev/null 2>&1 \
    || fail "playwright: clicking the chip"
  sleep 0.5
  assert_contains "$(seq_probe)" '"chips":0' "clicking the chip clears the filter"
  assert_contains "$(seq_probe)" "\"visible\":$all" "clearing the chip brings every card back"

  # Clear removes the last-view record too, so the next bare / stays bare.
  seq_goto "$WEB/?assignee=e2e"
  playwright-cli -s="$BROWSER_SESSION" click ".flt-clear" >/dev/null 2>&1 \
    || fail "playwright: clicking Clear"
  sleep 0.5
  assert_contains "$(seq_probe)" '"chips":0' "Clear resets the board"
  seq_goto "$WEB/"
  assert_contains "$(seq_probe)" '"chips":0' "Clear also cleared the last-view record"

  # --- /search filters as you type, and the X clears it (task-110) ---
  # A SEQUENCE, not an end state: the probe on <body> survives a fragment
  # morph and dies in a page load, so it is what tells "typed and the list
  # was patched" apart from "the form submitted and the page came back".
  #
  # Polled, not slept: the patch lands on the browser's schedule, and a fixed
  # sleep is how a green suite turns red on a loaded machine. The poll only
  # decides WHEN to look; the assertions below still judge what it saw.
  page_state() { # js -> the eval's result line
    playwright-cli -s="$BROWSER_SESSION" eval "$1" \
      | sed -n '/### Result/{n;p;}' | tr -d '\\'
  }
  page_until() { # js needle
    local out=""
    for _ in $(seq 1 40); do
      out=$(page_state "$1")
      case "$out" in *"$2"*) break ;; esac
      sleep 0.25
    done
    printf '%s' "$out"
  }
  playwright-cli -s="$BROWSER_SESSION" goto "$WEB/search" >/dev/null 2>&1 \
    || fail "playwright: opening /search"
  playwright-cli -s="$BROWSER_SESSION" eval \
    "() => { document.body.dataset.probe = 'kept'; return 'ok' }" >/dev/null 2>&1
  playwright-cli -s="$BROWSER_SESSION" type "Already" >/dev/null 2>&1 \
    || fail "playwright: typing in the search field"
  typed=$(page_until \
    "() => JSON.stringify({url: location.pathname + location.search, doc: document.body.dataset.probe || 'RELOADED', rows: [...document.querySelectorAll('.sr-title')].map(e => e.textContent), x: getComputedStyle(document.querySelector('.search-clear')).display})" \
    "Already in progress")
  assert_contains "$typed" "Already in progress" "browser: typing filtered without Enter"
  assert_not_contains "$typed" "Web board issue" "browser: non-matching issues stay out of the list"
  assert_contains "$typed" '"doc":"kept"' "browser: typing patched the results, it did not reload"
  assert_contains "$typed" '"url":"/search?q=Already"' "browser: the address bar carries what was typed"
  assert_not_contains "$typed" '"x":"none"' "browser: the clear X shows once there is a query"
  # The X is a link to the empty page, so this navigation IS the behaviour:
  # it empties the field and puts the URL back to a bare /search.
  playwright-cli -s="$BROWSER_SESSION" click ".search-clear" >/dev/null 2>&1 \
    || fail "playwright: clicking the clear X"
  cleared=$(page_until \
    "() => JSON.stringify({url: location.pathname + location.search, field: document.querySelector('.search-bar input').value, rows: document.querySelectorAll('.sr-title').length, note: document.querySelector('.search-note').textContent})" \
    '"field":""')
  assert_contains "$cleared" '"url":"/search"' "browser: the X returns to the bare /search URL"
  assert_contains "$cleared" '"field":""' "browser: the X empties the field"
  assert_contains "$cleared" '"rows":0' "browser: the X clears the results"
  assert_contains "$cleared" "Searches every issue in the team" "browser: the X returns the empty state"
  # --- task-94: the save-view affordance in a real browser -----------------
  # Reveal the form, name the view, submit: the rail gains the view without
  # a reload (the SSE patch does the pinning), and clicking the view
  # navigates to the filtered board.
  seq_goto "$WEB/?prio=urgent"
  playwright-cli -s="$BROWSER_SESSION" eval "() => localStorage.clear()" >/dev/null 2>&1
  seq_goto "$WEB/?prio=urgent"
  playwright-cli -s="$BROWSER_SESSION" click ".flt-save" >/dev/null 2>&1 \
    || fail "playwright: clicking Save view"
  # The reveal is a signal flip; give Datastar a beat before typing.
  sleep 0.3
  playwright-cli -s="$BROWSER_SESSION" click ".sv-form input[name=name]" >/dev/null 2>&1 \
    || fail "playwright: focusing the view name field"
  playwright-cli -s="$BROWSER_SESSION" type "Browser urgent" >/dev/null 2>&1 \
    || fail "playwright: naming the view"
  playwright-cli -s="$BROWSER_SESSION" click ".sv-form button[type=submit]" >/dev/null 2>&1 \
    || fail "playwright: submitting the view"
  saved_view=$(page_until "() => JSON.stringify({rail: document.getElementById('rail-views').textContent, navs: performance.getEntriesByType('navigation').length})" "Browser urgent")
  assert_contains "$saved_view" "Browser urgent" "browser: saving a view pins it in the rail"
  assert_contains "$saved_view" '"navs":1' "browser: saving a view did not reload the page"
  playwright-cli -s="$BROWSER_SESSION" eval "() => document.querySelector('#rail-views a').click()" >/dev/null 2>&1 \
    || fail "playwright: clicking the saved view"
  clicked_view=$(page_until "() => JSON.stringify({url: location.pathname + location.search, chips: [...document.querySelectorAll('.flt-chip')].length})" '"chips":1')
  assert_contains "$clicked_view" '"url":"/?prio=urgent"' \
    "browser: clicking a saved view navigates to its URL"

  # --- create more: the dialog stays open for the next issue (task-159) ---
  # The toggle is a preference signal on #ni-modal, outside the morph and
  # the form reset. Submitting with it on posts the SAME /create, the
  # server closes the dialog as always, and the client reopens it ---
  # clearing title and description, keeping the scoping fields. The board
  # repaint is the existing broadcast: navs stays 1 throughout.
  seq_goto "$WEB/"
  more_js="() => JSON.stringify({open: getComputedStyle(document.querySelector('.ni-shade')).display !== 'none', title: document.getElementById('ni-title').value, desc: document.getElementById('ni-desc').value, focused: document.activeElement === document.getElementById('ni-title'), more: document.getElementById('ni-more').checked, assignee: document.querySelector('#ni-form select[name=assignee]').value, one: [...document.querySelectorAll('.card .title')].some(e => e.textContent === 'Create more one'), two: [...document.querySelectorAll('.card .title')].some(e => e.textContent === 'Create more two'), off: [...document.querySelectorAll('.card .title')].some(e => e.textContent === 'Create more off'), navs: performance.getEntriesByType('navigation').length, flash: document.getElementById('flash').textContent})"
  # A submit click can be swallowed while the page is still settling after
  # the last-view restore redirect (seen under e2e load: playwright reports
  # the click, the button's handler never runs, the POST is never sent).
  # Click again until the probe shows the POST went through --- an extra
  # click is harmless, an empty title just refocuses the field.
  ni_submit() { # needle --- click create until the probe matches
    local out=""
    for _ in 1 2 3 4; do
      playwright-cli -s="$BROWSER_SESSION" click "#ni-create" >/dev/null 2>&1 || true
      out=$(page_until "$more_js" "$1")
      case "$out" in *"$1"*) break ;; esac
    done
    printf '%s' "$out"
  }
  playwright-cli -s="$BROWSER_SESSION" click "#ni-expand" >/dev/null 2>&1 \
    || fail "playwright: opening the create dialog"
  sleep 0.4
  playwright-cli -s="$BROWSER_SESSION" click "#ni-more" >/dev/null 2>&1 \
    || fail "playwright: enabling Create more"
  scoped=$(playwright-cli -s="$BROWSER_SESSION" eval \
    "() => { const s = document.querySelector('#ni-form select[name=assignee]'); if (s.options.length > 1) s.selectedIndex = 1; s.dispatchEvent(new Event('change', {bubbles: true})); return s.value }" \
    | sed -n '/### Result/{n;p;}' | tr -d '\\' | tr -d '"')
  playwright-cli -s="$BROWSER_SESSION" fill "#ni-title" "Create more one" >/dev/null 2>&1 \
    || fail "playwright: typing the first Create-more title"
  first=$(ni_submit '"one":true,"navs":1')
  assert_contains "$first" '"open":true' "task-159: submitting with Create more keeps the dialog open"
  assert_contains "$first" '"title":""' "task-159: the title is cleared for the next issue"
  assert_contains "$first" '"desc":""' "task-159: the description is cleared for the next issue"
  assert_contains "$first" "\"assignee\":\"$scoped\"" "task-159: the scoping select survives the submit"
  assert_contains "$first" '"one":true' "task-159: the new card repainted behind the open dialog"
  assert_contains "$first" '"navs":1' "task-159: the repaint came from the broadcast, not a reload"
  playwright-cli -s="$BROWSER_SESSION" fill "#ni-title" "Create more two" >/dev/null 2>&1 \
    || fail "playwright: typing the second Create-more title"
  second=$(ni_submit '"two":true')
  assert_contains "$second" '"open":true' "task-159: the dialog is still open for a third entry"
  assert_contains "$second" "\"assignee\":\"$scoped\"" "task-159: the scoping select survives the second submit"
  # Toggle off: the old behavior returns --- submit closes the dialog.
  playwright-cli -s="$BROWSER_SESSION" click "#ni-more" >/dev/null 2>&1 \
    || fail "playwright: disabling Create more"
  playwright-cli -s="$BROWSER_SESSION" fill "#ni-title" "Create more off" >/dev/null 2>&1 \
    || fail "playwright: typing the toggle-off title"
  turned_off=$(ni_submit '"off":true')
  assert_contains "$turned_off" '"open":false' "task-159: with the toggle off the dialog closes as before"
  # The preference is a signal, not a form field: it outlives opens and
  # closes without a reload (el.reset() re-applies it on every open).
  playwright-cli -s="$BROWSER_SESSION" click "#ni-expand" >/dev/null 2>&1 \
    || fail "playwright: reopening the create dialog"
  sleep 0.4
  playwright-cli -s="$BROWSER_SESSION" click "#ni-more" >/dev/null 2>&1 \
    || fail "playwright: re-enabling Create more"
  playwright-cli -s="$BROWSER_SESSION" press Escape >/dev/null 2>&1
  sleep 0.3
  playwright-cli -s="$BROWSER_SESSION" click "#ni-expand" >/dev/null 2>&1 \
    || fail "playwright: reopening the create dialog"
  sleep 0.4
  assert_contains "$(page_until "$more_js" '"open":true')" '"more":true' \
    "task-159: the toggle keeps its state across dialog opens"
  # A failed create must not clear anything: a hidden first `state` field
  # makes the server answer "unknown state 'bogus'" through the flash.
  playwright-cli -s="$BROWSER_SESSION" eval \
    "() => { const h = document.createElement('input'); h.type = 'hidden'; h.name = 'state'; h.value = 'bogus'; document.getElementById('ni-form').prepend(h); return 'ok' }" >/dev/null 2>&1
  playwright-cli -s="$BROWSER_SESSION" fill "#ni-title" "Create more doomed" >/dev/null 2>&1 \
    || fail "playwright: typing the doomed title"
  rejected=$(ni_submit 'unknown state')
  assert_contains "$rejected" '"title":"Create more doomed"' "task-159: a failed create keeps the typed title"
  assert_contains "$rejected" '"open":true' "task-159: a failed create keeps the dialog open"
  assert_contains "$rejected" '"focused":true' "task-159: a failed create returns focus to the title"
  "$LIN" issue list | grep -q "Create more doomed" \
    && fail "task-159: a failed Create-more submit wrote a record" || true

  playwright-cli -s="$BROWSER_SESSION" close >/dev/null 2>&1 || true
  echo "e2e_web: browser-level realtime check passed"
  echo "e2e_web: browser-level /search live-typing check passed"
else
  echo "e2e_web: playwright-cli not found — skipped browser-level check" >&2
fi

# --- issue descriptions render markdown, like comments (task-21) ---
"$LIN" issue update ENG-1 --description '## Heading

Some **bold** text and `code`.

<script>alert(1)</script>' >/dev/null
page=$(wcurl -sf "$WEB/issue/ENG-1")
assert_contains "$page" '<div class="desc md">' "description uses the shared markdown container"
assert_contains "$page" "<h2>Heading</h2>" "description renders a markdown heading"
assert_contains "$page" "<strong>bold</strong>" "description renders bold"
assert_contains "$page" "<code>code</code>" "description renders inline code"
assert_not_contains "$page" "<script>alert" "raw HTML in a description stays out of the page"

# --- descriptions hard-wrap too, and raw HTML stays dropped (task-45) ---
"$LIN" issue update ENG-1 --description 'desc line one
desc line two

<b>raw</b> markup' >/dev/null
page=$(wcurl -sf "$WEB/issue/ENG-1")
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
page=$(wcurl -sf "$WEB/issue/ENG-1")
assert_contains "$page" "<th>pick</th>" "GFM table renders as a table"
assert_not_contains "$page" "| pick | why |" "GFM table is not left as literal pipes"
assert_contains "$page" "<del>dropped</del>" "GFM strikethrough renders"
assert_contains "$page" '<a href="https://example.com/gfm">' "GFM autolink renders"
assert_contains "$page" 'type="checkbox"' "GFM task list renders a checkbox"
assert_contains "$page" 'class="chroma"' "fenced code is highlighted server-side"
assert_not_contains "$page" 'style="color:#' "chroma emits classes, not inline colors"
assert_contains "$page" '<code class="language-mermaid">' "a mermaid fence is left plain for the client"
assert_contains "$page" '/static/mermaid-init.js' "the issue page loads the mermaid initializer"
wcurl -sfI "$WEB/static/mermaid.min.js" >/dev/null || fail "vendored mermaid.min.js is not served"
wcurl -sfI "$WEB/static/mermaid-init.js" >/dev/null || fail "mermaid-init.js is not served"


# --- /issues: a sortable, filterable, bookmarkable table (task-82) ---
# The point of the table is that its whole state is in the URL, so every
# assertion below is one curl of a URL an agent could type.
issues=$(wcurl -sf "$WEB/issues") || fail "/issues did not serve"
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
  wcurl -sf "$WEB$1" | python3 -c '
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
todo=$(wcurl -sf "$WEB/issues?state=todo")
assert_contains "$todo" '<option value="todo" selected>' "the chooser shows the filter the URL asked for"
assert_contains "$todo" 'class="itbl-clear"' "a filtered table offers a way back to all issues"
# A dedicated pair, so the filter assertion does not depend on what earlier
# sections left the shared issues in.
"$LIN" issue create -t "Table filter subject" >/dev/null
subject=$("$LIN" issue list --search "Table filter subject" | awk '{print $1}' | head -1)
"$LIN" issue update "$subject" --state in-review >/dev/null
in_review=$(wcurl -sf "$WEB/issues?state=in-review")
assert_contains "$in_review" "Table filter subject" "?state=in-review keeps the in-review issue"
assert_contains "$in_review" 'value="in-review" selected' "the state chooser reflects the URL"
"$LIN" issue update "$subject" --state done >/dev/null
gone=$(wcurl -sf "$WEB/issues?state=in-review")
assert_not_contains "$gone" "Table filter subject" "?state=in-review drops it once it moves on"

# The count is honest rather than a bare row tally.
assert_contains "$issues" 'class="itbl-count"' "the table states how many issues it is showing"

# A stale bookmark degrades to the unfiltered table plus the flash strip — the
# system's one error voice — never a 500.
bad=$(wcurl -sf "$WEB/issues?sort=bogus") || fail "a bad sort param returned an error status"
assert_contains "$bad" 'class="flash"' "an unknown sort field is reported in the flash strip"
assert_contains "$bad" "unknown sort field" "the flash names the rejected field"
assert_contains "$bad" '<table id="issues"' "an unknown sort field still serves the table"
bad_state=$(wcurl -sf "$WEB/issues?state=nope") || fail "a bad state param returned an error status"
assert_contains "$bad_state" "unknown state" "an unknown state is reported too"

# One rail template: the same rows on every page, differing only in which row
# reads as current. Adding this page did not touch the board's template.
issues_rail=$(rail "$issues")
rail_rows() { printf '%s' "$1" | grep -o 'href="[^"]*"' | sort; }
# The rail is live data now (favorites, saved views), so both sides are
# fetched at the same moment — a snapshot from before the browser block
# would legitimately differ by the views saved since.
board_rail_now=$(rail "$(wcurl -sf "$WEB/")")
[ "$(rail_rows "$issues_rail")" = "$(rail_rows "$board_rail_now")" ] \
  || fail "the board and issues rails offer different destinations:
$(diff <(rail_rows "$board_rail_now") <(rail_rows "$issues_rail") || true)"
assert_contains "$issues_rail" 'href="/issues"' "the rail has an All issues row"
assert_contains "$board_rail" 'href="/issues"' "the board's rail has it too"
assert_contains "$issues_rail" '<a href="/issues" class="active">' "the All issues row is current on its own page"
assert_not_contains "$issues_rail" '<a href="/" class="active">' "and the board row is not"
# --- /projects: the read path a project never had (task-113) ---
# Projects have been in the schema since the start and issues have always
# related to them, but until this page the only place one was ever SHOWN was
# the settings row that manages it. Every assertion here is a read path.
"$LIN" project create -n "Ship the board" --status started \
  -d "The web board and everything it needs." >/dev/null
"$LIN" issue create -t "Project member issue" --project "Ship the board" >/dev/null
pj_key=$("$LIN" issue list --search "Project member issue" | awk '{print $1}' | head -1)
[ -n "$pj_key" ] || fail "the issue created into a project was not found"

projects=$(wcurl -sf "$WEB/projects") || fail "/projects did not serve"
assert_contains "$projects" 'id="projects"' "the projects page carries its stable id"
assert_contains "$projects" "Ship the board" "the project is listed by name"
assert_contains "$projects" "Started" "the list shows the project status"
assert_contains "$projects" "The web board and everything it needs." \
  "the list shows the description only the CLI could write"
assert_contains "$projects" 'href="/issues?project=Ship&#43;the&#43;board"' \
  "each row links into the issues table filtered to that project"
assert_contains "$projects" "1 issue" "the row counts the issues pointing at it"
assert_contains "$projects" 'var(--st-in-progress)' \
  "a started project borrows a state hue rather than a new colour"

# Same reasoning as /issues and /settings: the bridge broadcasts one
# unfiltered #board to every board-scoped client, so this page subscribes to
# nothing and loads no script to subscribe with.
assert_not_contains "$projects" "<script" "the projects page loads no script"
assert_not_contains "$projects" "data-init" "the projects page opens no SSE connection"

# The rail row is what makes a project reachable from the board at all.
projects_rail=$(rail "$projects")
assert_contains "$board_rail_now" 'href="/projects"' "the board's rail has a Projects row"
assert_contains "$projects_rail" '<a href="/projects" class="active">' \
  "the Projects row is current on its own page"
board_rail_projects=$(rail "$(wcurl -sf "$WEB/")")
[ "$(rail_rows "$projects_rail")" = "$(rail_rows "$board_rail_projects")" ] \
  || fail "the board and projects rails offer different destinations"

# The project filter is one more param on the encoding /issues already has,
# so it composes with the others and survives a sort link.
pj_filtered=$(wcurl -sf "$WEB/issues?project=Ship+the+board")
assert_contains "$pj_filtered" "Project member issue" "?project= keeps the issue in that project"
assert_contains "$pj_filtered" '<option value="Ship the board" selected>' \
  "the project chooser reflects the URL"
assert_contains "$pj_filtered" 'href="/issues?project=Ship&#43;the&#43;board&amp;sort=-created"' \
  "a sort link keeps the project filter"
assert_not_contains "$(wcurl -sf "$WEB/issues?project=Ship+the+board&state=done")" \
  "Project member issue" "?project= composes with ?state= instead of replacing it"
assert_not_contains "$(wcurl -sf "$WEB/issues?project=Ship+the+board")" \
  "Table filter subject" "?project= drops issues in no project"

# A stale bookmark degrades to the flash strip, never a 500 — same contract as
# every other rejected param on this page.
bad_pj=$(wcurl -sf "$WEB/issues?project=nosuchproject") \
  || fail "an unknown project param returned an error status"
assert_contains "$bad_pj" 'class="flash"' "an unknown project is reported in the flash strip"
assert_contains "$bad_pj" "no project named" "the flash names the rejected project"
assert_contains "$bad_pj" '<table id="issues"' "an unknown project still serves the table"

# An issue says which project it belongs to, and the name is the way in.
pj_issue=$(wcurl -sf "$WEB/issue/$pj_key")
assert_contains "$pj_issue" '<a href="/issues?project=Ship&#43;the&#43;board">Ship the board</a>' \
  "the issue page links its project to that project's issues"
assert_contains "$(wcurl -sf "$WEB/issue/ENG-1")" \
  '<option value="" selected>No project</option>' \
  "an issue with no project says so in its select"

# --- ?raw: every view answers its URL with markdown (task-104) ------------
# The URL is the API: the same URL with ?raw is the view in markdown, built
# from the same view models the HTML renders. One-shot fetches; nothing here
# subscribes. Dedicated fixtures, because earlier sections moved the shared
# issues between states.
"$LIN" issue create -t "Raw todo subject" \
  -d "Raw description line one.

Raw description line three." >/dev/null
raw_todo=$("$LIN" issue list --search "Raw todo subject" | awk '{print $1}' | head -1)
[ -n "$raw_todo" ] || fail "the raw fixture issue was not found"
"$LIN" issue comment "$raw_todo" -b "raw seed comment" >/dev/null
"$LIN" issue create -t "Raw done subject" >/dev/null
raw_done=$("$LIN" issue list --search "Raw done subject" | awk '{print $1}' | head -1)
[ -n "$raw_done" ] || fail "the raw done fixture was not found"
"$LIN" issue update "$raw_done" --state done >/dev/null

raw_board=$(wcurl -sf "$WEB/?raw") || fail "board ?raw did not serve"
assert_contains "$raw_board" "# Board" "board raw opens with a markdown heading"
assert_contains "$raw_board" "## Todo" "board raw carries columns as headings"
assert_contains "$raw_board" "- [$raw_todo](/issue/$raw_todo) | Raw todo subject | todo |" \
  "board raw card lines have the stable shape"

# A filtered board's raw output honors the URL's filter.
raw_filtered=$(wcurl -sf "$WEB/?state=todo&raw") || fail "filtered board ?raw did not serve"
assert_contains "$raw_filtered" "Raw todo subject" "filtered board raw keeps the matching card"
assert_not_contains "$raw_filtered" "Raw done subject" "filtered board raw drops the non-matching card"

# Hidden lanes honor ?hide= exactly as the HTML columns do.
raw_hidden=$(wcurl -sf "$WEB/?hide=todo&raw") || fail "hidden-lane ?raw did not serve"
assert_not_contains "$raw_hidden" "## Todo" "a hidden lane gets no raw column"
assert_not_contains "$raw_hidden" "Raw todo subject" "a hidden lane's cards are not listed"

# The issues table as markdown: the HTML's columns, the URL's filter, and a
# row shape an agent can parse without reading the HTML first.
raw_issues=$(wcurl -sf "$WEB/issues?state=todo&raw") || fail "issues ?raw did not serve"
assert_contains "$raw_issues" "| ID | Title | State | Priority | Labels | Assignee | Created | Updated |" \
  "issues raw is a markdown table with the HTML's columns"
assert_contains "$raw_issues" "| [$raw_todo](/issue/$raw_todo) | Raw todo subject | todo |" \
  "issues raw rows have the stable shape"
assert_not_contains "$raw_issues" "Raw done subject" "issues raw honors the URL's state filter"
ct=$(wcurl -s -o /dev/null -w '%{content_type}' "$WEB/issues?state=todo&raw")
printf '%s' "$ct" | grep -q "text/markdown" || fail "raw answers as text/markdown, got: $ct"

# The issue page: the same spirit as lll issue view --raw — properties as a
# list, the full description (not the hover snippet), then comments.
raw_issue=$(wcurl -sf "$WEB/issue/$raw_todo?raw") || fail "issue ?raw did not serve"
assert_contains "$raw_issue" "# $raw_todo: Raw todo subject" "issue raw opens with a markdown H1"
assert_contains "$raw_issue" "- State: todo" "issue raw lists properties"
assert_contains "$raw_issue" "Raw description line three." \
  "issue raw carries the description as-is, not the snippet"
assert_contains "$raw_issue" "raw seed comment" "issue raw carries comments"

# Unknown issue is a 404 in raw mode too.
code=$(wcurl -s -o /dev/null -w '%{http_code}' "$WEB/issue/ENG-99?raw")
[ "$code" = "404" ] || fail "unknown issue in raw mode is a $code, not a 404"

# Projects, search, settings.
raw_projects=$(wcurl -sf "$WEB/projects?raw") || fail "projects ?raw did not serve"
assert_contains "$raw_projects" "Ship the board" "projects raw lists the project"
assert_contains "$raw_projects" "1 issue" "projects raw carries the issue count"
raw_search=$(wcurl -sf "$WEB/search?q=Raw+todo&raw") || fail "search ?raw did not serve"
assert_contains "$raw_search" "Raw todo subject" "search raw lists the hit"
assert_not_contains "$(wcurl -sf "$WEB/search?q=zzzznope&raw")" "Raw todo subject" \
  "a no-hit search raw lists nothing"
raw_settings=$(wcurl -sf "$WEB/settings?raw") || fail "settings ?raw did not serve"
# The display name rides a seed race (`lll up` may create ENG before the
# rename POST lands), so assert on the stable key, not the name.
assert_contains "$raw_settings" "(ENG)" "settings raw lists the team"
assert_contains "$raw_settings" "No Issues Here" "settings raw lists the members"

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

settings=$(wcurl -sf "$WEB/settings") || fail "/settings did not respond"
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
wcurl -sf -X POST "$WEB/settings/label" -d 'name=web-made' -d 'color=#4cb782' >/dev/null
"$LIN" label list | grep -q '^web-made	#4cb782' || fail "creating a label from /settings did not reach PocketBase"
LABEL_ID=$(row_id "$(wcurl -sf "$WEB/settings")" label web-made)
[ -n "$LABEL_ID" ] || fail "/settings did not render the label it just created"
wcurl -sf -X POST "$WEB/settings/label" -d "id=$LABEL_ID" -d 'name=web-renamed' -d 'color=#8d7ce6' >/dev/null
"$LIN" label list | grep -q '^web-renamed	#8d7ce6' || fail "renaming and recoloring a label from /settings did not persist"
wcurl -sf -X POST "$WEB/settings/label?del=1" -d "id=$LABEL_ID" >/dev/null
"$LIN" label list | grep -q 'web-renamed' && fail "deleting a label from /settings did not persist" || true

wcurl -sf -X POST "$WEB/settings/member" -d 'name=Web Member' -d 'email=web@example.com' >/dev/null
"$LIN" member list | grep -q '^Web Member	web@example.com' || fail "creating a member from /settings did not persist"
MEMBER_ID=$(row_id "$(wcurl -sf "$WEB/settings")" member "Web Member")
# The name is the settings-editable half; the email is the member's login
# identity (task-180) and the page says so when a row tries to move it.
wcurl -sf -X POST "$WEB/settings/member" -d "id=$MEMBER_ID" -d 'name=Web Member Renamed' -d 'email=web@example.com' >/dev/null
"$LIN" member list | grep -q '^Web Member Renamed	web@example.com' || fail "editing a member from /settings did not persist"
wcurl -sf -X POST "$WEB/settings/member" -d "id=$MEMBER_ID" -d 'name=Web Member Renamed' -d 'email=moved@example.com' | grep -q 'login identity' \
  || fail "moving a member's email from /settings should be refused with the reason"

wcurl -sf -X POST "$WEB/settings/project" -d 'name=Web Project' -d 'status=planned' >/dev/null
"$LIN" project list | grep -q '^Web Project	planned' || fail "creating a project from /settings did not persist"
PROJECT_ID=$(row_id "$(wcurl -sf "$WEB/settings")" project "Web Project")
wcurl -sf -X POST "$WEB/settings/project" -d "id=$PROJECT_ID" -d 'name=Web Project' -d 'status=started' >/dev/null
"$LIN" project list | grep -q '^Web Project	started' || fail "changing a project status from /settings did not persist"

# Validation speaks through the one flash strip, and writes nothing.
assert_contains "$(wcurl -sf -X POST "$WEB/settings/label" -d 'name=   ')" \
  'id="flash"' "an empty label name answers with the flash strip"
assert_contains "$(wcurl -sf -X POST "$WEB/settings/label" -d 'name=x' -d 'color=nope')" \
  'not a #rrggbb colour' "a malformed colour is refused"
assert_contains "$(wcurl -sf -X POST "$WEB/settings/project" -d "id=$PROJECT_ID" -d 'name=Web Project' -d 'status=bogus')" \
  "unknown project status" "an unknown project status is refused"
"$LIN" label list | grep -q '^x	' && fail "a refused label write still created a record" || true

# --- Access (task-204): superuser actions behind per-action re-auth ---------
# /settings is board-token-reachable, but minting an agent token and
# credentialing a member are superuser-power actions: each form carries the
# admin password, verified server-side per action, so the board cookie alone
# must refuse. `lll up` above booted without LLL_ADMIN_*, so the superuser is
# the printed default pair.
ADMIN_PASS="${LLL_ADMIN_PASSWORD:-admin-local-123}"

settings=$(wcurl -sf "$WEB/settings")
assert_contains "$settings" 'id="access-token-form"' "settings page carries the mint form"
assert_contains "$settings" 'id="access-credential-form"' "settings page carries the credential form"
assert_contains "$settings" 'id="access-token-result"' "settings page carries the token result placeholder"

# Refusals first: no admin password, then a wrong one. Neither may answer a token.
out=$(wcurl -sf -X POST "$WEB/settings/access/token" -d "member=$MEMBER_ID")
assert_contains "$out" "admin password is required" "minting without the admin password is refused"
assert_not_contains "$out" "access-token-value" "a refused mint shows no token"
out=$(wcurl -sf -X POST "$WEB/settings/access/token" -d "member=$MEMBER_ID" -d 'admin_password=not-the-password')
assert_contains "$out" "wrong admin password" "minting with a wrong admin password is refused"
assert_not_contains "$out" "access-token-value" "a wrong-password mint shows no token"

# The right password mints a working member token: shown once in the response
# patch, and honored by PocketBase's authenticated-only rules.
out=$(wcurl -sf -X POST "$WEB/settings/access/token" -d "member=$MEMBER_ID" -d "admin_password=$ADMIN_PASS")
assert_contains "$out" 'id="access-token-result"' "a mint answers with the token patch"
MINTED=$(printf '%s' "$out" | python3 -c '
import re, sys
m = re.search(r"access-token-value\">([^<]+)<", sys.stdin.read())
print(m.group(1) if m else "")
')
[ -n "$MINTED" ] || fail "the mint response carried no token"
curl -sf -H "Authorization: Bearer $MINTED" "$LLL_URL/api/collections/members/records?perPage=1" >/dev/null \
  || fail "the minted token is not honored by PocketBase"

# Credential a member. Without the admin password: refused, and the login it
# tried to set must not work.
out=$(wcurl -sf -X POST "$WEB/settings/access/member" -d "member=$MEMBER_ID" \
  -d 'email=cred@example.com' -d 'password=cred-pass-12345' -d 'password_confirm=cred-pass-12345')
assert_contains "$out" "admin password is required" "credentialing without the admin password is refused"
curl -s "$LLL_URL/api/collections/members/auth-with-password" -H 'Content-Type: application/json' \
  -d '{"identity":"cred@example.com","password":"cred-pass-12345"}' | grep -q '"token"' \
  && fail "a refused credential still changed the member's login" || true

# Mismatched passwords are refused before anything is verified or written.
out=$(wcurl -sf -X POST "$WEB/settings/access/member" -d "member=$MEMBER_ID" \
  -d 'password=cred-pass-12345' -d 'password_confirm=other' -d "admin_password=$ADMIN_PASS")
assert_contains "$out" "do not match" "mismatched passwords are refused"

# The right admin password credentials the member: the settings patch and the
# success flash ride back, and the member auth round-trip answers a token.
out=$(wcurl -sf -X POST "$WEB/settings/access/member" -d "member=$MEMBER_ID" \
  -d 'email=cred@example.com' -d 'password=cred-pass-12345' -d 'password_confirm=cred-pass-12345' \
  -d "admin_password=$ADMIN_PASS")
assert_contains "$out" 'id="settings"' "a credential patches the settings body back"
assert_contains "$out" 'flash-ok' "a credential says its success in the flash strip"
curl -sf "$LLL_URL/api/collections/members/auth-with-password" -H 'Content-Type: application/json' \
  -d '{"identity":"cred@example.com","password":"cred-pass-12345"}' | grep -q '"token"' \
  || fail "the credentialed member cannot log in"

# --- the team accent drives --accent and the favicon (task-83) ---
# Nothing stored means DESIGN.md's canonical orange, so theme.css's own
# tokens are left byte-identical: the injected rule is empty.
assert_contains "$(wcurl -sf "$WEB/")" '<style id="accent"></style>' \
  "an unset accent overrides nothing"
assert_contains "$(wcurl -sf "$WEB/")" 'id="favicon"' "the board carries a generated favicon"

wcurl -sf -X POST "$WEB/settings/team" -d 'name=Engineering' -d 'accent=#3ea0f0' >/dev/null
for page in "/" "/issue/ENG-1" "/settings"; do
  html=$(wcurl -sf "$WEB$page")
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
saved=$(wcurl -sf -X POST "$WEB/settings/team" -d 'name=Engineering' -d 'accent=#3ea0f0')
assert_contains "$saved" 'id="settings"' "a settings save patches the page body back"
assert_contains "$saved" 'id="accent"' "a settings save patches the head's accent rule"

# An unparseable stored accent falls back rather than emitting broken CSS.
# The field's max of 7 already keeps a whole CSS rule from fitting, so this
# writes the longest junk PocketBase will accept.
TEAM_ID=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/teams/records?filter=$(python3 -c "import urllib.parse;print(urllib.parse.quote(\"key='ENG'\"))")" | jq -r '.items[0].id')
curl -sf -H "$AUTH_HDR" -X PATCH "$LLL_URL/api/collections/teams/records/$TEAM_ID" \
  -H 'Content-Type: application/json' -d '{"accent":"};z{a:b"}' >/dev/null
assert_contains "$(wcurl -sf "$WEB/")" '<style id="accent"></style>' \
  "an unparseable stored accent falls back to the canonical orange"

# Choosing the canonical orange back stores nothing, so theme.css decides again.
wcurl -sf -X POST "$WEB/settings/team" -d 'name=Engineering' -d 'accent=#f0883e' >/dev/null
assert_contains "$(wcurl -sf "$WEB/")" '<style id="accent"></style>' \
  "picking the default orange clears the stored accent"

# --- favorites (task-84): a workspace-wide star, pinned into the rail ---
# The rail group, for asserting its contents.
favgroup() { # html
  printf '%s' "$1" | python3 -c '
import sys
html = sys.stdin.read()
try:
    print(html.split("id=\"rail-favorites\"")[1].split("</div>")[0])
except IndexError:
    pass
'
}

# The star is a set, not a toggle: the button posts the state it just moved
# to, so a repeat is a no-op instead of an unstar.
code=$(wcurl -s -o /dev/null -w '%{http_code}' -X POST "$WEB/favorite?key=ENG-1&on=true")
[ "$code" = 200 ] || fail "/favorite on returned $code, want 200"
board=$(wcurl -sf "$WEB/")
assert_contains "$(favgroup "$board")" 'href="/issue/ENG-1"' "starred issue is in the rail"
assert_not_contains "$(favgroup "$board")" "Star an issue to pin it here" \
  "a non-empty group drops the empty-state line"
# The issue page seeds the star's signal from the server.
assert_contains "$(wcurl -sf "$WEB/issue/ENG-1")" 'data-signals:fav="true"' \
  "issue page opens with the star lit"

wcurl -s -o /dev/null -X POST "$WEB/favorite?key=ENG-1&on=true"
count=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/favorites/records?perPage=200" | jq '.items | length')
[ "$count" = 1 ] || fail "starring twice made $count rows, want 1"

# The record shape is what makes per-user favorites (task-32) a migration
# rather than a redesign: the member relation already exists, and is empty
# because a star currently belongs to the workspace.
row=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/favorites/records?perPage=1" | jq -r '.items[0]')
printf '%s' "$row" | jq -e 'has("member")' >/dev/null || fail "favorite has no member field"
[ "$(printf '%s' "$row" | jq -r '.member')" = "" ] || fail "favorite is not workspace-wide"

# Unstarring removes the row, and is equally idempotent.
wcurl -s -o /dev/null -X POST "$WEB/favorite?key=ENG-1&on=false"
wcurl -s -o /dev/null -X POST "$WEB/favorite?key=ENG-1&on=false"
count=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/favorites/records?perPage=200" | jq '.items | length')
[ "$count" = 0 ] || fail "unstarring left $count rows, want 0"
assert_contains "$(favgroup "$(wcurl -sf "$WEB/")")" "Star an issue to pin it here" \
  "the group is empty again after unstarring"
assert_contains "$(wcurl -sf "$WEB/issue/ENG-1")" 'data-signals:fav="false"' \
  "issue page opens with the star dark"

out=$(wcurl -s -X POST "$WEB/favorite?key=ENG-99&on=true")
assert_contains "$out" "not found" "/favorite unknown issue message"

# The rail is outside every morph boundary, but the favorites group is its
# OWN boundary inside it, so a star patches the group alone on every open
# page — board scope included, which is why the broadcast scope is "*".
wcurl -sN "$WEB/events?page=board" >"$EVENTS_FILE" &
CURL_PID=$!
sleep 0.5
wcurl -s -o /dev/null -X POST "$WEB/favorite?key=ENG-1&on=true"
for _ in $(seq 1 50); do
  grep -q "rail-favorites" "$EVENTS_FILE" 2>/dev/null && break
  sleep 0.1
done
kill $CURL_PID 2>/dev/null || true
CURL_PID=""
events=$(cat "$EVENTS_FILE")
assert_contains "$events" 'data: elements <div id="rail-favorites"' \
  "a star patches the rail's favorites group into a board-scope client"
assert_contains "$events" 'href="/issue/ENG-1"' "the patched group carries the starred issue"
# Still a fragment, never the shell: the rail around the group is untouched.
assert_not_contains "$events" 'id="rail"' "the favorites patch carries no shell"

# Deleting the issue cascades the star away, and that reaches the rail too.
"$LIN" issue create -t "Starred then deleted" >/dev/null
STARRED_KEY=$("$LIN" issue list --json | jq -r '.items[] | select(.title=="Starred then deleted") | "ENG-" + (.number|tostring)')
wcurl -s -o /dev/null -X POST "$WEB/favorite?key=$STARRED_KEY&on=true"
assert_contains "$(favgroup "$(wcurl -sf "$WEB/")")" "Starred then deleted" "second star pinned"
"$LIN" issue delete "$STARRED_KEY" --force >/dev/null
assert_not_contains "$(favgroup "$(wcurl -sf "$WEB/")")" "Starred then deleted" \
  "deleting an issue cascades its star out of the rail"
# ...and it is really gone from PB, not merely filtered out of the render:
# cascadeDelete is what keeps the rail from accumulating dead links.
count=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/favorites/records?perPage=200" | jq '.items | length')
[ "$count" = 1 ] || fail "cascade left $count favorites, want 1 (ENG-1's)"
wcurl -s -o /dev/null -X POST "$WEB/favorite?key=ENG-1&on=false"


# --- task-94 half two: a saved view is a NAME plus a QUERY STRING -----------
# The rail group, for asserting its contents.
viewgroup() { # html
  printf '%s' "$1" | python3 -c '
import sys
html = sys.stdin.read()
try:
    print(html.split("id=\"rail-views\"")[1].split("</div>")[0])
except IndexError:
    pass
'
}

# The browser block above saved "Browser urgent", so the group already has a
# row: the group header and its shared-by-everyone note still render.
assert_contains "$(viewgroup "$(wcurl -sf "$WEB/")")" "Shared by everyone here" \
  "the views group labels itself shared, not personal"

# The flashing() wrapper answers every POST with a flash-strip fragment;
# success is the empty flash, errors carry the message (asserted below).
wcurl -s -o /dev/null -X POST "$WEB/views/save" \
  -d "name=Todo lane" --data-urlencode "query=?state=todo"

# Saving captures the query string, not a filter model: the record is two
# fields, and the rail navigates back to the URL.
vg=$(viewgroup "$(wcurl -sf "$WEB/")")
assert_contains "$vg" "Todo lane" "a saved view appears in the rail"
assert_contains "$vg" 'href="/?state=todo"' "the saved view navigates to its URL"

# Navigating to the view's URL reproduces the filter, in a fresh fetch —
# the same assertion a bookmark, a link, or an agent's curl makes. Fresh
# fixtures, because earlier suites moved the seeds between lanes.
"$LIN" issue create -t "Views fixture todo" >/dev/null
"$LIN" issue create -t "Views fixture other" >/dev/null
OTHER_KEY=$("$LIN" issue list --json | jq -r '.items[] | select(.title=="Views fixture other") | "ENG-" + (.number|tostring)')
"$LIN" issue update "$OTHER_KEY" --state in-progress >/dev/null
view_page=$(wcurl -sf "$WEB/?state=todo")
assert_contains "$(column "$view_page" todo)" "Views fixture todo" \
  "a saved view reproduces its filter (matching issue present)"
assert_not_contains "$(column "$view_page" todo)" "Views fixture other" \
  "a saved view reproduces its filter (other states stay out)"

# Views are workspace-wide until auth (task-32): member is empty on the row.
row=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/views/records?perPage=200" | jq -c '.items[0]')
[ "$(printf '%s' "$row" | jq -r '.member')" = "" ] || fail "a view is not workspace-wide"

# A duplicate name is a readable error in the flash strip, not a 500.
dup=$(wcurl -s -X POST "$WEB/views/save" -d "name=Todo lane" --data-urlencode "query=?state=todo")
assert_contains "$dup" "already exists" "a duplicate view name is said out loud"

# The SSE bridge patches the views group alone on every open board page.
wcurl -sN "$WEB/events?page=board" >"$EVENTS_FILE" &
CURL_PID=$!
sleep 0.5
wcurl -s -o /dev/null -X POST "$WEB/views/save" -d "name=Urgent lane" --data-urlencode "query=?prio=urgent"
for _ in $(seq 1 50); do
  grep -q "rail-views" "$EVENTS_FILE" 2>/dev/null && break
  sleep 0.1
done
kill $CURL_PID 2>/dev/null || true
CURL_PID=""
events=$(cat "$EVENTS_FILE")
assert_contains "$events" 'data: elements <div id="rail-views"' \
  "saving a view patches the rail's views group into a board-scope client"
assert_contains "$events" "Urgent lane" "the patched group carries the new view"
assert_not_contains "$events" 'id="rail"' "the views patch carries no shell"


# --- TASK-173: one server, many projects — the web scopes past issues -----
# OPS is the second project sharing this server. A chooser, a chip list or a
# settings row that offered its records would either filter this board to
# nothing or write a record no view can explain.
env LLL_TEAM=OPS "$LIN" team create -k OPS -n Operations >/dev/null 2>&1 || true
env LLL_TEAM=OPS "$LIN" label create -n foreign-label -c '#ff0000' >/dev/null
env LLL_TEAM=OPS "$LIN" project create -n "Foreign Project" >/dev/null

page=$(wcurl -sf "$WEB/issues")
assert_not_contains "$page" 'value="foreign-label"' "/issues label chooser is team-scoped"
assert_not_contains "$page" 'value="Foreign Project"' "/issues project chooser is team-scoped"
assert_not_contains "$(wcurl -sf "$WEB/settings")" "foreign-label" "/settings is team-scoped"
assert_not_contains "$(wcurl -sf "$WEB/projects")" "Foreign Project" "/projects is team-scoped"
assert_not_contains "$(wcurl -sf "$WEB/issue/ENG-1")" "foreign-label" "issue page label chips are team-scoped"

# A posted id from the other team is as unknown as a deleted one, whatever
# markup it came from.
FOREIGN_LABEL=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/labels/records?perPage=200" \
  | jq -r '.items[] | select(.name=="foreign-label") | .id')
FOREIGN_PROJECT=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/projects/records?perPage=200" \
  | jq -r '.items[] | select(.name=="Foreign Project") | .id')
assert_contains "$(wcurl -s -X POST --data-urlencode "key=ENG-1" \
  --data-urlencode "labels=$FOREIGN_LABEL" "$WEB/labels")" \
  "unknown label" "POST /labels refuses another team's label"
assert_contains "$(wcurl -s -X POST --data-urlencode "key=ENG-1" \
  --data-urlencode "project=$FOREIGN_PROJECT" "$WEB/project")" \
  "unknown project" "POST /project refuses another team's project"

# Labels and projects are required to name a team, so the settings writes
# have to supply one — and an update must not blank it.
wcurl -sf -X POST "$WEB/settings/label" -d 'name=scoped-label' -d 'color=#4cb782' >/dev/null
SCOPED=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/labels/records?perPage=200&expand=team" \
  | jq -r '.items[] | select(.name=="scoped-label") | .expand.team.key')
[ "$SCOPED" = "ENG" ] || fail "a web-created label landed on team '$SCOPED', want ENG"
SCOPED_ID=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/labels/records?perPage=200" \
  | jq -r '.items[] | select(.name=="scoped-label") | .id')
wcurl -sf -X POST "$WEB/settings/label" -d "id=$SCOPED_ID" -d 'name=scoped-label' -d 'color=#8d7ce6' >/dev/null
KEPT=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/labels/records/$SCOPED_ID?expand=team" | jq -r '.expand.team.key')
[ "$KEPT" = "ENG" ] || fail "a settings update blanked the label's team (got '$KEPT')"
wcurl -sf -X POST "$WEB/settings/label?del=1" -d "id=$SCOPED_ID" >/dev/null


# --- task-114: /create takes everything `lll issue create` does ------------
# The board's full create form is a modal over the board, and it posts to the
# SAME POST /create as the topbar's one-line composer. One path is what keeps
# the CLI and the web in agreement and avoids a second update racing the
# broadcast, so the assertions below are all against /create.
# The label row only renders when the workspace has labels, and /settings
# deleted the one it made above, so seed one first.
"$LIN" label create -n dialog-label -c '#8d7ce6' >/dev/null
board=$(wcurl -sf "$WEB/")
assert_contains "$board" 'id="ni-modal"' "board carries the create dialog"
assert_contains "$board" 'id="ni-form"' "the dialog is a form"
assert_contains "$board" 'name="description"' "the dialog takes a description"
assert_contains "$board" 'name="labels"' "the dialog takes labels"
assert_contains "$board" '>Unassigned</option>' "the dialog offers an assignee"
assert_contains "$board" '>No project</option>' "the dialog offers a project"
assert_contains "$board" 'id="new-issue"' "the one-line composer is still there"

DL_LABEL=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/labels/records?perPage=200" \
  | jq -r '.items[] | select(.name=="dialog-label") | .id')
DL_MEMBER=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/members/records?perPage=200" \
  | jq -r '.items[] | select(.name=="Web Member Renamed") | .id')
DL_PROJECT=$(curl -sf -H "$AUTH_HDR" "$LLL_URL/api/collections/projects/records?perPage=200" \
  | jq -r '.items[] | select(.name=="Web Project") | .id')
[ -n "$DL_LABEL" ] && [ -n "$DL_MEMBER" ] && [ -n "$DL_PROJECT" ] \
  || fail "seeding the create-dialog assertions"

out=$(wcurl -s -w '\n%{http_code}' -X POST \
  --data-urlencode "title=Created from the dialog" \
  --data-urlencode "description=A **real** description." \
  -d "state=in-progress" -d "priority=high" \
  -d "assignee=$DL_MEMBER" -d "project=$DL_PROJECT" -d "labels=$DL_LABEL" \
  "$WEB/create")
printf '%s' "$out" | tail -1 | grep -q 200 || fail "/create with every field should return 200"
assert_contains "$out" 'id="flash" class="flash" hidden' "a full create clears the flash"
# Only a success closes the dialog, and the server is what says so.
assert_contains "$out" 'signals {"ni_open": false' "a successful create closes the dialog"

DIALOG_KEY=$("$LIN" issue list --json \
  | jq -r '.items[] | select(.title=="Created from the dialog") | "ENG-" + (.number|tostring)')
[ -n "$DIALOG_KEY" ] || fail "the dialog's issue is not in lll issue list"
view=$("$LIN" issue view "$DIALOG_KEY")
assert_contains "$view" "A **real** description." "description reached PocketBase"
assert_contains "$view" "in-progress" "state reached PocketBase"
assert_contains "$view" "Priority:  high" "priority reached PocketBase"
assert_contains "$view" "Web Member" "assignee reached PocketBase"
assert_contains "$view" "Web Project" "project reached PocketBase"
assert_contains "$view" "dialog-label" "labels reached PocketBase"

# The fast path is the point of not making everyone pay for the full form:
# a title on its own is a complete request, and lands in todo like the CLI's.
out=$(wcurl -s -w '\n%{http_code}' -X POST -d "title=Title and nothing else" "$WEB/create")
printf '%s' "$out" | tail -1 | grep -q 200 || fail "/create with only a title should return 200"
FAST_KEY=$("$LIN" issue list --json \
  | jq -r '.items[] | select(.title=="Title and nothing else") | "ENG-" + (.number|tostring)')
assert_contains "$("$LIN" issue view "$FAST_KEY")" "todo" "a title-only create defaults to todo"

# A rejected create writes nothing AND leaves the dialog open, so a typed
# description survives the failure.
out=$(wcurl -s -X POST -d "title=Never written" -d "priority=bogus" "$WEB/create")
assert_contains "$out" "unknown priority &#39;bogus&#39;" "a bad priority answers through the flash"
assert_not_contains "$out" "ni_open" "a failed create does not close the dialog"
"$LIN" issue list | grep -q "Never written" && fail "a refused create still wrote a record" || true

# task-159: the handler is stateless — two creates back to back both land,
# each on its own closing the dialog (the same one write path, unchanged).
for n in 1 2; do
  out=$(wcurl -s -w '\n%{http_code}' -X POST -d "title=Create more curl $n" "$WEB/create")
  printf '%s' "$out" | tail -1 | grep -q 200 || fail "/create number $n of two back-to-back should return 200"
  assert_contains "$out" 'signals {"ni_open": false' "create number $n of two back-to-back closes the dialog"
done
# Assert against the PB records API — the write's source of truth — not a
# CLI rendering pass; poll briefly so a loaded runner cannot read stale.
back_to_back_written() { # n --- the record exists in PocketBase
  for _ in 1 2 3 4 5; do
    curl -sf -H "$AUTH_HDR" --get "$LLL_URL/api/collections/issues/records" \
      --data-urlencode "filter=title='Create more curl $1'" \
      --data-urlencode "perPage=1" | jq -e '.items | length == 1' >/dev/null && return 0
    sleep 0.5
  done
  return 1
}
back_to_back_written 1 || fail "the first back-to-back create wrote nothing"
back_to_back_written 2 || fail "the second back-to-back create wrote nothing"

echo "e2e_web: all assertions passed"
