#!/usr/bin/env bash
# e2e: ephemeral PocketBase + compiled lll CLI.
# Covers: create/list with ENG-1 style IDs, per-team numbering,
# forged duplicate (team, number) rejection, issue view (fields, unknown IDs),
# --json (jq roundtrips, expand.team), --state/--sort filters, glyph/priority
# display, write path (start/update/close/delete, git branch creation and
# ID inference from the branch), members (add/list), comments (add via config
# 'me', authorless, list, in issue view), --assignee (create/update/list
# filter, unknown member, expand in --json), projects and labels (create/list,
# project view with its issues, --label/--project on issue create/update and
# as list filters, --search, unknown names, expand in --json), realtime watch
# (lll watch create/update/delete lines and server-side filters, lll issue
# watch transitions and comments, --json NDJSON, reconnect across a PB
# restart), completions (bash/zsh/fish parse smoke), issue url/id/title
# (explicit + branch-inferred), board and -w opener (stubbed 'open' on PATH;
# real gh runs for issue pr are manual), --limit, --help output, --version,
# fix-naming error messages (PB down, unknown team, broken .lll.toml,
# unknown command), config layering and its origins (config --list, the
# upward walk stopping at the git root, lll attach), and the lll up web board
# (via e2e_web.sh).
set -euo pipefail
. "$(dirname "$0")/lib.sh"   # free_port, wait_ok, fail, assert_*, e2e_begin/end
e2e_begin

PORT=$(free_port 20000 39999)
URL="http://127.0.0.1:$PORT"
WEB_PORT=$(free_port 40000 59999)
PB_LOG="$DATA_DIR/pb.log"
E2E_LOGS="$PB_LOG"

lis build >/dev/null
LIN=target/.lisette/bin/lll

# PocketBase is embedded in lll (gopb), so there is no external binary to
# install. `lll up` needs a team and refuses to start without one; ENG is the
# one this suite uses anyway, and seed_team below fixes up its display name.
start_pb() {
  # USER is pinned: `lll up` seeds a member named after it on first boot
  # (task-31), and the member assertions below must not depend on who runs
  # this suite. HOME is pinned because that first boot WRITES 'me' to the home
  # config now (TASK-168), and a suite must not rewrite the developer's own.
  LLL_URL="$URL" LLL_TEAM=ENG USER=e2e HOME="$E2E_HOME" "$LIN" up --no-open \
    --pb-dir "$DATA_DIR/pb_data" --port "$WEB_PORT" </dev/null >>"$PB_LOG" 2>&1 &
  PB_PID=$!
  wait_ok "$URL/api/health" 150
}
start_pb || { echo "FAIL: lll up did not start" >&2; cat "$PB_LOG" >&2; exit 1; }
WATCH_PIDS=""
cleanup() {
  kill $WATCH_PIDS "$PB_PID" 2>/dev/null || true
  for pid in ${SPY_PIDS:-}; do kill "$pid" 2>/dev/null || true; done
  e2e_end
}
trap cleanup EXIT

# --- TASK-181: the suite rides a member token --------------------------------
# The rules refuse tokenless requests now, so bootstrap one before anything
# else talks to PocketBase: the superuser API creates e2e-agent with a known
# password, auth-with-password issues the member token, and every CLI verb
# below inherits it through the environment. The direct curls further down
# name the header explicitly, each with a reason.
E2E_TOKEN=$(pb_member_token "$URL" e2e-agent e2e-agent@lll.test e2e-agent-pass-123) \
  || fail "bootstrapping the e2e member token"
[ -n "$E2E_TOKEN" ] && [ "$E2E_TOKEN" != "null" ] || fail "pb_member_token returned no token"
export LLL_TOKEN="$E2E_TOKEN"
AUTH_HDR="Authorization: Bearer $E2E_TOKEN"

json_id() { python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'; }

# `lll up` created ENG with name "ENG"; create-or-fetch, then set the name the
# assertions expect. Idempotent so the mid-suite restart cannot double-create.
seed_team() { # key name -> prints the record id
  q=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(f"key=\x27{sys.argv[1]}\x27"))' "$1")
  id=$(curl -sf -H "$AUTH_HDR" "$URL/api/collections/teams/records?filter=$q" \
       | python3 -c 'import json,sys; it=json.load(sys.stdin)["items"]; print(it[0]["id"] if it else "")')
  if [ -z "$id" ]; then
    # `lll up` seeds the configured team itself, concurrently. Losing that race
    # means a 400 on the unique key, which curl -sf swallows into an empty body
    # and json_id then chokes on. Whoever won, look it up again.
    id=$(curl -sf -X POST -H "$AUTH_HDR" "$URL/api/collections/teams/records" \
      -H 'Content-Type: application/json' -d "{\"key\":\"$1\",\"name\":\"$2\"}" \
      | python3 -c 'import json,sys
try: print(json.load(sys.stdin)["id"])
except Exception: print("")')
    for _ in 1 2 3 4 5; do
      [ -n "$id" ] && break
      sleep 0.2
      id=$(curl -sf -H "$AUTH_HDR" "$URL/api/collections/teams/records?filter=$q" \
           | python3 -c 'import json,sys; it=json.load(sys.stdin)["items"]; print(it[0]["id"] if it else "")')
    done
    [ -n "$id" ] || fail "seeding team $1: neither create nor lookup produced an id"
  fi
  # The rename must actually stick before the suite moves on, on EVERY path:
  # `lll up` names a fresh team after its key, so losing the create race above
  # used to leave the boot's "ENG" in place — half a suite later
  # 'team list has name' failed (seen on a loaded runner, twice in a row).
  named=""
  for _ in 1 2 3 4 5; do
    curl -sf -X PATCH -H "$AUTH_HDR" "$URL/api/collections/teams/records/$id" \
      -H 'Content-Type: application/json' -d "{\"name\":\"$2\"}" >/dev/null
    named=$(curl -sf -H "$AUTH_HDR" "$URL/api/collections/teams/records/$id" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')
    [ "$named" = "$2" ] && break
    sleep 0.2
  done
  [ "$named" = "$2" ] || fail "seeding team $1: rename to '$2' never stuck (saw '$named')"
  printf '%s' "$id"
}
ENG_ID=$(seed_team ENG Engineering)
OPS_ID=$(seed_team OPS Operations)
[ -n "$ENG_ID" ] && [ -n "$OPS_ID" ] || fail "seeding teams"

# --- TASK-181: unauthenticated requests are refused, per verb ---------------
# PocketBase applies rules as FILTERS, so the refusal codes are deliberate
# and not all 401 (verified in v0.40.1 apis/record_crud.go): a guest listing
# gets 200 with zero items — no existence leak; view/update/delete cannot
# resolve the record, so 404; create fails the rule check, so 400. Whatever
# shape the refusal takes, the property under test is: no data, no mutation.
anon=$(curl -s "$URL/api/collections/issues/records")
[ "$(printf '%s' "$anon" | jq '.items | length')" = 0 ] \
  || fail "an unauthenticated issue list leaked records: $anon"
code=$(curl -s -o /dev/null -w '%{http_code}' "$URL/api/collections/issues/records?perPage=1")
[ "$code" = 200 ] || fail "unauthenticated list: expected 200-empty, got $code"
code=$(curl -s -o /dev/null -w '%{http_code}' "$URL/api/collections/issues/records/$ENG_ID")
[ "$code" = 404 ] || fail "unauthenticated view: expected 404, got $code"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  "$URL/api/collections/issues/records" -H 'Content-Type: application/json' \
  -d "{\"team\":\"$ENG_ID\",\"title\":\"anonymous create\",\"state\":\"todo\"}")
[ "$code" = 400 ] || fail "unauthenticated create: expected 400, got $code"
code=$(curl -s -o /dev/null -w '%{http_code}' -X PATCH \
  "$URL/api/collections/issues/records/$ENG_ID" -H 'Content-Type: application/json' \
  -d '{"title":"anonymous patch"}')
[ "$code" = 404 ] || fail "unauthenticated update: expected 404, got $code"
code=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE \
  "$URL/api/collections/issues/records/$ENG_ID")
[ "$code" = 404 ] || fail "unauthenticated delete: expected 404, got $code"

# The same sweep across every collection: a guest list comes back empty and
# a guest create is refused. The browser-shaped version of this request —
# what a page or script would fire at PocketBase directly — is the same
# tokenless call, so it is covered by exactly this assertion.
for coll in teams members projects labels issues comments docs views favorites claims; do
  anon=$(curl -s "$URL/api/collections/$coll/records")
  [ "$(printf '%s' "$anon" | jq '.items | length')" = 0 ] \
    || fail "an unauthenticated list of $coll leaked records: $anon"
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
    "$URL/api/collections/$coll/records" -H 'Content-Type: application/json' -d '{}')
  [ "$code" = 400 ] || fail "unauthenticated create on $coll: expected 400, got $code"
done

# The token flips every one of those answers: a member list is 200 with
# whatever is there.
code=$(curl -s -o /dev/null -w '%{http_code}' -H "$AUTH_HDR" \
  "$URL/api/collections/issues/records?perPage=1")
[ "$code" = 200 ] || fail "authenticated member list: expected 200, got $code"

# --- create + list shows ENG-1 style identifier ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "First engineering issue")
assert_contains "$out" "Created ENG-1: First engineering issue" "create output"

out=$(LLL_URL=$URL "$LIN" issue list)
assert_contains "$out" "ENG-1" "list shows ENG-1"
assert_contains "$out" "First engineering issue" "list shows title"
assert_contains "$out" "todo" "list shows state"

# --- per-team numbering: interleaved creates yield ENG-1, OPS-1, ENG-2 ---
out=$(LLL_URL=$URL LLL_TEAM=OPS "$LIN" issue create -t "First ops issue")
assert_contains "$out" "Created OPS-1" "ops numbering starts at 1"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "Second engineering issue")
assert_contains "$out" "Created ENG-2" "eng numbering continues at 2"

out=$(LLL_URL=$URL "$LIN" issue list)
assert_contains "$out" "ENG-1" "list has ENG-1"
assert_contains "$out" "ENG-2" "list has ENG-2"
assert_contains "$out" "OPS-1" "list has OPS-1"
assert_not_contains "$out" "OPS-2" "no OPS-2"

# --- forged duplicate (team, number) rejected by unique index ---
status=$(curl -s -o "$DATA_DIR/forged.json" -w '%{http_code}' -H "$AUTH_HDR" \
  -X POST "$URL/api/collections/issues/records" \
  -H 'Content-Type: application/json' \
  -d "{\"team\":\"$ENG_ID\",\"number\":1,\"title\":\"forged\",\"state\":\"todo\"}")
[ "$status" = "400" ] || fail "forged duplicate: expected HTTP 400, got $status: $(cat "$DATA_DIR/forged.json")"

# --- team commands ---
out=$(LLL_URL=$URL "$LIN" team list)
assert_contains "$out" "ENG" "team list has ENG"
assert_contains "$out" "Engineering" "team list has name"
assert_contains "$out" "OPS" "team list has OPS"

