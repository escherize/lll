#!/usr/bin/env bash
# e2e: ephemeral PocketBase + compiled lin CLI.
# Covers: create/list with ENG-1 style IDs, per-team numbering,
# forged duplicate (team, number) rejection, issue view (fields, unknown IDs),
# --json (jq roundtrips, expand.team), --state/--sort filters, glyph/priority
# display, write path (start/update/close/delete, git branch creation and
# ID inference from the branch), members (add/list), comments (add via config
# 'me', authorless, list, in issue view), --assignee (create/update/list
# filter, unknown member, expand in --json), projects and labels (create/list,
# project view with its issues, --label/--project on issue create/update and
# as list filters, --search, unknown names, expand in --json), --help output.
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

# A superuser must exist or serve auto-opens the browser install wizard.
"$PB_BIN" superuser upsert e2e@local.test e2e-password-123 \
  --dir "$DATA_DIR/pb_data" >"$PB_LOG" 2>&1 \
  || { echo "FAIL: creating PB superuser" >&2; cat "$PB_LOG" >&2; exit 1; }

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
  printf '%s' "$1" | grep -qF -- "$2" || fail "$3: expected '$2' in output:
$1"
}
assert_not_contains() {
  printf '%s' "$1" | grep -qF -- "$2" && fail "$3: did not expect '$2' in output:
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

# --- issue view: full fields, glyphs, priority, relative dates, description ---
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue create -t "Fix login flow" --priority 2)
assert_contains "$out" "Created ENG-3: Fix login flow" "create with --priority"

ENG3_ID=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --json | \
  jq -r '.items[] | select(.title=="Fix login flow") | .id')
[ -n "$ENG3_ID" ] || fail "resolving ENG-3 record id from --json"
curl -sf -X PATCH "$URL/api/collections/issues/records/$ENG3_ID" \
  -H 'Content-Type: application/json' \
  -d '{"description":"First paragraph of the description.\n\nSecond paragraph."}' >/dev/null

out=$(LIN_URL=$URL "$LIN" issue view ENG-3)
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
out=$(LIN_URL=$URL "$LIN" issue view OPS-99 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "view OPS-99: expected nonzero exit"
assert_contains "$out" "issue OPS-99 not found" "view unknown number message"
assert_contains "$out" "lin issue list" "view unknown ID names the fix"

set +e
out=$(LIN_URL=$URL "$LIN" issue view ZZZ-1 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "view ZZZ-1: expected nonzero exit"
assert_contains "$out" "issue ZZZ-1 not found" "view unknown team message"

set +e
out=$(LIN_URL=$URL "$LIN" issue view not-an-id 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "view not-an-id: expected nonzero exit"
assert_contains "$out" "not an issue ID" "view malformed ID message"

# --- --json parses with jq and resolves expand.team ---
title=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --json | jq -r '.items[0].title')
[ -n "$title" ] && [ "$title" != "null" ] || fail "list --json: .items[0].title empty"
key=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --json | jq -r '.items[0].expand.team.key')
[ "$key" = "ENG" ] || fail "list --json: expected expand.team.key ENG, got '$key'"

vtitle=$(LIN_URL=$URL "$LIN" issue view ENG-3 --json | jq -r '.title')
[ "$vtitle" = "Fix login flow" ] || fail "view --json: expected title roundtrip, got '$vtitle'"
vkey=$(LIN_URL=$URL "$LIN" issue view ENG-3 --json | jq -r '.expand.team.key')
[ "$vkey" = "ENG" ] || fail "view --json: expected expand.team.key ENG, got '$vkey'"

# --- --state filters; invalid state rejected ---
curl -sf -X PATCH "$URL/api/collections/issues/records/$ENG3_ID" \
  -H 'Content-Type: application/json' -d '{"state":"in-review"}' >/dev/null

out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --state in-review)
assert_contains "$out" "ENG-3" "state filter shows in-review issue"
assert_not_contains "$out" "ENG-1" "state filter hides todo issues"

