#!/usr/bin/env bash
# TASK-79: a board with something on it, in one command.
#
# Every "let me poke at the board" until now started from an empty database:
# no issues, no projects, no labels, so the board renders its empty state and
# nothing about layout, sorting, overflow or the state columns can be judged.
# TASK-46 built a .private -> live-lll importer that loaded 47 tasks, and that
# one run immediately found two shipping bugs (a UTF-8 panic and a 5000-char
# description cap). The importer was disposable and survives in no commit, so
# the next person pays to rebuild it. This is the checked-in replacement.
#
# It is deliberately NOT the .private importer (that is TASK-199). The sidecar
# does not exist in a worktree and is not public, so a seed that depended on it
# would fail for exactly the new contributor it is meant to serve. Everything
# below is invented here: varied states, priorities, description lengths and
# emoji, so the board has something to render in every column.
#
# Usage:
#   mise run seed              # boot a throwaway board, seed it, keep it up
#   mise run seed -- --keep    # same, but reuse/keep the data dir between runs
#
# The server it boots is throwaway by default: a fresh --pb-dir under
# .lll-demo/ (gitignored), removed and recreated on each run so the seed is
# reproducible rather than cumulative. Your real pb/pb_data is never touched.
set -euo pipefail
. "$(dirname "$0")/lib.sh"   # free_port, wait_ok, fail - and cds to the checkout root

KEEP=0
case "${1:-}" in
  "") ;;
  --keep) KEEP=1 ;;
  # Named rather than ignored: `mise run seed -- --kepe` silently wiping the
  # data dir you meant to keep is a bad way to learn you typed it wrong.
  *) echo "usage: scripts/seed.sh [--keep]" >&2; exit 2 ;;
esac

DEMO_DIR=".lll-demo"
PB_DIR="$DEMO_DIR/pb_data"
SEED_LOG="$DEMO_DIR/seed.log"
E2E_LOGS="$SEED_LOG"

# The seed's identity and team are pinned in the ENVIRONMENT, never written to
# a file. `lll up` writes 'me' to the HOME config only when it has to guess it
# (up.lis:331) and writes 'team' to the repo's .lll.toml only when no team is
# configured (up.lis:311) - so pinning LLL_ME and LLL_TEAM means this script
# leaves no config behind in either place. That matters: a stray .lll.toml
# written by a demo boot once poisoned the e2e suite for hours (TASK-143), and
# a seed run is precisely the kind of thing that would do it again.
export LLL_TEAM=DEMO
export LLL_ME=demo

# A scratch HOME, for the same reason the e2e suites use one (lib.sh
# e2e_pin_home), and it is not optional here - it is the difference between
# this script working and not.
#
# Config LAYERS (TASK-168): ~/.config/lll/lll.toml is read on every run, and
# anyone who has run `lll login` has a `token` in it. The file layer is applied
# BEFORE the env layer and only non-empty values override (config.lis:97), so
# `env -u LLL_TOKEN` does NOT clear it - nothing does except moving HOME. With
# that stale token present, `up` sees a non-empty cfg.token, SKIPS minting its
# own superuser token (up.lis:174), and dies on the next line with
#
#   Error: could not create team 'DEMO' and none exists to reuse
#
# which names the team, says nothing about auth, and sends you looking at the
# wrong thing entirely. The token is perfectly valid - for somebody else's
# server. The freshly booted one has never heard of it.
#
# A stale `url` in the same file is the other half: it would aim an unpinned
# command at a deployed board, and this script does write fixtures.
#
# Safe to do at the top only because this script never builds: it requires an
# already-built binary and says so. The lis and go caches live under the real
# HOME, so anything that compiles must run before this line - which is why the
# mise task depends on `build` rather than building here.
export HOME="$PWD/$DEMO_DIR/home"
mkdir -p "$HOME/.config/lll"
# A fixed board token, so the login URL printed at the end is stable and this
# script can print it without scraping it back out of the boot banner.
export LLL_BOARD_TOKEN=demo-board-token