out=$(LLL_URL=$URL "$LIN" team create -k QA -n "Quality")
assert_contains "$out" "Created team QA: Quality" "team create output"
out=$(LLL_URL=$URL "$LIN" team list)
assert_contains "$out" "QA" "team list has created QA"

out=$(LLL_URL=$URL "$LIN" team view ENG)
assert_contains "$out" "Key:    ENG" "team view key"
assert_contains "$out" "Name:   Engineering" "team view name"
assert_contains "$out" "Issues: 2" "team view issue count"

# --- LLL_TEAM scopes issue list by default ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list)
assert_contains "$out" "ENG-1" "scoped list has ENG-1"
assert_not_contains "$out" "OPS-1" "scoped list hides OPS-1"

# --- config init ---
LLL_ABS="$PWD/$LIN"
WORK="$DATA_DIR/work"
FAKEHOME="$DATA_DIR/home"
mkdir -p "$WORK" "$FAKEHOME/.config/lll"

out=$(cd "$WORK" && "$LLL_ABS" config init)
assert_contains "$out" "Wrote .lll.toml" "config init output"
assert_contains "$(cat "$WORK/.lll.toml")" "url = " "template mentions url"
assert_contains "$(cat "$WORK/.lll.toml")" "team = " "template mentions team"
if (cd "$WORK" && "$LLL_ABS" config init >/dev/null 2>&1); then
  fail "config init overwrote an existing .lll.toml"
fi
rm "$WORK/.lll.toml"

# --- config set me (task-31): creates, then replaces rather than appends ---
# LLL_URL pinned: without it this reaches whatever owns the default port 8090,
# which on a machine running a dev board is somebody else's database.
# It writes the HOME config, not the repo file (TASK-168): 'me' is a fact
# about a person, and the repo's .lll.toml is committed.
SET_HOME="$DATA_DIR/sethome"
mkdir -p "$SET_HOME"
HOME_TOML="$SET_HOME/.config/lll/lll.toml"
out=$(cd "$WORK" && HOME="$SET_HOME" LLL_URL=$URL "$LLL_ABS" config set me alice)
assert_contains "$out" 'me = "alice"' "config set me output"
assert_contains "$out" "$HOME_TOML" "config set me names the file it wrote"
# With PocketBase reachable, config set me SEEDS the member (task-63) rather
# than printing the add-it-yourself hint. This assertion used to pass only
# because LLL_URL was unpinned and the command could not reach a server.
assert_contains "$out" "created member alice" "config set me seeds the member"
assert_contains "$(cat "$HOME_TOML")" 'me = "alice"' "config set me wrote the key"
[ ! -e "$WORK/.lll.toml" ] || fail "config set me wrote the repo file: $(cat "$WORK/.lll.toml")"
(cd "$WORK" && HOME="$SET_HOME" LLL_URL=$URL "$LLL_ABS" config set me bob >/dev/null)
[ "$(grep -c '^me = ' "$HOME_TOML")" = 1 ] \
  || fail "config set me appended a duplicate key: $(cat "$HOME_TOML")"
assert_contains "$(cat "$HOME_TOML")" 'me = "bob"' "config set me replaced the value"
# A duplicate key would make the file unparseable; prove it still loads.
out=$(cd "$WORK" && HOME="$SET_HOME" LLL_URL=$URL LLL_TEAM=ENG "$LLL_ABS" issue list)
assert_contains "$out" "ENG-1" "config still parses after two config set me"
out=$(cd "$WORK" && "$LLL_ABS" config set url http://x 2>&1) && fail "config set accepted a key other than me"
assert_contains "$out" "only 'me' is settable" "config set rejects other keys"

# --- config --list: every value and the file it came from (TASK-168) ---
# The failure this answers is silent, so it has to name origins, not values.
printf 'url = "%s"\nme = "homer"\n' "$URL" > "$HOME_TOML"
printf 'team = "ENG"\n' > "$WORK/.lll.toml"
out=$(cd "$WORK" && env -u LLL_URL -u LLL_TEAM -u LLL_ME -u LLL_SORT -u LLL_WEB_URL \
  HOME="$SET_HOME" "$LLL_ABS" config --list)
assert_contains "$out" "file:$HOME_TOML	url=$URL" "--list attributes url to the home file"
assert_contains "$out" "file:.lll.toml	team=ENG" "--list attributes team to the repo file"
assert_contains "$out" "file:$HOME_TOML	me=homer" "--list attributes me to the home file"
assert_contains "$out" "default	web_url=http://127.0.0.1:8100" "--list marks an unset key with a default"
assert_contains "$out" "unset	sort=" "--list marks a key nothing set"
out=$(cd "$WORK" && LLL_TEAM=FROMENV HOME="$SET_HOME" "$LLL_ABS" config --list)
assert_contains "$out" "env:LLL_TEAM	team=FROMENV" "--list attributes an override to the env var"

# --- layering: the repo file supplies team, the home file keeps url and me ---
# First-wins made a committed repo file impossible; this is what replaced it.
out=$(cd "$WORK" && env -u LLL_URL -u LLL_TEAM HOME="$SET_HOME" "$LLL_ABS" issue list)
assert_contains "$out" "ENG-1" "repo team layered over the home url"
assert_not_contains "$out" "OPS-1" "repo team scopes the list"
out=$(cd "$WORK" && env -u LLL_URL -u LLL_TEAM HOME="$SET_HOME" "$LLL_ABS" config --list)
assert_contains "$out" "me=homer" "the home file's me survives a repo file"

# --- discovery walks up to the repo root, not just the cwd (TASK-168) ---
# Running from a subdirectory used to fall through to the home config and use
# the wrong team, silently. The walk stops AT the git root: a .lll.toml above
# it must stay out of reach, or one stray file captures every repo beneath it.
WALK="$DATA_DIR/walk"
mkdir -p "$WALK/repo/deep/deeper"
printf 'team = "STRAY"\n' > "$WALK/.lll.toml"
git -C "$WALK/repo" init -q
printf 'team = "ENG"\n' > "$WALK/repo/.lll.toml"
out=$(cd "$WALK/repo/deep/deeper" && env -u LLL_TEAM HOME="$SET_HOME" "$LLL_ABS" issue list)
assert_contains "$out" "ENG-1" "a subdirectory finds the repo root's team"
rm "$WALK/repo/.lll.toml"
out=$(cd "$WALK/repo/deep/deeper" && env -u LLL_TEAM HOME="$SET_HOME" "$LLL_ABS" config --list)
assert_contains "$out" "unset	team=" "the walk stops at the git root"
assert_not_contains "$out" "STRAY" "a .lll.toml above the repo root is never read"

# --- attach: one command, one line, the team created (TASK-168) ---
ATTACH="$DATA_DIR/attach/lllattachdemo"
mkdir -p "$ATTACH/sub"
git -C "$ATTACH" init -q
out=$(cd "$ATTACH/sub" && LLL_URL=$URL HOME="$SET_HOME" "$LLL_ABS" attach)
# The repo root, not the subdirectory it was run from. Matched on the tail
# because git reports the path with symlinks resolved and $DATA_DIR is not.
assert_contains "$out" "lllattachdemo/.lll.toml" "attach names the file at the repo root"
assert_contains "$out" "created team LLLAT" "attach created the derived team"
[ "$(cat "$ATTACH/.lll.toml")" = 'team = "LLLAT"' ] \
  || fail "attach wrote more than the team: $(cat "$ATTACH/.lll.toml")"
# Idempotent, and -k overrides the derived key.
out=$(cd "$ATTACH" && LLL_URL=$URL HOME="$SET_HOME" "$LLL_ABS" attach -k ENG)
assert_contains "$out" "team ENG already exists" "attach reuses an existing team"
[ "$(cat "$ATTACH/.lll.toml")" = 'team = "ENG"' ] \
  || fail "attach -k did not replace the key: $(cat "$ATTACH/.lll.toml")"
# And that one committed line is the whole attachment: no url, no me needed.
out=$(cd "$ATTACH/sub" && env -u LLL_TEAM LLL_URL=$URL HOME="$SET_HOME" "$LLL_ABS" issue list)
assert_contains "$out" "ENG-1" "an attached repo is scoped from its committed file"
out=$(cd "$DATA_DIR" && LLL_URL=$URL HOME="$SET_HOME" "$LLL_ABS" attach 2>&1) \
  && fail "attach outside a git repository should exit non-zero"
assert_contains "$out" "not inside a git repository" "attach outside a repo names why"

rm -f "$WORK/.lll.toml"

# --- config precedence: env > ./.lll.toml > ~/.config/lll/lll.toml ---
printf 'url = "%s"\nteam = "OPS"\n' "$URL" > "$FAKEHOME/.config/lll/lll.toml"

# home file alone supplies url + team
out=$(cd "$WORK" && env -u LLL_URL -u LLL_TEAM HOME="$FAKEHOME" "$LLL_ABS" issue list)
assert_contains "$out" "OPS-1" "home config scopes to OPS"
assert_not_contains "$out" "ENG-1" "home config hides ENG"

# project file beats home file
printf 'url = "%s"\nteam = "ENG"\n' "$URL" > "$WORK/.lll.toml"
out=$(cd "$WORK" && env -u LLL_URL -u LLL_TEAM HOME="$FAKEHOME" "$LLL_ABS" issue list)
assert_contains "$out" "ENG-1" "project config scopes to ENG"
assert_not_contains "$out" "OPS-1" "project config beats home config"

# env beats project file
out=$(cd "$WORK" && env -u LLL_URL LLL_TEAM=OPS HOME="$FAKEHOME" "$LLL_ABS" issue list)
assert_contains "$out" "OPS-1" "env scopes to OPS"
assert_not_contains "$out" "ENG-1" "env beats project config"

# --- issue view: full fields, glyphs, priority, relative dates, description ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "Fix login flow" --priority 2)
assert_contains "$out" "Created ENG-3: Fix login flow" "create with --priority"

ENG3_ID=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --json | \
  jq -r '.items[] | select(.title=="Fix login flow") | .id')
[ -n "$ENG3_ID" ] || fail "resolving ENG-3 record id from --json"
curl -sf -X PATCH "$URL/api/collections/issues/records/$ENG3_ID" -H "$AUTH_HDR" \
  -H 'Content-Type: application/json' \
  -d '{"description":"First paragraph of the description.\n\nSecond paragraph."}' >/dev/null

out=$(LLL_URL=$URL "$LIN" issue view ENG-3)
assert_contains "$out" "ENG-3 Fix login flow" "view header"
assert_contains "$out" "State:" "view state label"
assert_contains "$out" "○ todo" "view state glyph"
assert_contains "$out" "Priority:  high" "view priority"
assert_contains "$out" "Created:   just now" "view relative created"
assert_contains "$out" "Updated:   just now" "view relative updated"
assert_contains "$out" "First paragraph of the description." "view description"
assert_contains "$out" "Second paragraph." "view description second paragraph"

