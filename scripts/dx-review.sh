#!/usr/bin/env bash
# Parallel developer-experience review: N agents, N isolated lll servers, N
# throwaway git repos, one shared task, one aggregated report.
#
# The point is to measure onboarding and everyday use the way a stranger meets
# them, not the way an author remembers them. Findings only appear when the
# agent has no prior knowledge of the tool, so every environment is sealed:
# its own server, its own HOME, its own repo, its own credentials.
#
# Agent-runtime agnostic. Without --agent-cmd the script provisions the
# environments, prints a manifest and stops, so any harness (or a person) can
# drive them. With --agent-cmd it runs that command once per environment in
# parallel and aggregates whatever the agents wrote back.
#
# Usage:
#   scripts/dx-review.sh -n 8
#   scripts/dx-review.sh -n 8 --agent-cmd 'some-agent --prompt-file {brief}'
#   scripts/dx-review.sh -n 3 --keep          # leave the servers running
#
# Placeholders in --agent-cmd, substituted per agent:
#   {brief}   absolute path to that agent's task file
#   {dir}     that agent's environment root
#   {report}  absolute path the agent must write its JSON report to
#   {n}       agent number
#
# Exit code is 0 when every agent reported success, 1 otherwise.
set -uo pipefail

N=6
AGENT_CMD=""
KEEP=0
TASK_FILE=""
ROOT=""
REPORT_ONLY=0

usage() {
  sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    -n|--agents)     N=$2; shift 2 ;;
    --agent-cmd)     AGENT_CMD=$2; shift 2 ;;
    --task)          TASK_FILE=$2; shift 2 ;;
    --root)          ROOT=$2; shift 2 ;;
    --keep)          KEEP=1; shift ;;
    --report-only)   REPORT_ONLY=1; shift ;;
    -h|--help)       usage 0 ;;
    *) echo "unknown argument: $1" >&2; usage 1 ;;
  esac
done

case "$N" in ''|*[!0-9]*) echo "-n takes a number, got '$N'" >&2; exit 1 ;; esac
[ "$N" -ge 1 ] || { echo "-n must be at least 1" >&2; exit 1; }

cd "$(dirname "$0")/.." || exit 1
REPO=$(pwd)
. scripts/lib.sh          # free_port, wait_ok

# --report-only re-reads a previous run's directory. It provisions nothing and
# kills nothing, so a run driven by some other harness can be aggregated here.
if [ "$REPORT_ONLY" -eq 1 ]; then
  [ -n "$ROOT" ] || { echo "--report-only needs --root <dir>" >&2; exit 1; }
  [ -d "$ROOT" ] || { echo "no such directory: $ROOT" >&2; exit 1; }
  N=$(find "$ROOT" -maxdepth 1 -name 'agent-*' -type d | wc -l | tr -d ' ')
  [ "$N" -gt 0 ] || { echo "no agent-* directories in $ROOT" >&2; exit 1; }
  exec python3 "$REPO/scripts/dx-aggregate.py" "$ROOT" "$N"
fi

command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

# Each server is a full lll process. Measured at ~50 MB resident, so the
# ceiling is memory, not CPU; 50 fits comfortably in 32 GB.
echo "dx-review: $N agents"

LLL="$REPO/target/.lisette/bin/lll"
if [ ! -x "$LLL" ]; then
  echo "building lll..."
  bash scripts/lis-typedefs-workaround.sh >/dev/null 2>&1
  lis build >/dev/null || { echo "build failed" >&2; exit 1; }
fi

[ -n "$ROOT" ] || ROOT=$(mktemp -d "${TMPDIR:-/tmp}/lll-dx.XXXXXX")
mkdir -p "$ROOT"
PIDS_FILE="$ROOT/servers.pids"
: > "$PIDS_FILE"