set +e
out=$(LIN_URL=$URL "$LIN" issue list --state bogus 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "list --state bogus: expected nonzero exit"
assert_contains "$out" "unknown state 'bogus'" "invalid state message"

# --- --sort orders by priority; LIN_SORT sets the default ---
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue create -t "Server on fire" --priority 1)
assert_contains "$out" "Created ENG-4" "urgent issue created"
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue create -t "Tidy readme" --priority 4)
assert_contains "$out" "Created ENG-5" "low issue created"

out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --sort -priority)
assert_contains "$(printf '%s\n' "$out" | head -1)" "ENG-5" "sort -priority puts low (4) first"
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --sort priority)
assert_contains "$(printf '%s\n' "$out" | tail -1)" "ENG-5" "sort priority puts low (4) last"

out=$(LIN_URL=$URL LIN_TEAM=ENG LIN_SORT=-priority "$LIN" issue list)
assert_contains "$(printf '%s\n' "$out" | head -1)" "ENG-5" "LIN_SORT is the default sort"

set +e
out=$(LIN_URL=$URL "$LIN" issue list --sort title 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "list --sort title: expected nonzero exit"
assert_contains "$out" "unknown sort field 'title'" "invalid sort message"

# --- list output: glyphs and priority markers, aligned columns ---
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list)
assert_contains "$out" "○ todo" "list shows todo glyph"
assert_contains "$out" "◉ in-review" "list shows in-review glyph"
assert_contains "$out" "!!!" "list shows urgent marker"
assert_contains "$out" "·" "list shows low marker"
assert_contains "$out" "just now" "list shows relative dates"

# --- write path round-trip: create -> start -> update -> close ---
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue create -t "Roundtrip issue" --priority 3)
assert_contains "$out" "Created ENG-6: Roundtrip issue" "roundtrip create"

REPO="$DATA_DIR/repo"
git init -q -b main "$REPO"
git -C "$REPO" -c user.name=e2e -c user.email=e2e@example.com \
  commit -q --allow-empty -m init

out=$(cd "$REPO" && LIN_URL=$URL "$LIN_ABS" issue start ENG-6)
assert_contains "$out" "Started ENG-6" "start output"
assert_contains "$out" "Branch: eng-6-roundtrip-issue" "start prints branch name"
assert_contains "$out" "Created and switched to branch 'eng-6-roundtrip-issue'" "start creates branch"
branch=$(git -C "$REPO" branch --show-current)
[ "$branch" = "eng-6-roundtrip-issue" ] || fail "start: expected branch eng-6-roundtrip-issue, on '$branch'"

# starting again — ID inferred from the branch — switches instead of failing
out=$(cd "$REPO" && LIN_URL=$URL "$LIN_ABS" issue start)
assert_contains "$out" "Started ENG-6" "inferred start output"
assert_contains "$out" "Switched to existing branch 'eng-6-roundtrip-issue'" "start reuses branch"

# --- ID inference from the branch: view / update / close with no arg ---
out=$(cd "$REPO" && LIN_URL=$URL "$LIN_ABS" issue view)
assert_contains "$out" "ENG-6 Roundtrip issue" "inferred view header"
assert_contains "$out" "◐ in-progress" "start set in-progress"

out=$(cd "$REPO" && LIN_URL=$URL "$LIN_ABS" issue update --priority 1 --title "Roundtrip issue v2")
assert_contains "$out" "Updated ENG-6" "inferred update output"
out=$(LIN_URL=$URL "$LIN" issue view ENG-6)
assert_contains "$out" "ENG-6 Roundtrip issue v2" "update changed title"
assert_contains "$out" "Priority:  urgent" "update changed priority"

out=$(cd "$REPO" && LIN_URL=$URL "$LIN_ABS" issue close)
assert_contains "$out" "Closed ENG-6" "inferred close output"
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --state done)
assert_contains "$out" "ENG-6" "closed issue listed as done"
assert_contains "$out" "● done" "list shows done glyph"