# --- issue view: unknown IDs exit nonzero and name the fix ---
set +e
out=$(LLL_URL=$URL "$LIN" issue view OPS-99 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "view OPS-99: expected nonzero exit"
assert_contains "$out" "issue OPS-99 not found" "view unknown number message"
assert_contains "$out" "lll issue list" "view unknown ID names the fix"

set +e
out=$(LLL_URL=$URL "$LIN" issue view ZZZ-1 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "view ZZZ-1: expected nonzero exit"
assert_contains "$out" "issue ZZZ-1 not found" "view unknown team message"

set +e
out=$(LLL_URL=$URL "$LIN" issue view not-an-id 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "view not-an-id: expected nonzero exit"
assert_contains "$out" "not an issue ID" "view malformed ID message"

# --- --json parses with jq and resolves expand.team ---
title=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --json | jq -r '.items[0].title')
[ -n "$title" ] && [ "$title" != "null" ] || fail "list --json: .items[0].title empty"
key=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --json | jq -r '.items[0].expand.team.key')
[ "$key" = "ENG" ] || fail "list --json: expected expand.team.key ENG, got '$key'"

vtitle=$(LLL_URL=$URL "$LIN" issue view ENG-3 --json | jq -r '.title')
[ "$vtitle" = "Fix login flow" ] || fail "view --json: expected title roundtrip, got '$vtitle'"
vkey=$(LLL_URL=$URL "$LIN" issue view ENG-3 --json | jq -r '.expand.team.key')
[ "$vkey" = "ENG" ] || fail "view --json: expected expand.team.key ENG, got '$vkey'"

# --- --state filters; invalid state rejected ---
curl -sf -X PATCH "$URL/api/collections/issues/records/$ENG3_ID" -H "$AUTH_HDR" \
  -H 'Content-Type: application/json' -d '{"state":"in-review"}' >/dev/null

out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --state in-review)
assert_contains "$out" "ENG-3" "state filter shows in-review issue"
assert_not_contains "$out" "ENG-1" "state filter hides todo issues"

set +e
out=$(LLL_URL=$URL "$LIN" issue list --state bogus 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "list --state bogus: expected nonzero exit"
assert_contains "$out" "unknown state 'bogus'" "invalid state message"

# --- --sort orders by priority; LLL_SORT sets the default ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "Server on fire" --priority 1)
assert_contains "$out" "Created ENG-4" "urgent issue created"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "Tidy readme" --priority 4)
assert_contains "$out" "Created ENG-5" "low issue created"

out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --sort -priority)
assert_contains "$(printf '%s\n' "$out" | head -1)" "ENG-5" "sort -priority puts low (4) first"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --sort priority)
assert_contains "$(printf '%s\n' "$out" | tail -1)" "ENG-5" "sort priority puts low (4) last"

out=$(LLL_URL=$URL LLL_TEAM=ENG LLL_SORT=-priority "$LIN" issue list)
assert_contains "$(printf '%s\n' "$out" | head -1)" "ENG-5" "LLL_SORT is the default sort"

set +e
out=$(LLL_URL=$URL "$LIN" issue list --sort title 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "list --sort title: expected nonzero exit"
assert_contains "$out" "unknown sort field 'title'" "invalid sort message"

# --- list output: glyphs and priority markers, aligned columns ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list)
assert_contains "$out" "○ todo" "list shows todo glyph"
assert_contains "$out" "◉ in-review" "list shows in-review glyph"
assert_contains "$out" "!!!" "list shows urgent marker"
assert_contains "$out" "·" "list shows low marker"
assert_contains "$out" "just now" "list shows relative dates"

# --- write path round-trip: create -> start -> update -> close ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "Roundtrip issue" --priority 3)
assert_contains "$out" "Created ENG-6: Roundtrip issue" "roundtrip create"

REPO="$DATA_DIR/repo"
git init -q -b main "$REPO"
git -C "$REPO" -c user.name=e2e -c user.email=e2e@example.com \
  commit -q --allow-empty -m init

out=$(cd "$REPO" && LLL_URL=$URL "$LLL_ABS" issue start ENG-6)
assert_contains "$out" "Started ENG-6" "start output"
assert_contains "$out" "Branch: eng-6-roundtrip-issue" "start prints branch name"
assert_contains "$out" "Created and switched to branch 'eng-6-roundtrip-issue'" "start creates branch"
branch=$(git -C "$REPO" branch --show-current)
[ "$branch" = "eng-6-roundtrip-issue" ] || fail "start: expected branch eng-6-roundtrip-issue, on '$branch'"

# starting again — ID inferred from the branch — switches instead of failing
out=$(cd "$REPO" && LLL_URL=$URL "$LLL_ABS" issue start)
assert_contains "$out" "Started ENG-6" "inferred start output"
assert_contains "$out" "Switched to existing branch 'eng-6-roundtrip-issue'" "start reuses branch"

# --- ID inference from the branch: view / update / close with no arg ---
out=$(cd "$REPO" && LLL_URL=$URL "$LLL_ABS" issue view)
assert_contains "$out" "ENG-6 Roundtrip issue" "inferred view header"
assert_contains "$out" "◐ in-progress" "start set in-progress"

out=$(cd "$REPO" && LLL_URL=$URL "$LLL_ABS" issue update --priority 1 --title "Roundtrip issue v2")
assert_contains "$out" "Updated ENG-6" "inferred update output"
out=$(LLL_URL=$URL "$LIN" issue view ENG-6)
assert_contains "$out" "ENG-6 Roundtrip issue v2" "update changed title"
assert_contains "$out" "Priority:  urgent" "update changed priority"

out=$(cd "$REPO" && LLL_URL=$URL "$LLL_ABS" issue close)
assert_contains "$out" "Closed ENG-6" "inferred close output"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --state done)
assert_contains "$out" "ENG-6" "closed issue listed as done"
assert_contains "$out" "● done" "list shows done glyph"

