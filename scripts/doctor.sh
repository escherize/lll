#!/usr/bin/env bash
# Is this board instance worth driving?
#
# Read-only. Answers one question before a verification run commits to it: is
# the binary the one we just built, is the port answering and ours, and does
# the board token authenticate. A drive against a stale or wedged instance
# produces evidence about the wrong thing, which is worse than no evidence.
#
# Exit 0 = worth driving. Exit 1 = stop and fix. Exit 2 = usage.
#
# The failure this CANNOT see is a wedged UI on a healthy process: up,
# answering, authenticating, and stuck in a state no assertion expects. When a
# drive fails and doctor is green, relaunch rather than retrying into it.
set -uo pipefail   # no -e: every check reports, one failure does not hide the rest

URL="${LLL_URL:-}"
WEB="${LLL_WEB_URL:-}"
TOKEN="${LLL_BOARD_TOKEN:-${LLL_TEST_BOARD_TOKEN:-}}"
BIN="target/.lisette/bin/lll"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --url)         [ "$#" -ge 2 ] || { echo "--url needs a value" >&2; exit 2; }; URL="$2"; shift 2 ;;
    --web)         [ "$#" -ge 2 ] || { echo "--web needs a value" >&2; exit 2; }; WEB="$2"; shift 2 ;;
    --board-token) [ "$#" -ge 2 ] || { echo "--board-token needs a value" >&2; exit 2; }; TOKEN="$2"; shift 2 ;;
    --binary)      [ "$#" -ge 2 ] || { echo "--binary needs a value" >&2; exit 2; }; BIN="$2"; shift 2 ;;
    -h|--help)
      echo "usage: bash scripts/doctor.sh [--url API] [--web BOARD] [--board-token TOKEN] [--binary PATH]"
      echo "Defaults come from LLL_URL, LLL_WEB_URL, LLL_BOARD_TOKEN."
      exit 0 ;;
    *) echo "usage: bash scripts/doctor.sh [--url API] [--web BOARD] [--board-token TOKEN] [--binary PATH]" >&2; exit 2 ;;
  esac
done

FAILED=0
SKIPPED_TARGET=0
ok()   { printf '  ok    %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; FAILED=1; }
skip() { printf '  skip  %s\n' "$1"; }
# A skipped CONNECTIVITY check is not a pass. Green means we actually reached
# an instance; an all-skipped run means there was nothing to reach, and saying
# "worth driving" about a board we never found is the false confidence this
# script exists to prevent.
skip_target() { skip "$1"; SKIPPED_TARGET=$((SKIPPED_TARGET + 1)); }

echo "doctor: is this instance worth driving?"

# 1. The binary is present, executable, and answers. A verification run against
#    a binary older than the change proves nothing about the change.
if [ -x "$BIN" ]; then
  if VERSION=$("$BIN" --version 2>&1); then
    ok "binary $BIN ($VERSION)"
    if [ -n "$(find "$BIN" -newermt '-24 hours' 2>/dev/null)" ]; then
      ok "binary built within 24h"
    else
      bad "binary is older than 24h - run 'mise run build' before trusting a drive"
    fi
  else
    bad "binary $BIN did not answer --version"
  fi
else
  bad "no binary at $BIN - run 'mise run build'"
fi

# 2. The API is answering. PocketBase's health route is the cheapest honest
#    liveness signal; a TCP connect only proves someone holds the port.
if [ -n "$URL" ]; then
  if curl -sf --max-time 5 "$URL/api/health" >/dev/null 2>&1; then
    ok "API answering at $URL"
  else
    bad "API not answering at $URL/api/health"
  fi
else
  skip_target "no API url (pass --url or export LLL_URL)"
fi

# 3. The board authenticates with the token we hold. An unauthenticated board
#    answers every route with a refusal, which reads like a broken feature.
if [ -n "$WEB" ]; then
  if [ -n "$TOKEN" ]; then
    CODE=$(curl -s -o /dev/null -w '%{http_code}' -L --max-time 5 \
             -H "Cookie: lll_board=$TOKEN" "$WEB/" 2>/dev/null)
    case "$CODE" in
      200) ok "board authenticating at $WEB" ;;
      000) bad "board unreachable at $WEB" ;;
      *)   bad "board at $WEB answered $CODE with the token we hold" ;;
    esac
  else
    CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$WEB/" 2>/dev/null)
    if [ "$CODE" = "000" ]; then
      bad "board unreachable at $WEB"
    else
      skip "board reachable ($CODE) but no token to test authentication"
    fi
  fi
else
  skip_target "no board url (pass --web or export LLL_WEB_URL)"
fi

# 4. playwright-cli, because its absence makes browser sections SKIP rather
#    than fail. A suite that skipped the only section covering your change
#    still exits 0.
if command -v playwright-cli >/dev/null 2>&1; then
  ok "playwright-cli present (browser sections will run)"
else
  bad "playwright-cli missing - browser drives will SKIP, not fail; use --require-browser to make that loud"
fi

if [ "$FAILED" -eq 0 ] && [ "$SKIPPED_TARGET" -ge 2 ]; then
  echo "doctor: no instance to check - pass --url and --web, or export LLL_URL and LLL_WEB_URL" >&2
  echo "doctor: this is NOT a green light; nothing was reached" >&2
  exit 1
fi

if [ "$FAILED" -eq 0 ]; then
  echo "doctor: green - worth driving"
else
  echo "doctor: red - fix the above before driving; evidence from a bad instance is worse than none" >&2
fi
exit "$FAILED"