mkdir -p "$DEMO_DIR"
if [ "$KEEP" = 0 ]; then
  rm -rf "$PB_DIR"
fi
mkdir -p "$PB_DIR"

DB_PORT=$(free_port 20000 39999)
WEB_PORT=$(free_port 40000 59999)
URL="http://127.0.0.1:$DB_PORT"
export LLL_URL="$URL"

LLL=target/.lisette/bin/lll
[ -x "$LLL" ] || fail "$LLL not built - run 'mise run build' first"

# `lll up` auto-increments off a taken port, so the port it actually chose is
# not necessarily the one asked for. free_port bind-tests, which makes a move
# unlikely, but the URL printed at the end must be the real one either way.
#
# `env -u LLL_TOKEN` covers the case the scratch HOME does not: a token
# exported in the calling shell. Either source makes `up` skip minting its own
# superuser token (up.lis:174) and then fail to create the team; see the HOME
# note above for why that failure names the wrong thing.
env -u LLL_TOKEN "$LLL" up --no-open --port "$WEB_PORT" --pb-dir "$PB_DIR" \
  </dev/null >"$SEED_LOG" 2>&1 &
UP_PID=$!

cleanup() { # exit-status
  # Only on the failure path. The whole point of the script is to leave a board
  # running for a human to look at, so a clean run must NOT kill the server.
  [ "${1:-0}" -eq 0 ] && return 0
  echo "--- seed.log ---" >&2
  tail -30 "$SEED_LOG" >&2 || true
  e2e_reap "${UP_PID:-}"
}
e2e_trap_cleanup cleanup

wait_ok "$URL/api/health" 200 || fail "the demo PocketBase never came up on $DB_PORT"
# The board's port is read back out of the banner rather than assumed: `lll up`
# auto-increments off a taken port, and the URL this script prints at the end
# has to be the one it actually bound. free_port bind-tests so a move is
# unlikely, but "unlikely" printed as fact is how someone ends up staring at a
# 'connection refused' deciding the seed silently did nothing.
#
# Polled, not read once: /api/health answers as soon as PocketBase binds, which
# is BEFORE `up` has created the team, the member, or chosen the board's port.
# A single read here reliably gets an empty file.
BOARD_URL=""
for _ in $(seq 1 100); do
  BOARD_URL=$(sed -n 's|.*board  login \(http://[^ ]*\).*|\1|p' "$SEED_LOG" | head -1)
  [ -n "$BOARD_URL" ] && break
  sleep 0.1
done
[ -n "$BOARD_URL" ] || fail "the boot banner never printed a board login URL"

# TASK-181: the collection rules are authenticated-only, so the CLI needs a
# member token. lib.sh's pb_member_token runs the same auth-with-password round
# trip a human login does, against the server just booted.
LLL_TOKEN=$(pb_member_token "$URL" seed seed@lll.test seed-pass-123) \
  || fail "could not bootstrap a member token against $URL"
export LLL_TOKEN

# --- the fixtures ------------------------------------------------------------
# Small helpers so the data below reads as data. A seed that half-ran is worse
# than one that failed: the board then looks fine and is quietly missing
# whichever column you were about to judge, so every one of these dies loudly.
#
# This one captures and REPRINTS the CLI's own message. A bare
# `|| fail "lll $*"` echoes the command back with a 20-line description
# interpolated into it and never says why the server refused - exactly the mute
# red this script exists to spare people.
lll() {
  local out
  out=$("$LLL" "$@" 2>&1) || fail "lll $1 $2: $out"
  printf '%s' "$out"
}