# inference fails helpfully off a conventional branch
git -C "$REPO" switch -q -c not-an-issue-branch
set +e
out=$(cd "$REPO" && LLL_URL=$URL "$LLL_ABS" issue view 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "view on non-issue branch: expected nonzero exit"
assert_contains "$out" "doesn't look like eng-123-" "inference failure names the convention"

# --- update validation: no flags, bad state ---
set +e
out=$(LLL_URL=$URL "$LIN" issue update ENG-6 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "update with no flags: expected nonzero exit"
assert_contains "$out" "nothing to update" "update requires a flag"

set +e
out=$(LLL_URL=$URL "$LIN" issue update ENG-6 --state bogus 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "update --state bogus: expected nonzero exit"
assert_contains "$out" "unknown state 'bogus'" "update validates state"

# --- unknown IDs: update / close exit nonzero ---
set +e
out=$(LLL_URL=$URL "$LIN" issue update ENG-99 --priority 2 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "update ENG-99: expected nonzero exit"
assert_contains "$out" "issue ENG-99 not found" "update unknown ID message"

set +e
out=$(LLL_URL=$URL "$LIN" issue close ZZZ-9 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "close ZZZ-9: expected nonzero exit"
assert_contains "$out" "issue ZZZ-9 not found" "close unknown ID message"

# --- delete: declined without --force, explicit ID required, --force deletes ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "Delete me")
assert_contains "$out" "Created ENG-7" "delete target created"

out=$(printf 'n\n' | LLL_URL=$URL "$LIN" issue delete ENG-7)
assert_contains "$out" "delete ENG-7? [y/N]" "delete prompts"
assert_contains "$out" "Aborted." "delete declined"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list)
assert_contains "$out" "ENG-7" "declined delete keeps the issue"

set +e
out=$(LLL_URL=$URL "$LIN" issue delete 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "delete without ID: expected nonzero exit"
assert_contains "$out" "lll issue delete KEY-123" "delete requires explicit ID"

out=$(LLL_URL=$URL "$LIN" issue delete ENG-7 --force)
assert_contains "$out" "Deleted ENG-7" "forced delete output"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list)
assert_not_contains "$out" "ENG-7" "forced delete removed the issue"

# --- members: add + list ---
out=$(LLL_URL=$URL "$LIN" member add -n bryan -e bryan@example.com)
assert_contains "$out" "Added member bryan" "member add output"
# NOT alice: `config set me alice` above now seeds that member for real, so
# adding it again hits the unique index. This case is about the no-email path.
out=$(LLL_URL=$URL "$LIN" member add -n carol)
assert_contains "$out" "Added member carol" "member add without email"
out=$(LLL_URL=$URL "$LIN" member list)
assert_contains "$out" "bryan" "member list has bryan"
assert_contains "$out" "bryan@example.com" "member list shows email"
assert_contains "$out" "carol" "member list has carol"
assert_contains "$out" "alice" "member list has the member config set me seeded"

# --- task-180: members is an auth collection -------------------------------
# carol was created without an email, so the CLI synthesized the reserved
# identity; the record carries a random password nobody knows, which is what
# makes the record creatable without making it log-in-able.
carol_email=$(curl -sf -H "$AUTH_HDR" "$URL/api/collections/members/records?perPage=200" | jq -r '.items[] | select(.name=="carol") | .email')
assert_contains "$carol_email" "@members.invalid" \
  "an email-less member got the reserved synthetic identity"

# PocketBase's own auth-with-password issues tokens for members that HAVE a
# real password. bryan was created with -e; give him one via the admin API
# and walk the full auth round trip.
# Setting a member's password is a superuser operation: PocketBase refuses a
# password change without the old password unless the caller is an admin.
ADMIN=$(curl -s -X POST "$URL/api/collections/_superusers/auth-with-password" \
  -H 'Content-Type: application/json' \
  -d '{"identity":"admin@local.dev","password":"admin-local-123"}' | jq -r '.token')
[ -n "$ADMIN" ] && [ "$ADMIN" != "null" ] || fail "admin auth-with-password returned no token"
BRYAN_ID=$(curl -sf -H "$AUTH_HDR" "$URL/api/collections/members/records?perPage=200" | jq -r '.items[] | select(.name=="bryan") | .id')
curl -sf -X PATCH "$URL/api/collections/members/records/$BRYAN_ID" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $ADMIN" \
  -d '{"password":"bryan-pass-123","passwordConfirm":"bryan-pass-123"}' >/dev/null \
  || fail "setting bryan's password via the admin API"
AUTH=$(set +e; curl -s -X POST "$URL/api/collections/members/auth-with-password" \
  -H 'Content-Type: application/json' \
  -d '{"identity":"bryan@example.com","password":"bryan-pass-123"}'; set -e)
assert_contains "$AUTH" '"token"' "auth-with-password returns a token"
TOKEN=$(printf '%s' "$AUTH" | jq -r '.token')
[ -n "$TOKEN" ] && [ "$TOKEN" != "null" ] || fail "auth token is empty"
# The token authenticates a GET the new rules now require it for.
code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" \
  "$URL/api/collections/issues/records?perPage=1")
[ "$code" = 200 ] || fail "authenticated GET with the member token returned $code"
# The assignee/author paths are asserted unchanged further below, where the
# issues they point at exist (ENG-7: 'assignee relation' + comment author).

# --- --assignee on create; assignee in list and view ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "Assigned issue" --assignee bryan)
assert_contains "$out" "Created ENG-7: Assigned issue" "assigned create output"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list)
assert_contains "$out" "bryan" "list shows assignee column"
out=$(LLL_URL=$URL "$LIN" issue view ENG-7)
assert_contains "$out" "Assignee:  bryan" "view shows assignee"
out=$(LLL_URL=$URL "$LIN" issue view ENG-6)
assert_contains "$out" "Assignee:  none" "view shows unassigned as none"

# --- --assignee filter on list ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --assignee bryan)
assert_contains "$out" "ENG-7" "assignee filter shows assigned issue"
assert_not_contains "$out" "ENG-6" "assignee filter hides unassigned issues"

# --- --assignee on update ---
out=$(LLL_URL=$URL "$LIN" issue update ENG-6 --assignee alice)
assert_contains "$out" "Updated ENG-6" "update --assignee output"
out=$(LLL_URL=$URL "$LIN" issue view ENG-6)
assert_contains "$out" "Assignee:  alice" "update set assignee"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --assignee alice)
assert_contains "$out" "ENG-6" "assignee filter finds updated issue"
assert_not_contains "$out" "ENG-7" "assignee filter scoped to alice"

# --- unknown member errors and names the fix ---
set +e
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "Nope" --assignee nobody 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "create --assignee nobody: expected nonzero exit"
assert_contains "$out" "no member named 'nobody'" "unknown member message"
assert_contains "$out" "lll member list" "unknown member names the fix"

set +e
out=$(LLL_URL=$URL "$LIN" issue update ENG-6 --assignee nobody 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "update --assignee nobody: expected nonzero exit"
assert_contains "$out" "no member named 'nobody'" "update unknown member message"

set +e
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --assignee nobody 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "list --assignee nobody: expected nonzero exit"
assert_contains "$out" "no member named 'nobody'" "list unknown member message"

# --- --json resolves expand.assignee ---
aname=$(LLL_URL=$URL "$LIN" issue view ENG-7 --json | jq -r '.expand.assignee.name')
[ "$aname" = "bryan" ] || fail "view --json: expected expand.assignee.name bryan, got '$aname'"
aname=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --assignee bryan --json | \
  jq -r '.items[0].expand.assignee.name')
[ "$aname" = "bryan" ] || fail "list --json: expected expand.assignee.name bryan, got '$aname'"

# --- comment add authored by config 'me'; shown in view with relative date ---
printf 'url = "%s"\nteam = "ENG"\nme = "bryan"\n' "$URL" > "$WORK/.lll.toml"
out=$(cd "$WORK" && env -u LLL_URL -u LLL_TEAM HOME="$FAKEHOME" "$LLL_ABS" issue comment ENG-7 -b "Looks good to me")
assert_contains "$out" "Commented on ENG-7" "comment add output"

out=$(LLL_URL=$URL "$LIN" issue view ENG-7)
assert_contains "$out" "Comments:" "view has comments section"
assert_contains "$out" "bryan (just now)" "view comment author and relative date"
assert_contains "$out" "Looks good to me" "view comment body"

# --- comment list without -b ---
out=$(LLL_URL=$URL "$LIN" issue comment ENG-7)
assert_contains "$out" "bryan (just now)" "comment list author"
assert_contains "$out" "Looks good to me" "comment list body"

# --- authorless comments: me unset, and me naming no member ---
out=$(LLL_URL=$URL "$LIN" issue comment ENG-7 -b "Anonymous note")
assert_contains "$out" "Commented on ENG-7" "authorless comment (me unset) accepted"

printf 'url = "%s"\nteam = "ENG"\nme = "ghost"\n' "$URL" > "$WORK/.lll.toml"
out=$(cd "$WORK" && env -u LLL_URL -u LLL_TEAM HOME="$FAKEHOME" "$LLL_ABS" issue comment ENG-7 -b "Ghost note")
assert_contains "$out" "Commented on ENG-7" "authorless comment (me unmatched) accepted"

out=$(LLL_URL=$URL "$LIN" issue comment ENG-7)
assert_contains "$out" "anon (just now)" "authorless comments render as anon"
assert_contains "$out" "Anonymous note" "authorless body listed"
assert_contains "$out" "Ghost note" "unmatched-me body listed"

# --- comment ID inference from the git branch ---
git -C "$REPO" switch -q eng-6-roundtrip-issue
out=$(cd "$REPO" && LLL_URL=$URL "$LLL_ABS" issue comment -b "From the branch")
assert_contains "$out" "Commented on ENG-6" "comment infers ID from branch"
out=$(cd "$REPO" && LLL_URL=$URL "$LLL_ABS" issue comment)
assert_contains "$out" "From the branch" "inferred comment list"

# --- no comments ---
out=$(LLL_URL=$URL "$LIN" issue comment ENG-1)
assert_contains "$out" "No comments." "empty comment list message"

# --- projects: create + list ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" project create -n "Auth Revamp" -d "Rework the login flow" --team ENG)
assert_contains "$out" "Created project Auth Revamp (planned)" "project create output"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" project create -n "Perf Push" --status started)
assert_contains "$out" "Created project Perf Push (started)" "project create with --status"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" project list)
assert_contains "$out" "Auth Revamp" "project list has Auth Revamp"
assert_contains "$out" "planned" "project list shows status"
assert_contains "$out" "ENG" "project list shows team"
# Every project belongs to exactly one team now (TASK-173), so a --team-less
# create takes LLL_TEAM and there is no "workspace" scope left to print.
out=$(LLL_URL=$URL LLL_TEAM=OPS "$LIN" project list)
assert_not_contains "$out" "Auth Revamp" "project list is scoped to the configured team"

set +e
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" project create -n "Bad" --status bogus 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "project create --status bogus: expected nonzero exit"
assert_contains "$out" "unknown status 'bogus'" "invalid project status message"

# --- labels: create + list ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" label create -n bug -c "#ff0000" --team ENG)
assert_contains "$out" "Created label bug" "label create output"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" label create -n chore)
assert_contains "$out" "Created label chore" "label create without color takes LLL_TEAM"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" label list)
assert_contains "$out" "bug" "label list has bug"
assert_contains "$out" "#ff0000" "label list shows color"
assert_contains "$out" "chore" "label list has chore"
# Labels are team-owned too, so the other team's list is empty of ours.
out=$(LLL_URL=$URL LLL_TEAM=OPS "$LIN" label list)
assert_not_contains "$out" "chore" "label list is scoped to the configured team"

# --- issue created with labels + project ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "Labeled login fix" --label bug --label chore --project "Auth Revamp")
assert_contains "$out" "Created ENG-8: Labeled login fix" "labeled create output"

out=$(LLL_URL=$URL "$LIN" issue view ENG-8)
assert_contains "$out" "Project:   Auth Revamp" "view shows project"
assert_contains "$out" "Labels:    bug, chore" "view shows labels"
out=$(LLL_URL=$URL "$LIN" issue view ENG-6)
assert_contains "$out" "Project:   none" "view shows unset project as none"
assert_contains "$out" "Labels:    none" "view shows unset labels as none"

# --- --label / --project filter issue list ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --label bug)
assert_contains "$out" "ENG-8" "label filter shows labeled issue"
assert_not_contains "$out" "ENG-6" "label filter hides unlabeled issues"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --project "Auth Revamp")
assert_contains "$out" "ENG-8" "project filter shows project issue"
assert_not_contains "$out" "ENG-6" "project filter hides other issues"

# --- --label / --project on update ---
out=$(LLL_URL=$URL "$LIN" issue update ENG-6 --project "Perf Push" --label chore)
assert_contains "$out" "Updated ENG-6" "update --project/--label output"
out=$(LLL_URL=$URL "$LIN" issue view ENG-6)
assert_contains "$out" "Project:   Perf Push" "update set project"
assert_contains "$out" "Labels:    chore" "update set labels"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --project "Perf Push")
assert_contains "$out" "ENG-6" "project filter finds updated issue"
assert_not_contains "$out" "ENG-8" "project filter scoped to Perf Push"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --label chore)
assert_contains "$out" "ENG-6" "label filter finds updated issue"
assert_contains "$out" "ENG-8" "label filter matches multi-relation membership"

# --- project view lists its issues ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" project view "Auth Revamp")
assert_contains "$out" "Name:    Auth Revamp" "project view name"
assert_contains "$out" "Status:  planned" "project view status"
assert_contains "$out" "Team:    ENG" "project view team"
assert_contains "$out" "Rework the login flow" "project view description"
assert_contains "$out" "Issues:" "project view issues section"
assert_contains "$out" "ENG-8" "project view lists its issue"
assert_contains "$out" "Labeled login fix" "project view issue title"
assert_not_contains "$out" "ENG-6" "project view scoped to its issues"

# --- --search matches title substrings ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --search "abeled login")
assert_contains "$out" "ENG-8" "search matches title substring"
assert_not_contains "$out" "ENG-6" "search hides non-matching titles"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --search "zz-no-such-title")
assert_not_contains "$out" "ENG-" "non-matching search yields no issues"

# --- unknown label / project names error with the fix ---
set +e
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "Nope" --label nosuch 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "create --label nosuch: expected nonzero exit"
assert_contains "$out" "no label named 'nosuch'" "unknown label message"
assert_contains "$out" "lll label list" "unknown label names the fix"

set +e
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "Nope" --project nosuch 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "create --project nosuch: expected nonzero exit"
assert_contains "$out" "no project named 'nosuch'" "unknown project message"
assert_contains "$out" "lll project list" "unknown project names the fix"

set +e
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --label nosuch 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "list --label nosuch: expected nonzero exit"
assert_contains "$out" "no label named 'nosuch'" "list unknown label message"

set +e
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" project view nosuch 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "project view nosuch: expected nonzero exit"
assert_contains "$out" "no project named 'nosuch'" "project view unknown name message"

# --- --json resolves expand.project and expand.labels ---
pname=$(LLL_URL=$URL "$LIN" issue view ENG-8 --json | jq -r '.expand.project.name')
[ "$pname" = "Auth Revamp" ] || fail "view --json: expected expand.project.name Auth Revamp, got '$pname'"
lname=$(LLL_URL=$URL "$LIN" issue view ENG-8 --json | jq -r '.expand.labels[0].name')
[ "$lname" = "bug" ] || fail "view --json: expected expand.labels[0].name bug, got '$lname'"
pname=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --label bug --json | \
  jq -r '.items[0].expand.project.name')
[ "$pname" = "Auth Revamp" ] || fail "list --json: expected expand.project.name Auth Revamp, got '$pname'"
lname=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --label bug --json | \
  jq -r '.items[0].expand.labels[0].name')
[ "$lname" = "bug" ] || fail "list --json: expected expand.labels[0].name bug, got '$lname'"

# --- watch: realtime event streams ---
WATCH_ALL="$DATA_DIR/watch_all.txt"    # lll watch (team-scoped, no state filter)
WATCH_TODO="$DATA_DIR/watch_todo.txt"  # lll watch --state todo
WATCH_JSON="$DATA_DIR/watch_json.txt"  # lll watch --json
WATCH_ISSUE="$DATA_DIR/watch_issue.txt"