# inference fails helpfully off a conventional branch
git -C "$REPO" switch -q -c not-an-issue-branch
set +e
out=$(cd "$REPO" && LIN_URL=$URL "$LIN_ABS" issue view 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "view on non-issue branch: expected nonzero exit"
assert_contains "$out" "doesn't look like eng-123-" "inference failure names the convention"

# --- update validation: no flags, bad state ---
set +e
out=$(LIN_URL=$URL "$LIN" issue update ENG-6 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "update with no flags: expected nonzero exit"
assert_contains "$out" "nothing to update" "update requires a flag"

set +e
out=$(LIN_URL=$URL "$LIN" issue update ENG-6 --state bogus 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "update --state bogus: expected nonzero exit"
assert_contains "$out" "unknown state 'bogus'" "update validates state"

# --- unknown IDs: update / close exit nonzero ---
set +e
out=$(LIN_URL=$URL "$LIN" issue update ENG-99 --priority 2 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "update ENG-99: expected nonzero exit"
assert_contains "$out" "issue ENG-99 not found" "update unknown ID message"

set +e
out=$(LIN_URL=$URL "$LIN" issue close ZZZ-9 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "close ZZZ-9: expected nonzero exit"
assert_contains "$out" "issue ZZZ-9 not found" "close unknown ID message"

# --- delete: declined without --force, explicit ID required, --force deletes ---
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue create -t "Delete me")
assert_contains "$out" "Created ENG-7" "delete target created"

out=$(printf 'n\n' | LIN_URL=$URL "$LIN" issue delete ENG-7)
assert_contains "$out" "delete ENG-7? [y/N]" "delete prompts"
assert_contains "$out" "Aborted." "delete declined"
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list)
assert_contains "$out" "ENG-7" "declined delete keeps the issue"

set +e
out=$(LIN_URL=$URL "$LIN" issue delete 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "delete without ID: expected nonzero exit"
assert_contains "$out" "lin issue delete KEY-123" "delete requires explicit ID"

out=$(LIN_URL=$URL "$LIN" issue delete ENG-7 --force)
assert_contains "$out" "Deleted ENG-7" "forced delete output"
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list)
assert_not_contains "$out" "ENG-7" "forced delete removed the issue"

# --- members: add + list ---
out=$(LIN_URL=$URL "$LIN" member add -n bryan -e bryan@example.com)
assert_contains "$out" "Added member bryan" "member add output"
out=$(LIN_URL=$URL "$LIN" member add -n alice)
assert_contains "$out" "Added member alice" "member add without email"
out=$(LIN_URL=$URL "$LIN" member list)
assert_contains "$out" "bryan" "member list has bryan"
assert_contains "$out" "bryan@example.com" "member list shows email"
assert_contains "$out" "alice" "member list has alice"

# --- --assignee on create; assignee in list and view ---
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue create -t "Assigned issue" --assignee bryan)
assert_contains "$out" "Created ENG-7: Assigned issue" "assigned create output"
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list)
assert_contains "$out" "bryan" "list shows assignee column"
out=$(LIN_URL=$URL "$LIN" issue view ENG-7)
assert_contains "$out" "Assignee:  bryan" "view shows assignee"
out=$(LIN_URL=$URL "$LIN" issue view ENG-6)
assert_contains "$out" "Assignee:  none" "view shows unassigned as none"

# --- --assignee filter on list ---
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --assignee bryan)
assert_contains "$out" "ENG-7" "assignee filter shows assigned issue"
assert_not_contains "$out" "ENG-6" "assignee filter hides unassigned issues"

# --- --assignee on update ---
out=$(LIN_URL=$URL "$LIN" issue update ENG-6 --assignee alice)
assert_contains "$out" "Updated ENG-6" "update --assignee output"
out=$(LIN_URL=$URL "$LIN" issue view ENG-6)
assert_contains "$out" "Assignee:  alice" "update set assignee"
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --assignee alice)
assert_contains "$out" "ENG-6" "assignee filter finds updated issue"
assert_not_contains "$out" "ENG-7" "assignee filter scoped to alice"