# The already-there variant. Members, teams, projects and labels are unique
# server-side and the CLI has no --if-missing, so a create that loses to
# something that got there first is a 400 and not an error worth stopping for.
# Two things get there first: `lll up` seeds the LLL_ME member on every boot
# (up.lis:336), and `--keep` reuses a data dir that already holds the whole
# fixture set. Issues deliberately do NOT go through this - they have no
# uniqueness constraint, so a failure there is real.
lll_idem() { "$LLL" "$@" >/dev/null 2>&1 || true; }

people() {
  # demo already exists: `lll up` seeded it from LLL_ME during the boot above.
  lll_idem member add -n demo -e demo@lll.test
  lll_idem member add -n avery -e avery@lll.test
  lll_idem member add -n kai -e kai@lll.test
  # But the members must genuinely be there, or every --assignee below fails
  # one at a time with a message about an unknown member instead of this one.
  for who in demo avery kai; do
    "$LLL" member list | grep -qw "$who" || fail "member '$who' was not created"
  done
}

# Two projects and a spread of labels: enough for the project filter, the
# label picker and the label inventory to have something to show.
scaffolding() {
  lll_idem project create -n "Board v2" -d "Make the board pleasant to live in." --status started
  lll_idem project create -n "Onboarding" -d "Everything a second person hits in their first ten minutes." --status planned
  lll_idem label create -n bug -c "#e5484d"
  lll_idem label create -n feature -c "#3e63dd"
  lll_idem label create -n chore -c "#8e8c99"
  lll_idem label create -n docs -c "#30a46c"
  lll_idem label create -n perf -c "#f76b15"
  # Same reason as the member check: an --project or --label on an issue below
  # fails per-issue and blames the issue, not the missing project or label.
  for p in "Board v2" Onboarding; do
    "$LLL" project list | grep -qF "$p" || fail "project '$p' was not created"
  done
  for l in bug feature chore docs perf; do
    "$LLL" label list | grep -qw "$l" || fail "label '$l' was not created"
  done
}

# A long description, so the issue page and the card have to cope with one.
# The 5000-char cap TASK-46 found is real, so this stays well under it while
# still being longer than anything a hand-typed fixture would be.
LONG_DESC='The board renders every issue description as markdown, which means
the seed has to contain some.

## Why this issue is long

Short fixtures make everything look fine. A description that runs past the
fold is what exercises the overflow rules on the card, the scroll behaviour on
the issue page, and the truncation in search results.

- a list item
- another list item, longer than the first, so wrapping happens somewhere
- a third

Code, because markdown rendering is a thing that breaks:

```sh
mise run seed
```

And a closing paragraph so the document does not end on a code fence.'

# Create an issue, then move it to a state. Two calls because `--state` is on
# `issue list` and `issue update` but NOT on `issue create` (issue.lis:151 and
# :231, with nothing at create) - every new issue lands in the create default
# and has to be moved. Nothing here needs it fixed; the seed just has to know.
#
# That default is "todo" (issue.lis:488), which is worth stating rather than
# assuming: an earlier version of this function skipped the update when the
# wanted state was "backlog", on the theory that new issues start there. They
# do not, and the seed quietly produced four todo columns and an empty backlog
# - a wrong board that looks like a working one, which is the failure mode a
# seed script is least able to afford. Hence: always update, never guess.
mk() { # state create-args...
  local state=$1 out id
  shift
  out=$(lll issue create "$@")
  # "Created DEMO-7" - the id on the line that announces it.
  id=$(printf '%s' "$out" | sed -n 's/^Created \([A-Z0-9]*-[0-9]*\).*/\1/p' | head -1)
  [ -n "$id" ] || fail "issue create printed no id: $out"
  lll issue update "$id" --state "$state" >/dev/null
  printf '%s' "$id"
}