wait_for_line() { # file needle label [tries, at 0.1s each]
  tries="${4:-100}"
  for _ in $(seq 1 "$tries"); do
    grep -qF -- "$2" "$1" 2>/dev/null && return 0
    sleep 0.1
  done
  fail "$3: expected '$2' in $1:
$(cat "$1" 2>/dev/null)"
}

LLL_URL=$URL LLL_TEAM=ENG "$LIN" watch > "$WATCH_ALL" &
WATCH_PIDS="$WATCH_PIDS $!"
LLL_URL=$URL LLL_TEAM=ENG "$LIN" watch --state todo > "$WATCH_TODO" &
WATCH_PIDS="$WATCH_PIDS $!"
LLL_URL=$URL LLL_TEAM=ENG "$LIN" watch --json > "$WATCH_JSON" &
WATCH_PIDS="$WATCH_PIDS $!"
sleep 2 # let the subscriptions establish

# matching create (lll issue create starts issues in todo)
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "Watched todo issue")
WKEY=$(printf '%s' "$out" | sed -n 's/^Created \(ENG-[0-9]*\):.*/\1/p')
[ -n "$WKEY" ] || fail "watched create: no issue key in: $out"
wait_for_line "$WATCH_ALL" "$WKEY created: Watched todo issue" "watch sees matching create"
wait_for_line "$WATCH_TODO" "$WKEY created: Watched todo issue" "watch --state todo sees todo create"

# non-matching creates: wrong state (forged via curl) and wrong team
curl -sf -X POST "$URL/api/collections/issues/records" -H "$AUTH_HDR" \
  -H 'Content-Type: application/json' \
  -d "{\"team\":\"$ENG_ID\",\"title\":\"Backlog noise issue\",\"state\":\"backlog\"}" >/dev/null
out=$(LLL_URL=$URL LLL_TEAM=OPS "$LIN" issue create -t "Ops noise issue")
assert_contains "$out" "Created OPS-" "ops noise created"
wait_for_line "$WATCH_ALL" "created: Backlog noise issue" "unfiltered watch sees backlog create"
sleep 1
assert_not_contains "$(cat "$WATCH_TODO")" "Backlog noise issue" "watch --state todo silent for non-matching state"
assert_not_contains "$(cat "$WATCH_ALL")" "Ops noise issue" "team-scoped watch silent for other teams"

# update rendered as a state transition (diffed against the seen create)
out=$(LLL_URL=$URL "$LIN" issue update "$WKEY" --state in-progress)
assert_contains "$out" "Updated $WKEY" "watched update output"
wait_for_line "$WATCH_ALL" "$WKEY update state: todo -> in-progress" "watch renders state transition"
# leaving the filter emits nothing: PB only delivers events whose record
# matches the filter after the change, so todo -> in-progress is silent there
sleep 1
assert_not_contains "$(cat "$WATCH_TODO")" "in-progress" "watch --state todo silent when record leaves filter"

# --- lll issue watch: one issue + its comments ---
LLL_URL=$URL "$LIN" issue watch "$WKEY" > "$WATCH_ISSUE" &
WATCH_PIDS="$WATCH_PIDS $!"
# the header prints once the subscription is active
wait_for_line "$WATCH_ISSUE" "Watching $WKEY" "issue watch header"

out=$(LLL_URL=$URL "$LIN" issue update "$WKEY" --state in-review --assignee bryan)
assert_contains "$out" "Updated $WKEY" "issue watch update output"
wait_for_line "$WATCH_ISSUE" "state: in-progress -> in-review" "issue watch renders state transition"
wait_for_line "$WATCH_ISSUE" "assignee: none -> bryan" "issue watch renders assignee transition"

printf 'url = "%s"\nteam = "ENG"\nme = "bryan"\n' "$URL" > "$WORK/.lll.toml"
out=$(cd "$WORK" && env -u LLL_URL -u LLL_TEAM HOME="$FAKEHOME" "$LLL_ABS" issue comment "$WKEY" -b "Watching closely")
assert_contains "$out" "Commented on $WKEY" "watched comment output"
wait_for_line "$WATCH_ISSUE" "comment by bryan: Watching closely" "issue watch sees the comment"

# --- --json emits one jq-parseable object per line ---
wait_for_line "$WATCH_JSON" "Watched todo issue" "watch --json captured the create"
while IFS= read -r line; do
  printf '%s' "$line" | jq -e '.topic and .action and .record.id' >/dev/null \
    || fail "watch --json: line is not a PB event object: $line"
done < "$WATCH_JSON"

# --- reconnect: kill PB, restart on the same port and data dir ---
WID=$(LLL_URL=$URL "$LIN" issue view "$WKEY" --json | jq -r '.id')
[ -n "$WID" ] || fail "resolving $WKEY record id"
kill "$PB_PID"
wait "$PB_PID" 2>/dev/null || true
start_pb || fail "PocketBase did not restart"
# watchers resubscribe within ~1s; keep patching (each a fresh title
# transition) until one lands, instead of trusting a fixed sleep
for i in $(seq 1 20); do
  curl -s -X PATCH "$URL/api/collections/issues/records/$WID" -H "$AUTH_HDR" \
    -H 'Content-Type: application/json' \
    -d "{\"title\":\"Back after restart $i\"}" >/dev/null || true
  sleep 1
  grep -qF -- "Back after restart" "$WATCH_ALL" && break
done
wait_for_line "$WATCH_ALL" "Back after restart" "watch survives a PB restart" 10
wait_for_line "$WATCH_ISSUE" "Back after restart" "issue watch survives a PB restart" 100

# --- delete events; issue watch exits after its issue is deleted ---
out=$(LLL_URL=$URL "$LIN" issue delete "$WKEY" --force)
assert_contains "$out" "Deleted $WKEY" "watched delete output"
wait_for_line "$WATCH_ALL" "$WKEY deleted" "watch sees the delete"
wait_for_line "$WATCH_ISSUE" "$WKEY deleted" "issue watch sees the delete"

kill $WATCH_PIDS 2>/dev/null || true
WATCH_PIDS=""

# --- completions: emit + parse smoke for each shell ---
"$LIN" completions bash > "$DATA_DIR/comp.bash"
bash -n "$DATA_DIR/comp.bash" || fail "bash completions do not parse"
out=$(cat "$DATA_DIR/comp.bash")
assert_contains "$out" "create list view update close start claim release delete comment watch url id title pr link unlink" "bash completions list issue verbs"
assert_contains "$out" "--limit" "bash completions know --limit"
assert_contains "$out" "complete -F _lll lll" "bash completions register"
"$LIN" completions zsh > "$DATA_DIR/comp.zsh"
if command -v zsh >/dev/null; then
  zsh -n "$DATA_DIR/comp.zsh" || fail "zsh completions do not parse"
fi
assert_contains "$(cat "$DATA_DIR/comp.zsh")" "compdef _lll lll" "zsh completions register"
"$LIN" completions fish > "$DATA_DIR/comp.fish"
if command -v fish >/dev/null; then
  fish -n "$DATA_DIR/comp.fish" || fail "fish completions do not parse"
fi
assert_contains "$(cat "$DATA_DIR/comp.fish")" "complete -c lll" "fish completions complete lll"

# task-127: help, completions and the parser read ONE table, so the gate
# enforces what used to be reviewed — a flag one surface knows, they all
# know. `lll watch --help` is generated from the watch spec; the completions
# entry for the verb-less watch noun reads the same table.
comp_watch=$("$LIN" completions bash | grep -F "watch,*)" | head -1 | sed "s/.*words='//;s/'.*//")
assert_contains "$comp_watch" "--state --assignee --label --project --search --json" \
  "watch completions carry exactly the watch spec's flags"
comp_doc=$("$LIN" completions bash | grep -F "doc,new" | head -1 | sed "s/.*words='//;s/'.*//")
assert_contains "$comp_doc" "-s --slug -t --title -k --kind -b --body" \
  "doc new completions carry exactly the doc new spec's flags"
comp_issue=$("$LIN" completions bash | grep -F "issue)" | head -1 | sed "s/.*words='//;s/'.*//")
assert_contains "$comp_issue" "link unlink" "issue completions include link and unlink"
help_watch=$("$LIN" watch --help)
for fl in '--state' '--assignee' '--label' '--project' '--search' '--json'; do
  assert_contains "$help_watch" "$fl" "watch help lists $fl, as its completions entry does"
done
# The reverse direction: --emoji is in the parser and the completions, and
# a flag in the completions entry but not the parser would make this error
# impossible — the two are one table now, so assert both surfaces agree on
# the flag that once drifted.
assert_contains "$(cat "$DATA_DIR/comp.bash")" "issue,create) words='-t -d --description --emoji" \
  "completions offer the parser's own issue create flags"