# --- unknown member errors and names the fix ---
set +e
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue create -t "Nope" --assignee nobody 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "create --assignee nobody: expected nonzero exit"
assert_contains "$out" "no member named 'nobody'" "unknown member message"
assert_contains "$out" "lin member list" "unknown member names the fix"

set +e
out=$(LIN_URL=$URL "$LIN" issue update ENG-6 --assignee nobody 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "update --assignee nobody: expected nonzero exit"
assert_contains "$out" "no member named 'nobody'" "update unknown member message"

set +e
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --assignee nobody 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "list --assignee nobody: expected nonzero exit"
assert_contains "$out" "no member named 'nobody'" "list unknown member message"

# --- --json resolves expand.assignee ---
aname=$(LIN_URL=$URL "$LIN" issue view ENG-7 --json | jq -r '.expand.assignee.name')
[ "$aname" = "bryan" ] || fail "view --json: expected expand.assignee.name bryan, got '$aname'"
aname=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --assignee bryan --json | \
  jq -r '.items[0].expand.assignee.name')
[ "$aname" = "bryan" ] || fail "list --json: expected expand.assignee.name bryan, got '$aname'"

# --- comment add authored by config 'me'; shown in view with relative date ---
printf 'url = "%s"\nteam = "ENG"\nme = "bryan"\n' "$URL" > "$WORK/.lin.toml"
out=$(cd "$WORK" && env -u LIN_URL -u LIN_TEAM HOME="$FAKEHOME" "$LIN_ABS" issue comment ENG-7 -b "Looks good to me")
assert_contains "$out" "Commented on ENG-7" "comment add output"

out=$(LIN_URL=$URL "$LIN" issue view ENG-7)
assert_contains "$out" "Comments:" "view has comments section"
assert_contains "$out" "bryan (just now)" "view comment author and relative date"
assert_contains "$out" "Looks good to me" "view comment body"

# --- comment list without -b ---
out=$(LIN_URL=$URL "$LIN" issue comment ENG-7)
assert_contains "$out" "bryan (just now)" "comment list author"
assert_contains "$out" "Looks good to me" "comment list body"

# --- authorless comments: me unset, and me naming no member ---
out=$(LIN_URL=$URL "$LIN" issue comment ENG-7 -b "Anonymous note")
assert_contains "$out" "Commented on ENG-7" "authorless comment (me unset) accepted"

printf 'url = "%s"\nteam = "ENG"\nme = "ghost"\n' "$URL" > "$WORK/.lin.toml"
out=$(cd "$WORK" && env -u LIN_URL -u LIN_TEAM HOME="$FAKEHOME" "$LIN_ABS" issue comment ENG-7 -b "Ghost note")
assert_contains "$out" "Commented on ENG-7" "authorless comment (me unmatched) accepted"

out=$(LIN_URL=$URL "$LIN" issue comment ENG-7)
assert_contains "$out" "anon (just now)" "authorless comments render as anon"
assert_contains "$out" "Anonymous note" "authorless body listed"
assert_contains "$out" "Ghost note" "unmatched-me body listed"

# --- comment ID inference from the git branch ---
git -C "$REPO" switch -q eng-6-roundtrip-issue
out=$(cd "$REPO" && LIN_URL=$URL "$LIN_ABS" issue comment -b "From the branch")
assert_contains "$out" "Commented on ENG-6" "comment infers ID from branch"
out=$(cd "$REPO" && LIN_URL=$URL "$LIN_ABS" issue comment)
assert_contains "$out" "From the branch" "inferred comment list"

# --- no comments ---
out=$(LIN_URL=$URL "$LIN" issue comment ENG-1)
assert_contains "$out" "No comments." "empty comment list message"