issues() {
  # Spread across every state the board has a column for, every priority, both
  # projects, assigned and unassigned, with and without emoji.
  ISSUE_COLUMNS=$(mk in-progress -t "Board columns collapse on narrow windows" -d "$LONG_DESC" \
    --priority 1 --assignee avery --project "Board v2" --label bug --label perf --emoji "🐛")
  mk todo -t "Vendor datastar so the board works offline" \
    -d "The CDN tag is the last thing that breaks the board with no network." \
    --priority 2 --assignee kai --project "Board v2" --label chore >/dev/null
  mk done -t "Seed script" -d "A board with something on it, in one command." \
    --priority 3 --assignee demo --project Onboarding --label chore --label docs --emoji "🌱" >/dev/null
  ISSUE_SECOND_BOOT=$(mk in-review -t "Second boot fails with no team configured" \
    -d "up guesses the key correctly and then refuses to use its own guess." \
    --priority 1 --assignee demo --project Onboarding --label bug)
  mk backlog -t "Document the scratch board recipe" \
    -d "Only the e2e scripts know how to start a board that does not collide." \
    --priority 4 --project Onboarding --label docs >/dev/null
  mk backlog -t "Short one" --priority 0 >/dev/null
  mk todo -t "Make the binary relocatable" \
    -d "pb_migrations is still read from disk, so lll up only runs from the checkout." \
    --priority 2 --assignee kai --project "Board v2" --label bug --emoji "📦" >/dev/null
  mk cancelled -t "Drop the old export path" -d "Superseded; keeping it around costs more than it earns." \
    --priority 4 --label chore >/dev/null
  mk done -t "Label inventory in settings" -d "See which labels are actually in use." \
    --priority 3 --assignee avery --project "Board v2" --label feature >/dev/null
}

# Comments, so the issue page is not just a description. Authored as 'me',
# which LLL_ME pins to the seeded demo member.
#
# Addressed by the ids issues() captured, not by a literal DEMO-1: issue
# numbers are per-team and monotonic, so under --keep the second run's issues
# start at DEMO-10 and every hardcoded id would comment on the wrong thing.
conversation() {
  lll issue comment "$ISSUE_COLUMNS" -b "Reproduced at 900px. The third column wraps under the second." >/dev/null
  lll issue comment "$ISSUE_COLUMNS" -b "Narrowing it to the flex-basis on the column wrapper." >/dev/null
  lll issue comment "$ISSUE_SECOND_BOOT" -b "Ready for review - the guess is now used when stdin is empty." >/dev/null
}

people
scaffolding
issues
conversation

# --- done --------------------------------------------------------------------
# Assert the spread, do not just count. The point of the seed is a board with
# something in every column, and the bug this catches has already happened
# once: a wrong skip in mk() left the backlog empty and piled four issues into
# todo. The count was still 9 and the run still said "seeded 9 issues", so
# nothing announced it - it had to be found by reading the database by hand.
# One issue per state is the weakest claim worth making, and it is enough.
listing=$("$LLL" issue list --json)
count=$(printf '%s' "$listing" | jq '.items | length')
for want in backlog todo in-progress in-review done cancelled; do
  printf '%s' "$listing" | jq -e --arg s "$want" 'any(.items[]; .state == $s)' >/dev/null \
    || fail "no issue ended up in state '$want' - the board will render an empty column"
done

echo
echo "seeded $count issues, 2 projects, 5 labels, 3 members into a throwaway board"
echo
echo "  board   $BOARD_URL"
echo "  db      $URL/_/"
if [ "$KEEP" = 1 ]; then
  echo "  data    $PB_DIR  (kept and added to; drop --keep for a clean board)"
else
  echo "  data    $PB_DIR  (thrown away on the next run; --keep to add to it instead)"
fi
echo
echo "the server is still running as pid $UP_PID - Ctrl-C it, or:  kill $UP_PID"
echo "to drive the CLI against it in another shell:"
echo "  export LLL_URL=$URL LLL_TEAM=DEMO LLL_TOKEN=$LLL_TOKEN"
echo

# Hand the terminal to the server: Ctrl-C then stops the board, which is what
# someone who just ran a script that printed a URL expects Ctrl-C to do.
wait "$UP_PID"
