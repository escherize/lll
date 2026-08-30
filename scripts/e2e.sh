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
# unknown command), and the lll up web board (via e2e_web.sh).
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
  # this suite.
  LLL_URL="$URL" LLL_TEAM=ENG USER=e2e "$LIN" up --no-open \
    --pb-dir "$DATA_DIR/pb_data" --port "$WEB_PORT" </dev/null >>"$PB_LOG" 2>&1 &
  PB_PID=$!
  wait_ok "$URL/api/health" 150
}
start_pb || { echo "FAIL: lll up did not start" >&2; cat "$PB_LOG" >&2; exit 1; }
WATCH_PIDS=""
cleanup() {
  kill $WATCH_PIDS "$PB_PID" 2>/dev/null || true
  e2e_end
}
trap cleanup EXIT

json_id() { python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'; }

# `lll up` created ENG with name "ENG"; create-or-fetch, then set the name the
# assertions expect. Idempotent so the mid-suite restart cannot double-create.
seed_team() { # key name -> prints the record id
  q=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(f"key=\x27{sys.argv[1]}\x27"))' "$1")
  id=$(curl -sf "$URL/api/collections/teams/records?filter=$q" \
       | python3 -c 'import json,sys; it=json.load(sys.stdin)["items"]; print(it[0]["id"] if it else "")')
  if [ -z "$id" ]; then
    id=$(curl -sf -X POST "$URL/api/collections/teams/records" \
      -H 'Content-Type: application/json' -d "{\"key\":\"$1\",\"name\":\"$2\"}" | json_id)
  else
    curl -sf -X PATCH "$URL/api/collections/teams/records/$id" \
      -H 'Content-Type: application/json' -d "{\"name\":\"$2\"}" >/dev/null
  fi
  printf '%s' "$id"
}
ENG_ID=$(seed_team ENG Engineering)
OPS_ID=$(seed_team OPS Operations)
[ -n "$ENG_ID" ] && [ -n "$OPS_ID" ] || fail "seeding teams"

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
status=$(curl -s -o "$DATA_DIR/forged.json" -w '%{http_code}' \
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
out=$(cd "$WORK" && "$LLL_ABS" config set me alice)
assert_contains "$out" 'me = "alice"' "config set me output"
assert_contains "$out" "lll member add" "config set me names the member fix"
assert_contains "$(cat "$WORK/.lll.toml")" 'me = "alice"' "config set me wrote the key"
(cd "$WORK" && "$LLL_ABS" config set me bob >/dev/null)
[ "$(grep -c '^me = ' "$WORK/.lll.toml")" = 1 ] \
  || fail "config set me appended a duplicate key: $(cat "$WORK/.lll.toml")"
assert_contains "$(cat "$WORK/.lll.toml")" 'me = "bob"' "config set me replaced the value"
# A duplicate key would make the file unparseable; prove it still loads.
out=$(cd "$WORK" && LLL_URL=$URL LLL_TEAM=ENG "$LLL_ABS" issue list)
assert_contains "$out" "ENG-1" "config still parses after two config set me"
out=$(cd "$WORK" && "$LLL_ABS" config set url http://x 2>&1) && fail "config set accepted a key other than me"
assert_contains "$out" "only 'me' is settable" "config set rejects other keys"
rm "$WORK/.lll.toml"

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
curl -sf -X PATCH "$URL/api/collections/issues/records/$ENG3_ID" \
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
curl -sf -X PATCH "$URL/api/collections/issues/records/$ENG3_ID" \
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
out=$(LLL_URL=$URL "$LIN" member add -n alice)
assert_contains "$out" "Added member alice" "member add without email"
out=$(LLL_URL=$URL "$LIN" member list)
assert_contains "$out" "bryan" "member list has bryan"
assert_contains "$out" "bryan@example.com" "member list shows email"
assert_contains "$out" "alice" "member list has alice"

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
out=$(LLL_URL=$URL "$LIN" project create -n "Auth Revamp" -d "Rework the login flow" --team ENG)
assert_contains "$out" "Created project Auth Revamp (planned)" "project create output"
out=$(LLL_URL=$URL "$LIN" project create -n "Perf Push" --status started)
assert_contains "$out" "Created project Perf Push (started)" "project create with --status"
out=$(LLL_URL=$URL "$LIN" project list)
assert_contains "$out" "Auth Revamp" "project list has Auth Revamp"
assert_contains "$out" "planned" "project list shows status"
assert_contains "$out" "ENG" "project list shows team"
assert_contains "$out" "workspace" "project list shows workspace scope"

set +e
out=$(LLL_URL=$URL "$LIN" project create -n "Bad" --status bogus 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "project create --status bogus: expected nonzero exit"
assert_contains "$out" "unknown status 'bogus'" "invalid project status message"

# --- labels: create + list ---
out=$(LLL_URL=$URL "$LIN" label create -n bug -c "#ff0000" --team ENG)
assert_contains "$out" "Created label bug" "label create output"
out=$(LLL_URL=$URL "$LIN" label create -n chore)
assert_contains "$out" "Created label chore" "label create without color/team"
out=$(LLL_URL=$URL "$LIN" label list)
assert_contains "$out" "bug" "label list has bug"
assert_contains "$out" "#ff0000" "label list shows color"
assert_contains "$out" "chore" "label list has chore"
assert_contains "$out" "workspace" "label list shows workspace scope"

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
out=$(LLL_URL=$URL "$LIN" project view "Auth Revamp")
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
out=$(LLL_URL=$URL "$LIN" project view nosuch 2>&1)
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
curl -sf -X POST "$URL/api/collections/issues/records" \
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
  curl -s -X PATCH "$URL/api/collections/issues/records/$WID" \
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
assert_contains "$out" "create list view update close start delete comment watch url id title pr" "bash completions list issue verbs"
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

# --- help output ---
out=$("$LIN" --help)
assert_contains "$out" "Usage:" "lll --help"
assert_contains "$out" "lll team" "lll --help mentions team"
assert_contains "$out" "lll member" "lll --help mentions member"
assert_contains "$out" "lll project" "lll --help mentions project"
assert_contains "$out" "lll label" "lll --help mentions label"
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

echo "e2e: all assertions passed"

# --- web board (own ephemeral PB; see e2e_web.sh) ---
scripts/e2e_web.sh

# --- lll up runner (own ephemeral PB; see e2e_up.sh) ---
scripts/e2e_up.sh