# --- projects: create + list ---
out=$(LIN_URL=$URL "$LIN" project create -n "Auth Revamp" -d "Rework the login flow" --team ENG)
assert_contains "$out" "Created project Auth Revamp (planned)" "project create output"
out=$(LIN_URL=$URL "$LIN" project create -n "Perf Push" --status started)
assert_contains "$out" "Created project Perf Push (started)" "project create with --status"
out=$(LIN_URL=$URL "$LIN" project list)
assert_contains "$out" "Auth Revamp" "project list has Auth Revamp"
assert_contains "$out" "planned" "project list shows status"
assert_contains "$out" "ENG" "project list shows team"
assert_contains "$out" "workspace" "project list shows workspace scope"

set +e
out=$(LIN_URL=$URL "$LIN" project create -n "Bad" --status bogus 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "project create --status bogus: expected nonzero exit"
assert_contains "$out" "unknown status 'bogus'" "invalid project status message"

# --- labels: create + list ---
out=$(LIN_URL=$URL "$LIN" label create -n bug -c "#ff0000" --team ENG)
assert_contains "$out" "Created label bug" "label create output"
out=$(LIN_URL=$URL "$LIN" label create -n chore)
assert_contains "$out" "Created label chore" "label create without color/team"
out=$(LIN_URL=$URL "$LIN" label list)
assert_contains "$out" "bug" "label list has bug"
assert_contains "$out" "#ff0000" "label list shows color"
assert_contains "$out" "chore" "label list has chore"
assert_contains "$out" "workspace" "label list shows workspace scope"

# --- issue created with labels + project ---
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue create -t "Labeled login fix" --label bug --label chore --project "Auth Revamp")
assert_contains "$out" "Created ENG-8: Labeled login fix" "labeled create output"

out=$(LIN_URL=$URL "$LIN" issue view ENG-8)
assert_contains "$out" "Project:   Auth Revamp" "view shows project"
assert_contains "$out" "Labels:    bug, chore" "view shows labels"
out=$(LIN_URL=$URL "$LIN" issue view ENG-6)
assert_contains "$out" "Project:   none" "view shows unset project as none"
assert_contains "$out" "Labels:    none" "view shows unset labels as none"

# --- --label / --project filter issue list ---
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --label bug)
assert_contains "$out" "ENG-8" "label filter shows labeled issue"
assert_not_contains "$out" "ENG-6" "label filter hides unlabeled issues"
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --project "Auth Revamp")
assert_contains "$out" "ENG-8" "project filter shows project issue"
assert_not_contains "$out" "ENG-6" "project filter hides other issues"

# --- --label / --project on update ---
out=$(LIN_URL=$URL "$LIN" issue update ENG-6 --project "Perf Push" --label chore)
assert_contains "$out" "Updated ENG-6" "update --project/--label output"
out=$(LIN_URL=$URL "$LIN" issue view ENG-6)
assert_contains "$out" "Project:   Perf Push" "update set project"
assert_contains "$out" "Labels:    chore" "update set labels"
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --project "Perf Push")
assert_contains "$out" "ENG-6" "project filter finds updated issue"
assert_not_contains "$out" "ENG-8" "project filter scoped to Perf Push"
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --label chore)
assert_contains "$out" "ENG-6" "label filter finds updated issue"
assert_contains "$out" "ENG-8" "label filter matches multi-relation membership"

# --- project view lists its issues ---
out=$(LIN_URL=$URL "$LIN" project view "Auth Revamp")
assert_contains "$out" "Name:    Auth Revamp" "project view name"
assert_contains "$out" "Status:  planned" "project view status"
assert_contains "$out" "Team:    ENG" "project view team"
assert_contains "$out" "Rework the login flow" "project view description"
assert_contains "$out" "Issues:" "project view issues section"
assert_contains "$out" "ENG-8" "project view lists its issue"
assert_contains "$out" "Labeled login fix" "project view issue title"
assert_not_contains "$out" "ENG-6" "project view scoped to its issues"

