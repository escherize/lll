#!/usr/bin/env bash
# Synthetic, busy lll 1.0.0 board for the landing page: several teams, humans
# and one bot per harness, work in every column. Nothing here is real data.
set -euo pipefail
D=/tmp/landing-demo
LLL=/opt/homebrew/bin/lll
[ -f "$D/run/pid" ] && kill "$(cat "$D/run/pid")" 2>/dev/null || true
sleep 1
rm -rf "$D/run"; mkdir -p "$D/run/home" "$D/run/work"
export HOME="$D/run/home" LLL_CONFIG_HOME="$D/run/home/.config"
unset LLL_TOKEN LLL_URL XDG_CONFIG_HOME
export USER=bryan LLL_TEAM=ENG
export LLL_ADMIN_EMAIL=admin@local.dev LLL_ADMIN_PASSWORD=admin-local-123
export LLL_BOARD_TOKEN=landing-demo
cd "$D/run/work"
"$LLL" up --no-open --port 48100 </dev/null >"$D/run/up.log" 2>&1 &
echo $! >"$D/run/pid"
for _ in $(seq 1 200); do grep -q 'board  login' "$D/run/up.log" 2>/dev/null && break; sleep 0.1; done
grep -q 'board  login' "$D/run/up.log" || { tail -20 "$D/run/up.log"; exit 1; }

q() { "$LLL" "$@" >/dev/null; }
key() { "$LLL" issue create "$@" --json | python3 -c 'import json,sys;print(json.load(sys.stdin)["key"])'; }

q team rename ENG -n "Platform"
q team create WEB -n "Web board"
q team create OPS -n "Ops"
q team create DOCS -n "Docs"
for l in bug feature chore docs perf security cli agents; do q label create "$l" || true; done
q project create "1.0 launch" || true
q project create "Realtime" || true

for b in claude codex pi opencode ci; do "$LLL" bot create "bot-$b" --env >"$D/run/$b.env"; done
as() { local b=$1 agent=$2; shift 2; ( set -a; . "$D/run/$b.env"; set +a; "$LLL" "$@" --agent "$agent" >/dev/null ); }

# done: the long tail
for t in "Walking skeleton: create and list issues" "Teams, keys and ENG-123 identifiers" "Live board over one SSE stream" \
         "Drag cards between states" "Search that is a URL" "Bot members with their own tokens" "Claims that release on close" \
         "Exit codes as a contract" "Scoped access per team" "Webhooks with a shared secret" "NDJSON watch stream" \
         "Findings recorded against file paths"; do
  key "$t" --state done --priority medium --label feature >/dev/null
done
key "Drop the old export path" --state cancelled --label chore >/dev/null

# backlog
key "Keyboard shortcuts on the board" --state backlog --priority low --label feature >/dev/null
key "Project overview pages" --state backlog --priority low --label feature --project "1.0 launch" >/dev/null
key "OS keychain for saved tokens" --state backlog --priority medium --label security >/dev/null
key "Mobile layout for the issue page" --state backlog --priority low --label feature >/dev/null

# todo
t1=$(key "Vendor datastar so the board works offline" --priority high --label chore)
key "Per-reader cursor on team notices" --priority medium --label agents >/dev/null
key "Board loads only the visible columns" --priority medium --label perf >/dev/null
key "Invite links that carry team scope" --priority high --label security >/dev/null
key "Typed close evidence: --reason and --evidence" --priority low --label cli >/dev/null

# in progress, claimed by agents
p1=$(key "Retry loses the upload on slow links" --priority urgent --label bug --state in-progress)
p2=$(key "Stream backpressure on slow watchers" --priority high --label perf --state in-progress --project Realtime)
p3=$(key "Board columns collapse on narrow windows" --priority medium --label bug --state in-progress)
p4=$(key "Release notes for 1.0" --priority medium --label docs --state in-progress --project "1.0 launch")
as codex codex.ci-runner issue claim "$p1"
as codex codex.ci-runner issue comment "$p1" "reproduced on a 64 kbit link; the retry drops the multipart body"
as pi pi.homelab issue claim "$p2"
as claude claude-code.laptop issue claim "$p3"
as claude claude-code.laptop issue claim "$p4"

# in review
r1=$(key "Second boot fails with no team configured" --priority high --label bug --state in-review)
r2=$(key "Token rotation for bot members" --priority high --label security --state in-review)
r3=$(key "Comment events on watch and webhooks" --priority medium --label agents --state in-review --project Realtime)
as opencode opencode.desk issue claim "$r1"
as opencode opencode.desk issue comment "$r1" "fix up: lll up now asks for a team instead of exiting"
as claude claude-code.laptop issue claim "$r2"
as pi pi.homelab issue claim "$r3"

# a few issues on the other teams so the sidebar is real
for t in WEB OPS DOCS; do key "First issue on $t" --team "$t" --priority low >/dev/null; done

sed -n 's|.*board  login \(http://[^ ]*\).*|\1|p' "$D/run/up.log" | head -1
