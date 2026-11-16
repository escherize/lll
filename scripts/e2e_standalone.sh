#!/usr/bin/env bash
# e2e: the suites that take only the built binary. Each boots whatever server
# it needs, so none depends on the board e2e.sh drives or on another suite.
# That independence is what lets CI run them on separate runners (LLL-805):
# --shard I/N takes every Nth suite starting at the Ith.
# Standalone, also invoked by e2e.sh.
set -euo pipefail
LIN=""
SHARD="${E2E_SHARD:-1/1}"
LIST=0
usage() { echo "usage: bash scripts/e2e_standalone.sh [--prebuilt BINARY] [--shard I/N] [--list]" >&2; exit 2; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --prebuilt)
      [ "$#" -ge 2 ] && [ -x "$2" ] || { echo "--prebuilt requires an executable" >&2; exit 2; }
      LIN=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$2")
      shift 2 ;;
    --shard) [ "$#" -ge 2 ] || usage; SHARD=$2; shift 2 ;;
    --list) LIST=1; shift ;;
    *) usage ;;
  esac
done
case "$SHARD" in
  [1-9]/[1-9]) ;;
  *) echo "--shard wants I/N with 1 <= I <= N <= 9, got '$SHARD'" >&2; exit 2 ;;
esac
SHARD_I=${SHARD%/*}
SHARD_N=${SHARD#*/}
[ "$SHARD_I" -le "$SHARD_N" ] || { echo "--shard wants I/N with 1 <= I <= N <= 9, got '$SHARD'" >&2; exit 2; }

# One suite per line: the script, then any arguments that follow the binary.
# Add a suite here when it takes only the binary; one that also needs the
# shared board's URL belongs in e2e.sh.
SUITES=(
  "test_response_reads.py"
  # lll search: full text over issues, comments and docs, ranked, with context (LLL-96)
  "test_search_team.py"
  # the 1.0 CLI contract: exit codes, list envelope, issue JSON, time flags (LLL-645)
  "test_cli_contract.py"
  "test_watch_activity.py"
  # member invite --team: one team over the API and the board
  "test_team_scope.py"
  "test_team_roles.py --browser"
  # who made or owns a record is the server's word, not a member's (LLL-681)
  "test_identity_fields.py"
  "test_board_head.py"
  # an archived team is read-only on the server, every collection classified (LLL-660)
  "test_archived_guard.py"
  # a member token in the board cookie scopes pages, search and the stream (LLL-545)
  "test_board_viewer_scope.py"
  # the board reads as its viewer: team links, the link-token route, one access check (LLL-658)
  "test_viewer_reads.py"
  # every registered non-GET board route refuses another origin (LLL-630)
  "test_board_origin.py"
  "test_access_agent_prompt.py"
  "test_access_agent_prompt.py lan"
  # invite create + /join/<code>: single-use, bounded by the creator (LLL-544)
  "test_invites.py"
  # the real invites migration on a board with names differing only by case
  "test_name_index_migration.py"
  "test_board_add_bot.py"
  # the members roster a team-scoped member sees: API, CLI, board (LLL-551)
  "test_roster_scope.py"
  # references stay in one team; relation filters cannot read hidden rows; team key rule (LLL-631, 634, 628)
  "test_team_refs.py"
  # an older CLI than its server says so once a day, on stderr only (LLL-607)
  "test_version_skew.py"
  "test_whoami_malformed.py"
  # lll upgrade picks its command from how lll was installed (LLL-608)
  "test_upgrade.py"
  # a Homebrew lll older than its server updates itself in the background (LLL-721)
  "test_auto_update.py"
  "test_completion_commands.py"
  "test_flag_policy.py"
  "test_usage_exit.py"
  "test_password_tty.py"
  "test_write_json.py"
  "test_help_exit.py"
  "test_help_ticket_keys.py"
  "test_doc_examples.py"
  "test_views_refresh.py"
  "test_config_permissions.py"
  "test_whoami_recovery.py"
  "test_new_cli_login.py"
  "test_shared_reopen.py"
  "test_agenda_scope.py"
  "test_collection_pagination.py"
  "test_bulk_reads.py"
  "test_issue_view_reads.py"
  "test_move_pagination.py"
  "test_config_isolation.py"
)
SELECTED=()
for i in "${!SUITES[@]}"; do
  [ $((i % SHARD_N)) -eq $((SHARD_I - 1)) ] && SELECTED+=("${SUITES[$i]}")
done
if [ "$LIST" = 1 ]; then
  printf '%s\n' "${SELECTED[@]}"
  exit 0
fi

. "$(dirname "$0")/lib.sh"   # Resolve user paths before this changes directory.
e2e_begin
cleanup() { # exit-status
  e2e_diagnose "$1"
  e2e_end
}
e2e_trap_cleanup cleanup

if [ -z "$LIN" ]; then
  (cd "$REPO_ROOT" && lis build >/dev/null)
  LIN="$REPO_ROOT/target/.lisette/bin/lll"
fi
# After the build, for the reason lib.sh gives: the compiler caches live under
# the real HOME.
e2e_pin_home

for suite in "${SELECTED[@]}"; do
  started=$SECONDS
  read -r -a words <<< "$suite"
  python3 "$REPO_ROOT/scripts/${words[0]}" "$LIN" "${words[@]:1}"
  echo "standalone: $suite ($((SECONDS - started))s)"
done
echo "e2e_standalone: shard $SHARD passed (${#SELECTED[@]} suites)"