# TASK-177: create --json joined the spec, so its completions entry carries
# it automatically — one table (TASK-127), asserted like watch's entry above.
comp_create=$("$LIN" completions bash | grep -F "issue,create)" | head -1 | sed "s/.*words='//;s/'.*//")
assert_contains "$comp_create" "--json" "issue create completions carry --json"
set +e
out=$("$LIN" issue create --bogus 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "issue create --bogus: expected nonzero exit"
assert_contains "$out" "unknown flag: '--bogus'" "unknown flag names the flag"
assert_contains "$out" "usage: lll issue create" "unknown flag error carries the generated usage line"
set +e
out=$("$LIN" completions powershell 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "completions powershell: expected nonzero exit"
assert_contains "$out" "unknown shell" "unknown shell message"

# --- issue url / id / title: explicit arg ---
out=$(HOME="$FAKEHOME" LLL_URL=$URL "$LIN" issue url ENG-6)
[ "$out" = "http://127.0.0.1:8100/issue/ENG-6" ] || fail "issue url: got '$out'"
out=$(LLL_URL=$URL LLL_WEB_URL=https://lll.example.com "$LIN" issue url ENG-6)
[ "$out" = "https://lll.example.com/issue/ENG-6" ] || fail "issue url with LLL_WEB_URL: got '$out'"
out=$(LLL_URL=$URL "$LIN" issue id ENG-6)
[ "$out" = "ENG-6" ] || fail "issue id: got '$out'"
out=$(LLL_URL=$URL "$LIN" issue title ENG-6)
[ "$out" = "Roundtrip issue v2" ] || fail "issue title: got '$out'"

set +e
out=$(LLL_URL=$URL "$LIN" issue url ENG-99 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "issue url ENG-99: expected nonzero exit"
assert_contains "$out" "issue ENG-99 not found" "issue url unknown ID message"

# --- issue url / id / title: inferred from the git branch ---
out=$(cd "$REPO" && HOME="$FAKEHOME" LLL_URL=$URL "$LLL_ABS" issue url)
[ "$out" = "http://127.0.0.1:8100/issue/ENG-6" ] || fail "inferred issue url: got '$out'"
out=$(cd "$REPO" && LLL_URL=$URL "$LLL_ABS" issue id)
[ "$out" = "ENG-6" ] || fail "inferred issue id: got '$out'"
out=$(cd "$REPO" && LLL_URL=$URL "$LLL_ABS" issue title)
[ "$out" = "Roundtrip issue v2" ] || fail "inferred issue title: got '$out'"

# --- board prints the web URL; LLL_WEB_URL env and web_url config override ---
out=$(HOME="$FAKEHOME" "$LIN" board)
[ "$out" = "http://127.0.0.1:8100" ] || fail "board URL: got '$out'"
out=$(LLL_WEB_URL=https://lll.example.com/ "$LIN" board)
[ "$out" = "https://lll.example.com" ] || fail "board URL trims trailing slash: got '$out'"
printf 'url = "%s"\nweb_url = "https://cfg.example.com"\n' "$URL" > "$WORK/.lll.toml"
out=$(cd "$WORK" && HOME="$FAKEHOME" "$LLL_ABS" board)
[ "$out" = "https://cfg.example.com" ] || fail "board URL from config web_url: got '$out'"

# --- -w opens via the first opener on PATH (stubbed; no real browser) ---
mkdir -p "$DATA_DIR/bin"
printf '#!/bin/sh\necho "$1" >> "%s/opened.txt"\n' "$DATA_DIR" > "$DATA_DIR/bin/open"
chmod +x "$DATA_DIR/bin/open"
out=$(HOME="$FAKEHOME" PATH="$DATA_DIR/bin:$PATH" LLL_URL=$URL "$LIN" issue view ENG-6 -w)
assert_contains "$out" "Opening http://127.0.0.1:8100/issue/ENG-6" "view -w announces the URL"
out=$(HOME="$FAKEHOME" PATH="$DATA_DIR/bin:$PATH" "$LIN" board -w)
assert_contains "$out" "Opening http://127.0.0.1:8100" "board -w announces the URL"
# -w is fire-and-forget by design (the CLI must not block on a browser), so poll
# for the opener's output instead of assuming it lands within a fixed sleep.
opened=""
for _ in $(seq 1 100); do
  opened="$(cat "$DATA_DIR/opened.txt" 2>/dev/null || true)"
  case "$opened" in *"/issue/ENG-6"*) break ;; esac
  sleep 0.1
done
assert_contains "$opened" "/issue/ENG-6" "view -w invoked the opener"

# --- issue pr: clear error when gh is missing ---
# (a real gh run needs a pushed branch and GitHub auth — manual only)
set +e
out=$(PATH=/nonexistent LLL_URL=$URL "$LIN" issue pr ENG-6 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "issue pr without gh: expected nonzero exit"
assert_contains "$out" "brew install gh" "pr without gh names the fix"

# --- --limit on issue list (applied server-side via PB perPage) ---
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue list --limit 1)
[ "$(printf '%s\n' "$out" | wc -l | tr -d ' ')" = "1" ] || fail "--limit 1: expected one line:
$out"
set +e
out=$(LLL_URL=$URL "$LIN" issue list --limit 0 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "list --limit 0: expected nonzero exit"
assert_contains "$out" "--limit must be a positive integer" "invalid limit message"
set +e
out=$(LLL_URL=$URL "$LIN" issue list --limit abc 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "list --limit abc: expected nonzero exit"
assert_contains "$out" "--limit must be a positive integer" "non-numeric limit message"

# --- docs (TASK-86): new/list/view/edit round trip, issue link + unlink ---
set +e
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc view nosuch 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "doc view nosuch: expected nonzero exit"
assert_contains "$out" "no doc with slug 'nosuch'" "unknown doc message"
assert_contains "$out" "lll doc list" "unknown doc names the fix"

out=$(printf 'The port plan.\n\nStep two.' | env LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc new -s port-notes -t "Port notes" -k wiki -b -)
assert_contains "$out" "Created doc port-notes" "doc new from stdin"

set +e
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc new -s port-notes -t "Again" 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "duplicate doc slug: expected nonzero exit"
assert_contains "$out" "ENG already has a doc with slug 'port-notes'" "duplicate slug message names the team"

set +e
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc new -s "Bad Slug" -t x 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "invalid slug: expected nonzero exit"
assert_contains "$out" "invalid slug 'Bad Slug'" "invalid slug message"

out=$(printf 'raw finding body' | env LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc new -s race-found -t "Race found" -k finding -b -)
assert_contains "$out" "Created doc race-found" "doc new with kind finding"

out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc list)
assert_contains "$out" "port-notes	wiki	Port notes" "doc list shows slug, kind, title"
assert_contains "$out" "race-found	finding	Race found" "doc list shows second doc"

out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc view port-notes)
assert_contains "$out" "port-notes Port notes" "doc view header"
assert_contains "$out" "Kind:      wiki" "doc view kind"
assert_contains "$out" "The port plan." "doc view body"

out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc view port-notes --raw)
[ "$out" = "The port plan.

Step two." ] || fail "doc view --raw should print only the body, got: $out"

# edit replaces the whole body from stdin
out=$(printf 'Replaced body' | env LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc edit port-notes -b -)
assert_contains "$out" "Updated doc port-notes" "doc edit from stdin"
got=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc view port-notes --raw)
[ "$got" = "Replaced body" ] || fail "doc edit should replace the whole body, got: '$got'"

# issue link: doc view shows the issue, issue view shows the doc
ENG1_ID=$(LLL_URL=$URL "$LIN" issue view ENG-1 --json | jq -r .id)
set +e
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue link ENG-1 nosuch 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "issue link unknown slug: expected nonzero exit"
assert_contains "$out" "no doc with slug 'nosuch'" "link unknown doc names the fix"

out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue link ENG-1 port-notes)
assert_contains "$out" "Linked ENG-1 -> port-notes" "issue link output"

out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc view port-notes)
assert_contains "$out" "Issues:    ENG-1" "doc view shows linked issue"
out=$(LLL_URL=$URL "$LIN" issue view ENG-1)
assert_contains "$out" "Docs:      port-notes" "issue view shows linked doc"
rid=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc view port-notes --json | jq -r '.issues[0]')
[ "$rid" = "$ENG1_ID" ] || fail "doc record issues relation: expected $ENG1_ID, got '$rid'"

# linking twice is idempotent
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue link ENG-1 port-notes)
assert_contains "$out" "already linked" "double link is idempotent"

# relink corrects a wrong link: unlink the wrong issue, keep the right one
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue link ENG-2 port-notes)
assert_contains "$out" "Linked ENG-2 -> port-notes" "second issue links"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue unlink ENG-1 port-notes)
assert_contains "$out" "Unlinked ENG-1 from port-notes" "issue unlink output"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc view port-notes)
assert_contains "$out" "ENG-2" "relinked doc shows ENG-2"
assert_not_contains "$out" "ENG-1" "relinked doc no longer shows ENG-1"
set +e
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue unlink ENG-1 port-notes 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "unlink not-linked: expected nonzero exit"
assert_contains "$out" "is not linked to" "unlink not-linked message"

# deleting a linked issue unsets the relation; the doc survives
key=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue create -t "Doc link fodder" | sed -n 's/^Created \([A-Z]*-[0-9]*\).*/\1/p')
[ -n "$key" ] || fail "doc-link fodder create did not print a key"
env LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue link "$key" race-found >/dev/null
env LLL_URL=$URL "$LIN" issue delete "$key" --force >/dev/null
n=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc view race-found --json | jq -r '.issues | length')
[ "$n" = "0" ] || fail "deleting a linked issue should unset the relation, got: $n"
assert_contains "$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc view race-found)" "race-found Race found" "doc survives a linked issue's deletion"

# --- findings (TASK-103): authorship with area/paths, near by path, list,
# issue view surfacing. A finding is a doc with kind=finding; retrieval is
# by area and path — a filter, never a body search.
out=$(printf 'Migrations are a merge hazard.' | env LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc new -s migration-hazard -t "Migration collisions" -k finding -a pb -p "pb/pb_migrations, src/pb" -b -)
assert_contains "$out" "Created doc migration-hazard" "doc new takes area and paths"

out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" doc view migration-hazard)
assert_contains "$out" "Kind:      finding" "finding view shows kind"
assert_contains "$out" "Area:      pb" "finding view shows area"
assert_contains "$out" "Paths:     pb/pb_migrations, src/pb" "finding view shows paths"

# near: exact path, parent directory, and a file inside a stored directory —
# containment matches in both directions.
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" finding near src/pb)
assert_contains "$out" "migration-hazard" "finding near matches the exact path"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" finding near src)
assert_contains "$out" "migration-hazard" "finding near matches the parent directory"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" finding near src/pb/up.lis)
assert_contains "$out" "migration-hazard" "finding near matches a file inside a stored directory"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" finding near web/templates)
assert_contains "$out" "No findings for web/templates." "finding near with no match says so"

out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" finding list)
assert_contains "$out" "migration-hazard	pb	Migration collisions" "finding list prints slug, area, title"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" finding list --area pb)
assert_contains "$out" "migration-hazard" "finding list --area matches"
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" finding list --area nothing)
assert_contains "$out" "No findings." "finding list --area without a match"

# Issue view surfaces related findings (the brief mechanism, AC#3): a
# finding linked to the issue always shows; a finding whose area names one
# of the issue's labels shows without any link.
env LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue link ENG-1 race-found >/dev/null
out=$(LLL_URL=$URL "$LIN" issue view ENG-1)
assert_contains "$out" "Related findings:" "issue view has a related findings section"
assert_contains "$out" "race-found (-) — Race found" "a linked finding always shows"

LLL_URL=$URL LLL_TEAM=ENG "$LIN" label create -n pb >/dev/null
env LLL_URL=$URL "$LIN" issue update ENG-1 --label pb >/dev/null
out=$(LLL_URL=$URL "$LIN" issue view ENG-1)
assert_contains "$out" "migration-hazard (pb) — Migration collisions" "an area-matched finding surfaces by label"

out=$(env LLL_URL=$URL "$LIN" issue view ENG-1 --raw)
assert_contains "$out" "## Related findings" "issue view --raw carries related findings"
assert_contains "$out" "- migration-hazard (pb): Migration collisions" "issue view --raw lists the finding"

# --- team scoping past issues (TASK-173): one server, many projects ---
# OPS is the second project on this server. Everything below is what breaks
# when only issues honour the tenancy boundary.

# A slug is unique per TEAM, not per server: without this, the second project
# to write a wiki page called "port-notes" fails on a global unique index.
out=$(LLL_URL=$URL LLL_TEAM=OPS "$LIN" doc new -s port-notes -t "OPS port notes" -b "ops body")
assert_contains "$out" "Created doc port-notes" "two teams both hold a doc slugged port-notes"
out=$(LLL_URL=$URL LLL_TEAM=OPS "$LIN" doc view port-notes --raw)
assert_contains "$out" "ops body" "doc view resolves inside the configured team"
out=$(LLL_URL=$URL LLL_TEAM=OPS "$LIN" doc list)
assert_not_contains "$out" "Port notes" "doc list does not show the other team's doc"

