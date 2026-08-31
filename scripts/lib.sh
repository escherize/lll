# Shared scaffolding for the e2e suites. Source it, never run it:
#
#   set -euo pipefail
#   . "$(dirname "$0")/lib.sh"
#   e2e_begin
#
# Sourcing also cds to the checkout root, so a suite can use repo-relative
# paths (target/.lisette/bin/lll, scripts/e2e_web.sh) however it was invoked.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

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

# Poll an HTTP endpoint until it answers, at 0.1s intervals. Returns 1 when it
# never does, so the caller is the one that says which server it waited for.
wait_ok() { # url [tries=100]
  for _ in $(seq 1 "${2:-100}"); do
    curl -sf "$1" >/dev/null 2>&1 && return 0
    sleep 0.1
  done
  return 1
}

# Name the assertion, then show the tail of every log the suite registered in
# E2E_LOGS (in order, most specific first).
fail() { # message
  echo "FAIL: $1" >&2
  for _log in ${E2E_LOGS:-}; do
    [ -f "$_log" ] || continue
    echo "--- ${_log##*/} ---" >&2
    tail -20 "$_log" >&2 || true
  done
  exit 1
}

assert_contains() { # haystack needle label
  # No -q: with pipefail, grep -q exits on the first match and the writer
  # eats EPIPE for the bytes after it — a matching haystack then FAILS when
  # the needle sits early in a large page (seen on a loaded CI runner, where
  # the scheduler widens that window). Reading everything is the fix; the
  # match status is unchanged.
  printf '%s' "$1" | grep -F -- "$2" >/dev/null || fail "$3: expected '$2' in output:
$1"
}

assert_not_contains() { # haystack needle label
  printf '%s' "$1" | grep -F -- "$2" >/dev/null &&
    fail "$3: did not expect '$2' in output:
$1" || true
}

# --- TASK-181: every collection rule is authenticated-only now --------------
# PocketBase answers nothing useful to a tokenless request, so every suite
# drives the server with a member token. pb_superuser_token is the admin API
# (the credentials `lll up` prints and upserts); pb_member_token runs the
# same auth-with-password round trip a human login does: find-or-create a
# member whose password the suite knows, then exchange identity+password for
# the member token the CLI itself sends as LLL_TOKEN.
pb_superuser_token() { # url
  curl -sf -X POST "$1/api/collections/_superusers/auth-with-password" \
    -H 'Content-Type: application/json' \
    -d '{"identity":"admin@local.dev","password":"admin-local-123"}' | jq -r '.token'
}

pb_member_token() { # url name email password -> prints the member token
  local url=$1 name=$2 email=$3 pass=$4 atok id
  atok=$(pb_superuser_token "$url")
  [ -n "$atok" ] && [ "$atok" != "null" ] || return 1
  id=$(curl -sf -G "$url/api/collections/members/records" \
    --data-urlencode "filter=(name='$name')" -H "Authorization: Bearer $atok" \
    | jq -r '(.items[0] // {}).id // ""')
  if [ -z "$id" ]; then
    id=$(curl -sf -X POST "$url/api/collections/members/records" \
      -H 'Content-Type: application/json' -H "Authorization: Bearer $atok" \
      -d "{\"name\":\"$name\",\"email\":\"$email\",\"password\":\"$pass\",\"passwordConfirm\":\"$pass\"}" \
      | jq -r '.id // ""')
  else
    # Left over from an earlier run of this suite: reset to the known
    # password so auth-with-password below always succeeds.
    curl -sf -X PATCH "$url/api/collections/members/records/$id" \
      -H 'Content-Type: application/json' -H "Authorization: Bearer $atok" \
      -d "{\"password\":\"$pass\",\"passwordConfirm\":\"$pass\"}" >/dev/null
  fi
  [ -n "$id" ] && [ "$id" != "null" ] || return 1
  curl -sf -X POST "$url/api/collections/members/auth-with-password" \
    -H 'Content-Type: application/json' \
    -d "{\"identity\":\"$email\",\"password\":\"$pass\"}" | jq -r '.token'
}

# A scratch DATA_DIR, a scratch E2E_HOME, and hermeticity: a developer's own
# config must not leak into assertions. It is announced by name because the
# reverse — a stray config quietly steering a run — once cost hours (TASK-143).
#
# E2E_HOME exists because config now LAYERS (TASK-168): ~/.config/lll/lll.toml
# is read on every run, under the repo file rather than instead of it, and
# `lll up` WRITES 'me' there on a first boot. Any invocation that boots lll up
# or asserts on config must pass HOME="$E2E_HOME", so a suite neither reads
# nor rewrites the developer's own.
e2e_begin() {
  # The suites write fixtures into whatever LLL_URL names. An inherited
  # non-local LLL_URL would run the whole write-heavy gate against a live
  # server (the deployed board, TASK-171), so an allowlist of loopback hosts
  # is the guard: anything unrecognizable is refused, named, up front.
  case "${LLL_URL:-}" in
    "" | http://127.0.0.1:* | http://localhost:* | http://\[::1\]:* | http://\[::1\]) ;;
    *)
      echo "refusing non-local LLL_URL '$LLL_URL' — the gate writes fixtures; unset it or point it at 127.0.0.1" >&2
      exit 1
      ;;
  esac
  DATA_DIR="$(mktemp -d)"
  E2E_HOME="$DATA_DIR/e2e_home"
  mkdir -p "$E2E_HOME/.config/lll"
  if [ -f .lll.toml ]; then
    echo "e2e: repo-root .lll.toml moved aside for this run, restored on exit" >&2
    mv .lll.toml "$DATA_DIR/.lll.toml.saved"
    RESTORE_TOML=1
  fi
}

# The tail of every suite's EXIT trap: put the repo's own .lll.toml back.
#
# It restores rather than deletes because .lll.toml is TRACKED now (TASK-168):
# `rm -f` on a committed file leaves git status dirty after every run, and on
# a checkout whose copy is already missing it deletes it for good. The bare
# `rm` is kept only for the case where there was nothing to move aside, where
# any file present was written by this run.
e2e_end() {
  if [ "${RESTORE_TOML:-}" != 1 ]; then
    rm -f .lll.toml
  elif [ -f "$DATA_DIR/.lll.toml.saved" ]; then
    mv -f "$DATA_DIR/.lll.toml.saved" .lll.toml
  else
    echo "e2e: the saved .lll.toml is gone; restore it with 'git checkout .lll.toml'" >&2
  fi
  rm -rf "$DATA_DIR"
}