teardown() {
  [ "$KEEP" -eq 1 ] && { echo; echo "servers left running; stop them with:"; echo "  kill \$(cat $PIDS_FILE)"; echo "  rm -rf $ROOT"; return 0; }
  while read -r pid; do [ -n "$pid" ] && kill "$pid" 2>/dev/null; done < "$PIDS_FILE"
  sleep 1
  while read -r pid; do [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null; done < "$PIDS_FILE"
}
trap teardown EXIT

# ---------------------------------------------------------------- the task
# One task that reaches most of what lll does. Ordered so each step depends on
# the last, which is what makes a stuck agent's report legible: the step it
# stopped at names the surface that failed.
default_task() {
  cat <<'TASK'
## Your task

Work through all of it. If a step is impossible, record why and continue to
the next one; a partial run is a useful result, a fabricated one is not.

1.  Get yourself authenticated against the server, as a member named `AGENT`
    with email `AGENT@example.com`.
2.  Attach this git repository to a team so issues get created in it.
3.  Create a project called "Checkout rewrite".
4.  Create two labels: `bug` and `chore`.
5.  Create three issues. At least one must carry a priority, one the `bug`
    label, and one must belong to the project from step 3.
6.  List the issues and confirm all three are there.
7.  Begin work on one issue so that a git branch is created for it. Confirm
    you are on that branch.
8.  While on that branch, and WITHOUT naming the issue explicitly, view the
    issue and add a comment to it.
9.  Assign that issue to yourself and move it to a review state.
10. Close it.
11. Search for one of your issues by a word in its title.
12. Add a colleague named `COLLEAGUE` who can log in with the email
    `COLLEAGUE@example.com`, and record the exact commands they would run.
13. Print the URL of the web board.
14. Produce machine-readable output of the issue list.
TASK
}

# ------------------------------------------------------------ provisioning
manifest="$ROOT/manifest.tsv"
printf 'agent\tdir\tapi\tboard\tbrief\treport\n' > "$manifest"

for i in $(seq 1 "$N"); do
  DIR="$ROOT/agent-$i"
  mkdir -p "$DIR/home" "$DIR/repo" "$DIR/pb_data"

  # A real git repository, NOT a worktree of this checkout. A worktree would
  # inherit the committed .lll.toml (pointing every agent at the real team and
  # the real server) and would write their branches into these refs. The
  # branch-creating verbs still need a repo, so each agent gets a fresh one.
  git -C "$DIR/repo" init -q
  git -C "$DIR/repo" config user.email "agent$i@example.com"
  git -C "$DIR/repo" config user.name "agent$i"
  printf '# scratch\n' > "$DIR/repo/README.md"
  git -C "$DIR/repo" add -A
  git -C "$DIR/repo" -c commit.gpgsign=false commit -qm "initial" 2>/dev/null

  DB=$(free_port 20000 39999)
  WEB=$(free_port 40000 59999)
  ADMIN_EMAIL="admin$i@local.dev"
  ADMIN_PASS="admin-pw-$i-$RANDOM"

  # USER=deployer on purpose: `lll up` seeds a member from $USER on first
  # boot, so booting as the agent would hand it the account that onboarding is
  # supposed to be about obtaining. The agent must arrive a stranger.
  ( cd "$REPO" && exec env -i PATH="$PATH" HOME="$DIR/home" USER=deployer \
      LLL_URL="http://127.0.0.1:$DB" LLL_TEAM=ENG \
      LLL_ADMIN_EMAIL="$ADMIN_EMAIL" LLL_ADMIN_PASSWORD="$ADMIN_PASS" \
      LLL_BOARD_TOKEN="board-tok-$i" \
      "$LLL" up --port "$WEB" --pb-dir "$DIR/pb_data" --no-open ) \
    > "$DIR/server.log" 2>&1 &
  echo "$!" >> "$PIDS_FILE"

  # The agent's own HOME, empty of any config, is what makes step 1 real.
  rm -rf "$DIR/agenthome"; mkdir -p "$DIR/agenthome"

  BRIEF="$DIR/BRIEF.md"
  REPORT="$DIR/report.json"
  {
    cat <<EOF
# lll: developer-experience review

You are setting up a machine to use \`lll\`, an issue tracker with a
command-line interface and a web board, against a server someone else already
deployed. You have never used it before.

## Environment

Run every command with this environment:

    export HOME=$DIR/agenthome
    export PATH=$(dirname "$LLL"):\$PATH
    cd $DIR/repo

The server is at        http://127.0.0.1:$DB
The board is at         http://127.0.0.1:$WEB

You deployed that server, so you hold its administrator credentials:

    LLL_ADMIN_EMAIL=$ADMIN_EMAIL
    LLL_ADMIN_PASSWORD=$ADMIN_PASS

EOF
    if [ -n "$TASK_FILE" ]; then cat "$TASK_FILE"; else default_task; fi
    cat <<EOF

Wherever the task says \`AGENT\`, use \`agent$i\`. Wherever it says
\`COLLEAGUE\`, use \`colleague$i\`.

## Rules

1.  This is a black-box usability review. Read no source code. Do not open,
    search or list anything under $REPO. Your only sources are the \`lll\`
    binary, its \`--help\` output, and the messages it prints.
2.  Try what you would naturally try FIRST, before consulting \`--help\`.
    Your untrained instinct is the measurement. When a guess fails, record it
    and try the next one.
3.  Count every \`lll\` command you run and whether it worked.
4.  Verify before claiming success. Run the command and read its output. Do
    not report a step as done because it should have worked.

## Report

Write a JSON object to this exact path, and nothing else to it:

    $REPORT

Use these keys:

    {
      "agent": $i,
      "completed_steps": [1, 2, 3],
      "failed_steps": [{"step": 7, "why": "...", "commands_tried": ["..."]}],
      "total_commands": 0,
      "wasted_commands": 0,
      "consulted_help": false,
      "first_command": "the very first lll command you ran, verbatim",
      "misleading_messages": ["quote any message that sent you somewhere useless"],
      "helpful_messages": ["quote any message that told you exactly what to run next"],
      "surprises": ["anything that did not work the way you assumed"],
      "worst_moment": "the single biggest obstacle, in one sentence"
    }

A failed step is a valid and useful result. Report it honestly.
EOF
  } > "$BRIEF"

  printf '%s\t%s\thttp://127.0.0.1:%s\thttp://127.0.0.1:%s/?board_token=board-tok-%s\t%s\t%s\n' \
    "$i" "$DIR" "$DB" "$WEB" "$i" "$BRIEF" "$REPORT" >> "$manifest"
done

# Wait for every server, so no agent meets a half-open port.
echo -n "waiting for $N servers"
ready=0
for i in $(seq 1 "$N"); do
  DB=$(awk -v n="$i" -F'\t' '$1==n {sub("http://127.0.0.1:","",$3); print $3}' "$manifest")
  if wait_ok "http://127.0.0.1:$DB/api/health" 150 >/dev/null 2>&1; then
    ready=$((ready + 1)); echo -n "."
  else
    echo; echo "server $i failed to start; see $ROOT/agent-$i/server.log" >&2
  fi
done
echo " $ready/$N up"
[ "$ready" -eq "$N" ] || { echo "not every server started; aborting" >&2; exit 1; }

echo "environments: $ROOT"
echo "manifest:     $manifest"

if [ -z "$AGENT_CMD" ]; then
  echo
  echo "No --agent-cmd given, so nothing was run. Each agent's task file:"
  awk -F'\t' 'NR>1 {printf "  agent %s  %s\n", $1, $5}' "$manifest"
  echo
  echo "Drive them with any runtime, then aggregate with:"
  echo "  scripts/dx-review.sh --root $ROOT --report-only"
  KEEP=1
  exit 0
fi

# ---------------------------------------------------------------- the runs
echo "running $N agents in parallel"
for i in $(seq 1 "$N"); do
  DIR="$ROOT/agent-$i"
  cmd=${AGENT_CMD//\{brief\}/$DIR/BRIEF.md}
  cmd=${cmd//\{dir\}/$DIR}
  cmd=${cmd//\{report\}/$DIR/report.json}
  cmd=${cmd//\{n\}/$i}
  ( cd "$DIR/repo" && eval "$cmd" ) > "$DIR/agent.log" 2>&1 &
done
wait
echo "all agents finished"

# ------------------------------------------------------------- aggregation
python3 "$REPO/scripts/dx-aggregate.py" "$ROOT" "$N"
rc=$?
echo
echo "raw reports and logs: $ROOT"
exit $rc