# --- --search matches title substrings ---
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --search "abeled login")
assert_contains "$out" "ENG-8" "search matches title substring"
assert_not_contains "$out" "ENG-6" "search hides non-matching titles"
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --search "zz-no-such-title")
assert_not_contains "$out" "ENG-" "non-matching search yields no issues"

# --- unknown label / project names error with the fix ---
set +e
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue create -t "Nope" --label nosuch 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "create --label nosuch: expected nonzero exit"
assert_contains "$out" "no label named 'nosuch'" "unknown label message"
assert_contains "$out" "lin label list" "unknown label names the fix"

set +e
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue create -t "Nope" --project nosuch 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "create --project nosuch: expected nonzero exit"
assert_contains "$out" "no project named 'nosuch'" "unknown project message"
assert_contains "$out" "lin project list" "unknown project names the fix"

set +e
out=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --label nosuch 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "list --label nosuch: expected nonzero exit"
assert_contains "$out" "no label named 'nosuch'" "list unknown label message"

set +e
out=$(LIN_URL=$URL "$LIN" project view nosuch 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || fail "project view nosuch: expected nonzero exit"
assert_contains "$out" "no project named 'nosuch'" "project view unknown name message"

# --- --json resolves expand.project and expand.labels ---
pname=$(LIN_URL=$URL "$LIN" issue view ENG-8 --json | jq -r '.expand.project.name')
[ "$pname" = "Auth Revamp" ] || fail "view --json: expected expand.project.name Auth Revamp, got '$pname'"
lname=$(LIN_URL=$URL "$LIN" issue view ENG-8 --json | jq -r '.expand.labels[0].name')
[ "$lname" = "bug" ] || fail "view --json: expected expand.labels[0].name bug, got '$lname'"
pname=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --label bug --json | \
  jq -r '.items[0].expand.project.name')
[ "$pname" = "Auth Revamp" ] || fail "list --json: expected expand.project.name Auth Revamp, got '$pname'"
lname=$(LIN_URL=$URL LIN_TEAM=ENG "$LIN" issue list --label bug --json | \
  jq -r '.items[0].expand.labels[0].name')
[ "$lname" = "bug" ] || fail "list --json: expected expand.labels[0].name bug, got '$lname'"

# --- help output ---
out=$("$LIN" --help)
assert_contains "$out" "Usage:" "lin --help"
assert_contains "$out" "lin team" "lin --help mentions team"
assert_contains "$out" "lin member" "lin --help mentions member"
assert_contains "$out" "lin project" "lin --help mentions project"
assert_contains "$out" "lin label" "lin --help mentions label"
assert_contains "$out" "lin config" "lin --help mentions config"
out=$("$LIN" issue --help)
assert_contains "$out" "Usage:" "lin issue --help"
assert_contains "$out" "lin issue update" "issue --help mentions update"
assert_contains "$out" "lin issue close" "issue --help mentions close"
assert_contains "$out" "lin issue start" "issue --help mentions start"
assert_contains "$out" "lin issue delete" "issue --help mentions delete"
assert_contains "$out" "lin issue comment" "issue --help mentions comment"
assert_contains "$out" "--assignee" "issue --help mentions --assignee"
assert_contains "$out" "--label" "issue --help mentions --label"
assert_contains "$out" "--project" "issue --help mentions --project"
assert_contains "$out" "--search" "issue --help mentions --search"
out=$("$LIN" member --help)
assert_contains "$out" "Usage:" "lin member --help"
assert_contains "$out" "lin member add" "member --help mentions add"
out=$("$LIN" team --help)
assert_contains "$out" "Usage:" "lin team --help"
out=$("$LIN" project --help)
assert_contains "$out" "Usage:" "lin project --help"
assert_contains "$out" "lin project view" "project --help mentions view"
out=$("$LIN" label --help)
assert_contains "$out" "Usage:" "lin label --help"
assert_contains "$out" "lin label create" "label --help mentions create"
out=$("$LIN" config --help)
assert_contains "$out" "Usage:" "lin config --help"

echo "e2e: all assertions passed"