# finding near answers about THIS codebase. Every project has a src/, so an
# unscoped filter would return another repo's notes, formatted identically.
env LLL_URL=$URL LLL_TEAM=OPS "$LIN" doc new -s ops-hazard -t "OPS hazard" -k finding \
  -a pb -p "pb/pb_migrations, src/pb" -b "ops" >/dev/null
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" finding near src/pb)
assert_contains "$out" "migration-hazard" "finding near still finds this team's finding"
assert_not_contains "$out" "ops-hazard" "finding near never surfaces another team's finding"
out=$(LLL_URL=$URL LLL_TEAM=OPS "$LIN" finding list)
assert_not_contains "$out" "migration-hazard" "finding list is scoped too"

# With no team there is nothing to scope to, so the answer is a refusal
# rather than every project's findings at once.
set +e
out=$(env -u LLL_TEAM LLL_URL=$URL "$LIN" finding near src 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "finding near without a team: expected nonzero exit"
assert_contains "$out" "set LLL_TEAM" "unscoped finding near names the fix"

# A link crossing tenancy is refused, not silently stitched.
set +e
out=$(LLL_URL=$URL LLL_TEAM=OPS "$LIN" issue link ENG-1 port-notes 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "cross-team issue link: expected nonzero exit"
assert_contains "$out" "a link stays inside one team" "cross-team link is refused"

# Labels are team-owned, so the same name on two boards is two labels and an
# issue takes its own team's.
LLL_URL=$URL LLL_TEAM=OPS "$LIN" label create -n pb >/dev/null
out=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" label list)
assert_contains "$out" "pb" "ENG still has its own pb label"
# The id ENG's issue carries is ENG's pb, not OPS's same-named one. Two
# labels now answer to "pb"; only one may reach an ENG issue.
eng_pb=$(curl -sf -H "$AUTH_HDR" "$URL/api/collections/labels/records?perPage=200&expand=team" | \
  jq -r '.items[] | select(.name == "pb" and .expand.team.key == "ENG") | .id')
got=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue view ENG-1 --json | jq -r --arg id "$eng_pb" '.labels | index($id) // "missing"')
[ "$got" != "missing" ] || fail "ENG-1 does not carry ENG's pb label ($eng_pb)"
ops_pb=$(curl -sf -H "$AUTH_HDR" "$URL/api/collections/labels/records?perPage=200&expand=team" | \
  jq -r '.items[] | select(.name == "pb" and .expand.team.key == "OPS") | .id')
got=$(LLL_URL=$URL LLL_TEAM=ENG "$LIN" issue view ENG-1 --json | jq -r --arg id "$ops_pb" '.labels | index($id) // "absent"')
[ "$got" = "absent" ] || fail "ENG-1 picked up OPS's pb label ($ops_pb)"
out=$(env LLL_URL=$URL "$LIN" issue view ENG-2 --raw)
assert_not_contains "$out" "Related findings" "an issue with no matches renders no findings section"

out=$("$LIN" finding --help)
assert_contains "$out" "lll finding near" "finding --help mentions near"
assert_contains "$out" "lll finding list" "finding --help mentions list"
out=$("$LIN" --help)
assert_contains "$out" "lll finding" "lll --help mentions finding"
out=$("$LIN" doc --help)
assert_contains "$out" "-a" "doc --help mentions the area flag"
assert_contains "$out" "-p" "doc --help mentions the paths flag"

# --- task-179: the pb client sends the configured token --------------------
# A scratch HTTP listener records the Authorization header of whatever the
# CLI sends it; LLL_TOKEN is machine state, so it rides the env, and the
# response is PB-shaped JSON so the command itself succeeds. The listener is
# generated once and told per-run whether a header is expected.
SPY="$DATA_DIR/spy_server.py"
cat > "$SPY" <<'SPY_EOF'
import http.server, socketserver, sys
port, rec, body_mode = int(sys.argv[1]), sys.argv[2], sys.argv[3]
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        with open(rec, "a") as f:
            f.write((self.headers.get("Authorization") or "<none>") + "\n")
        body = b'{"items":[],"totalItems":0,"page":1,"perPage":200}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass
socketserver.TCPServer(("127.0.0.1", port), H).serve_forever()
SPY_EOF

run_spy() { # rec port -> records one GET's Authorization header
  python3 "$SPY" "$2" "$1" x >/dev/null 2>&1 &
  SPY_PIDS="${SPY_PIDS:-} $!"
  sleep 0.4
}
SPY_PIDS=""

REC="$DATA_DIR/auth-header.txt"
SPY_PORT=$(free_port 20000 39999)
run_spy "$REC" "$SPY_PORT"
out=$(LLL_URL="http://127.0.0.1:$SPY_PORT" LLL_TOKEN="spy-token-123" "$LIN" team list)
assert_contains "$(cat "$REC")" "Bearer spy-token-123" \
  "the pb client sends the configured token as its Authorization header"

REC2="$DATA_DIR/auth-header-none.txt"
SPY2_PORT=$(free_port 20000 39999)
run_spy "$REC2" "$SPY2_PORT"
out=$(env -u LLL_TOKEN LLL_URL="http://127.0.0.1:$SPY2_PORT" "$LIN" team list)
assert_contains "$(cat "$REC2")" "<none>" \
  "no token configured sends no Authorization header"

for pid in $SPY_PIDS; do kill "$pid" 2>/dev/null || true; done
SPY_PIDS=""

# --- help output ---
out=$("$LIN" --help)
assert_contains "$out" "Usage:" "lll --help"
assert_contains "$out" "lll team" "lll --help mentions team"
assert_contains "$out" "lll member" "lll --help mentions member"
assert_contains "$out" "lll project" "lll --help mentions project"
assert_contains "$out" "lll label" "lll --help mentions label"
assert_contains "$out" "lll doc" "lll --help mentions doc"
assert_contains "$out" "lll config" "lll --help mentions config"
assert_contains "$out" "lll watch" "lll --help mentions watch"
assert_contains "$out" "lll board" "lll --help mentions board"
assert_contains "$out" "lll completions" "lll --help mentions completions"
out=$("$LIN" issue --help)
assert_contains "$out" "Usage:" "lll issue --help"
assert_contains "$out" "lll issue update" "issue --help mentions update"
assert_contains "$out" "lll issue close" "issue --help mentions close"
assert_contains "$out" "lll issue start" "issue --help mentions start"
assert_contains "$out" "lll issue delete" "issue --help mentions delete"
assert_contains "$out" "lll issue comment" "issue --help mentions comment"
assert_contains "$out" "--assignee" "issue --help mentions --assignee"
assert_contains "$out" "--label" "issue --help mentions --label"
assert_contains "$out" "--project" "issue --help mentions --project"
assert_contains "$out" "--search" "issue --help mentions --search"
assert_contains "$out" "lll issue watch" "issue --help mentions watch"
assert_contains "$out" "lll issue url" "issue --help mentions url"
assert_contains "$out" "lll issue pr" "issue --help mentions pr"
assert_contains "$out" "--limit" "issue --help mentions --limit"
out=$("$LIN" board --help)
assert_contains "$out" "Usage:" "lll board --help"
assert_contains "$out" "-w" "board --help mentions -w"
out=$("$LIN" completions --help)
assert_contains "$out" "Usage:" "lll completions --help"
assert_contains "$out" "eval" "completions --help shows the eval line"
out=$("$LIN" watch --help)
assert_contains "$out" "Usage:" "lll watch --help"
assert_contains "$out" "--state" "watch --help mentions --state"
assert_contains "$out" "--json" "watch --help mentions --json"
out=$("$LIN" member --help)
assert_contains "$out" "Usage:" "lll member --help"
assert_contains "$out" "lll member add" "member --help mentions add"
out=$("$LIN" team --help)
assert_contains "$out" "Usage:" "lll team --help"
out=$("$LIN" project --help)
assert_contains "$out" "Usage:" "lll project --help"
assert_contains "$out" "lll project view" "project --help mentions view"
out=$("$LIN" label --help)
assert_contains "$out" "Usage:" "lll label --help"
assert_contains "$out" "lll label create" "label --help mentions create"
out=$("$LIN" doc --help)
assert_contains "$out" "Usage:" "lll doc --help"
assert_contains "$out" "lll doc new" "doc --help mentions new"
assert_contains "$out" "lll doc edit" "doc --help mentions edit"
assert_contains "$out" "--raw" "doc --help mentions --raw"
assert_contains "$out" "-b" "doc --help mentions -b"
out=$("$LIN" config --help)
assert_contains "$out" "Usage:" "lll config --help"
out=$("$LIN" up --help)
assert_contains "$out" "Usage:" "lll up --help"
assert_contains "$out" "--port" "up --help mentions --port"

# --- --version prints the lisette.toml version ---
out=$("$LIN" --version)
want="lll $(sed -n 's/^version = "\(.*\)"/\1/p' lisette.toml | head -1)"
[ "$out" = "$want" ] || fail "--version: expected '$want', got '$out'"
[ "$("$LIN" version)" = "$want" ] || fail "'lll version': expected '$want'"

# --- error messages name the fix ---
# unknown top-level command points at --help
set +e
out=$("$LIN" frobnicate 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "unknown command: expected nonzero exit"
assert_contains "$out" "see 'lll --help'" "unknown command names the fix"

# PB unreachable: names lll up and LLL_URL (request path and realtime path)
set +e
out=$(LLL_URL=http://127.0.0.1:1 "$LIN" issue list 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "issue list with PB down: expected nonzero exit"
assert_contains "$out" "cannot reach PocketBase at http://127.0.0.1:1" "PB-down names the server"
assert_contains "$out" "start everything with 'lll up'" "PB-down names lll up"
assert_contains "$out" "LLL_URL" "PB-down names LLL_URL"
set +e
out=$(LLL_URL=http://127.0.0.1:1 LLL_TEAM= "$LIN" watch 2>&1)
set -e
assert_contains "$out" "start everything with 'lll up'" "watch PB-down names lll up"

# unknown team names team list / team create
set +e
out=$(LLL_URL=$URL "$LIN" team view NOPE 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "team view NOPE: expected nonzero exit"
assert_contains "$out" "no team with key 'NOPE'" "unknown team message"
assert_contains "$out" "lll team create -k NOPE" "unknown team names the fix"
set +e
out=$(LLL_URL=$URL LLL_TEAM=NOPE "$LIN" issue create -t x 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "create with unknown team: expected nonzero exit"
assert_contains "$out" "lll team create -k NOPE" "create unknown team names the fix"

# broken config file names the file and the fix
printf 'url = "unterminated\n' > "$WORK/.lll.toml"
set +e
out=$(cd "$WORK" && env -u LLL_URL HOME="$FAKEHOME" "$LLL_ABS" issue list 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "broken .lll.toml: expected nonzero exit"
assert_contains "$out" "parsing .lll.toml" "broken config names the file"
assert_contains "$out" "fix the TOML syntax" "broken config names the fix"
rm "$WORK/.lll.toml"

# --- bodies from stdin: `-d -` and `-b -` (task-37) ---
# The config section above removed .lll.toml, so pass the scope explicitly.
E="LLL_URL=$URL LLL_TEAM=ENG"
out=$(printf 'piped description' | env $E "$LIN" issue create -t "From stdin" -d -)
key=$(printf '%s' "$out" | sed -n 's/^Created \([A-Z]*-[0-9]*\).*/\1/p')
[ -n "$key" ] || fail "stdin create did not print a key: $out"
got=$(env $E "$LIN" issue view "$key" --json | jq -r .description)
[ "$got" = "piped description" ] || fail "-d - description: got '$got'"

# one trailing newline is the shell's, not the author's
out=$(echo "trailing" | env $E "$LIN" issue create -t "Stdin newline" -d -)
key2=$(printf '%s' "$out" | sed -n 's/^Created \([A-Z]*-[0-9]*\).*/\1/p')
got=$(env $E "$LIN" issue view "$key2" --json | jq -r .description)
[ "$got" = "trailing" ] || fail "-d - should strip the trailing newline: got '$got'"

printf 'piped comment body' | env $E "$LIN" issue comment "$key" -b - >/dev/null
assert_contains "$(env $E "$LIN" issue comment "$key")" "piped comment body" "-b - reads the comment from stdin"

# a literal value still works, and only an exact "-" means stdin
env $E "$LIN" issue update "$key" --description "literal again" >/dev/null
got=$(env $E "$LIN" issue view "$key" --json | jq -r .description)
[ "$got" = "literal again" ] || fail "literal --description regressed: got '$got'"

# nothing piped in: refuse rather than hang
if out=$(env $E "$LIN" issue create -t "no stdin" -d - </dev/null 2>&1); then
  fail "-d - with no pipe should exit non-zero, got: $out"
fi
assert_contains "$out" "nothing is piped in" "-d - with no pipe names the fix"

# --- create --json (TASK-177): the raw record, pipe-safe and keyable ---
# Scripts used to parse the "Created KEY-N" sentence for the key; --json
# hands them the record itself instead — same shape as `view --json`.
out=$(env $E "$LIN" issue create -t "Create json target" --json)
case "$out" in *Created*) fail "create --json must replace the sentence, got: $out";; esac
cj_id=$(printf '%s' "$out" | jq -r .id)
cj_num=$(printf '%s' "$out" | jq -r .number)
cj_team=$(printf '%s' "$out" | jq -r .team)
[ -n "$cj_id" ] && [ "$cj_id" != "null" ] || fail "create --json: .id missing"
[ -n "$cj_num" ] && [ "$cj_num" != "null" ] || fail "create --json: .number missing"
[ -n "$cj_team" ] && [ "$cj_team" != "null" ] || fail "create --json: .team missing"
cj_key=$(printf '%s' "$out" | jq -r '.expand.team.key')-$cj_num
vid=$(env $E "$LIN" issue view "$cj_key" --json | jq -r .id)
[ "$vid" = "$cj_id" ] || fail "create --json: .id $cj_id does not match view --json id $vid"

# --- agent read path: --raw, and a pasted board URL anywhere a key goes (task-36) ---
out=$(env $E "$LIN" issue view "$key" --raw)
assert_contains "$out" "# $key: From stdin" "--raw prints a markdown heading"
assert_contains "$out" "literal again" "--raw prints the description verbatim"
printf '%s' "$out" | grep -qF "Assignee" && fail "--raw should not print the property table"

# a pasted board URL is accepted anywhere the key is
assert_contains "$(env $E "$LIN" issue title "http://127.0.0.1:8100/issue/$key")" "From stdin" \
  "issue title accepts a pasted board URL"
[ "$(env $E "$LIN" issue id "http://127.0.0.1:8100/issue/$key/")" = "$key" ] \
  || fail "issue id should accept a URL with a trailing slash"
[ "$(env $E "$LIN" issue id "$key")" = "$key" ] || fail "a bare key must still work"

# a URL that is not an issue page is not silently misparsed
if env $E "$LIN" issue view "http://example.com/a/b/c/NOPE-9" >/dev/null 2>&1; then
  fail "a non-issue URL should not resolve"
fi

# --- claims (TASK-175): exclusive, atomic, released ---
# `issue update --assignee` is a last-write-wins PATCH: two agents both
# "win" and neither is told. `issue claim` is an INSERT into a collection
# that is UNIQUE on issue, so the database arbitrates.
CKEY=$(env $E "$LIN" issue create -t "Claimable" | sed -n 's/^Created \([A-Z]*-[0-9]*\).*/\1/p')
[ -n "$CKEY" ] || fail "claim fodder create did not print a key"

out=$(env $E LLL_ME=bryan "$LIN" issue claim "$CKEY")
assert_contains "$out" "Claimed $CKEY for bryan" "claim output"
out=$(env $E "$LIN" issue view "$CKEY")
assert_contains "$out" "Claimed:   bryan" "issue view shows the holder"
assert_contains "$out" "Assignee:  bryan" "claiming assigns the issue"

# AC#1: a held issue refuses the second claim and changes nothing.
set +e
out=$(env $E LLL_ME=carol "$LIN" issue claim "$CKEY" 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "claiming a held issue: expected nonzero exit"
assert_contains "$out" "already claimed by bryan" "refusal names the holder"
assert_contains "$out" "lll issue release $CKEY" "refusal names the fix"
out=$(env $E "$LIN" issue view "$CKEY")
assert_contains "$out" "Assignee:  bryan" "a refused claim leaves the assignee alone"
assert_contains "$out" "Claimed:   bryan" "a refused claim leaves the holder alone"

# Held is held, including by you: re-claiming is not a silent no-op.
set +e
out=$(env $E LLL_ME=bryan "$LIN" issue claim "$CKEY" 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "re-claiming your own hold: expected nonzero exit"
assert_contains "$out" "already claimed by bryan" "re-claim names the holder"

# AC#3: release gives it back, and the next claim succeeds.
out=$(env $E "$LIN" issue release "$CKEY")
assert_contains "$out" "Released $CKEY (was bryan's)" "release output"
out=$(env $E "$LIN" issue view "$CKEY")
assert_not_contains "$out" "Claimed:" "release removes the hold"
assert_contains "$out" "Assignee:  none" "release clears the assignee the claim set"
out=$(env $E LLL_ME=carol "$LIN" issue claim "$CKEY")
assert_contains "$out" "Claimed $CKEY for carol" "a released issue can be claimed again"

# Releasing what nobody holds is an error, not a no-op.
env $E "$LIN" issue release "$CKEY" >/dev/null
set +e
out=$(env $E "$LIN" issue release "$CKEY" 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "releasing an unclaimed issue: expected nonzero exit"
assert_contains "$out" "$CKEY is not claimed" "double release names the state"

# No 'me' to claim as: refuse and name the fix. $WORK has no .lll.toml and
# $FAKEHOME no user config, so 'me' is genuinely unset here.
set +e
out=$(cd "$WORK" && env LLL_URL=$URL HOME="$FAKEHOME" "$LLL_ABS" issue claim "$CKEY" 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "claim without 'me': expected nonzero exit"
assert_contains "$out" "lll config set me" "claim without 'me' names the fix"

# AC#2, at the REST layer: fire N creates at one issue at once and count the
# survivors. This is the atomicity claim itself — the unique index, with no
# lll process in the way to serialise anything.
RKEY=$(env $E "$LIN" issue create -t "Race target" | sed -n 's/^Created \([A-Z]*-[0-9]*\).*/\1/p')
RID=$(env $E "$LIN" issue view "$RKEY" --json | jq -r .id)
MID=$(curl -sf -H "$AUTH_HDR" "$URL/api/collections/members/records?perPage=1" | jq -r '.items[0].id')
RACE="$DATA_DIR/race"
mkdir -p "$RACE"
# Wait on these pids by name, never bare `wait`: the suite's own `lll up`
# is a background job of this shell and would never return.
race_pids=""
for i in $(seq 1 16); do
  (curl -s -o /dev/null -w '%{http_code}\n' -X POST "$URL/api/collections/claims/records" \
     -H "$AUTH_HDR" \
     -H 'Content-Type: application/json' \
     -d "{\"issue\":\"$RID\",\"member\":\"$MID\"}" > "$RACE/$i.code") &
  race_pids="$race_pids $!"
done
wait $race_pids || true
won=$(cat "$RACE"/*.code | grep -c '^2' || true)
[ "$won" = 1 ] || fail "16 concurrent claim inserts: expected exactly 1 to succeed, got $won
$(cat "$RACE"/*.code | sort | uniq -c)"
rows=$(curl -sf -H "$AUTH_HDR" "$URL/api/collections/claims/records?perPage=200" | \
  jq --arg id "$RID" '[.items[] | select(.issue==$id)] | length')
[ "$rows" = 1 ] || fail "after the race the issue should hold exactly 1 claim row, got $rows"

WON_ID=$(curl -sf -H "$AUTH_HDR" "$URL/api/collections/claims/records?perPage=200" | \
  jq -r --arg id "$RID" '[.items[] | select(.issue==$id)][0].id')
# The winning row is not editable, or a loser has a second door: PATCH the
# holder's `member` to itself, which an index on `issue` alone would allow.
# With the rules on, this is a MEMBER token and claims.updateRule is still
# null (superuser only, TASK-175): the refusal is exactly 403.
code=$(curl -s -o /dev/null -w '%{http_code}' -X PATCH \
  "$URL/api/collections/claims/records/$WON_ID" \
  -H 'Content-Type: application/json' -H "$AUTH_HDR" -d "{\"member\":\"$MID\"}")
[ "$code" = 403 ] || fail "PATCH on a claim should be superuser-only (updateRule null), got $code"

# AC#2, through the CLI: three real `lll issue claim` processes, one issue.
CRKEY=$(env $E "$LIN" issue create -t "CLI race target" | sed -n 's/^Created \([A-Z]*-[0-9]*\).*/\1/p')
CRACE="$DATA_DIR/clirace"
mkdir -p "$CRACE"
cli_pids=""
for m in bryan carol alice; do
  # set +e inside: two of these three MUST fail, and errexit is inherited by
  # a subshell — without it the losers die before recording their status.
  (set +e
   env $E LLL_ME="$m" "$LIN" issue claim "$CRKEY" > "$CRACE/$m.out" 2>&1
   echo $? > "$CRACE/$m.rc") &
  cli_pids="$cli_pids $!"
done
wait $cli_pids || true
wins=$(cat "$CRACE"/*.rc | grep -c '^0$' || true)
[ "$wins" = 1 ] || fail "3 concurrent 'lll issue claim': expected exactly 1 winner, got $wins
$(head -100 "$CRACE"/*.out)"
losers=$(cat "$CRACE"/*.out | grep -c 'already claimed by' || true)
[ "$losers" = 2 ] || fail "the 2 losers should each be told who holds it, got $losers"

out=$("$LIN" issue --help)
assert_contains "$out" "lll issue claim" "issue --help mentions claim"
assert_contains "$out" "lll issue release" "issue --help mentions release"
assert_contains "$("$LIN" completions bash)" "claim" "bash completions offer claim"

echo "e2e: all assertions passed"

# --- web board (own ephemeral PB; see e2e_web.sh) ---
scripts/e2e_web.sh

# --- lll up runner (own ephemeral PB; see e2e_up.sh) ---
scripts/e2e_up.sh
