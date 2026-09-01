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

# The tail of every log the suite registered in E2E_LOGS (in order, most
# specific first). Split out of fail() so the EXIT trap can print the same
# thing for a death that never reached an assertion (TASK-121).
e2e_log_tails() {
  for _log in ${E2E_LOGS:-}; do
    [ -f "$_log" ] || continue
    echo "--- ${_log##*/} ---" >&2
    tail -20 "$_log" >&2 || true
  done
}

# Name the assertion, then show the logs.
#
# The marker file is for the trap: fail() has already said everything there is
# to say, so e2e_diagnose must not say it twice. A FILE and not a variable
# because fail() can run inside a command substitution, where a variable it
# sets dies with the subshell but the exit status still reaches the trap.
fail() { # message
  echo "FAIL: $1" >&2
  : > "${DATA_DIR:-${TMPDIR:-/tmp}}/.e2e_failed" 2>/dev/null || true
  e2e_log_tails
  exit 1
}

# Run a fixture write and fail NAMING IT if the server did not accept it
# (TASK-162). Prints the response body, so a caller can still pipe it to jq.
#
# `curl -sf` on a seed is not enough. It exits non-zero on a 4xx and `set -e`
# then aborts the suite, but it aborts MUTELY: no FAIL line, no log tail,
# nothing that says which write died — the silent red a later agent re-runs
# blind. And `-f` throws the body away, so even a manual re-run does not learn
# WHY PocketBase refused it. The other half of the complaint is the seed that
# is lost in a pipeline or an `|| true`: nothing aborts, the fixture simply is
# not there, and the assertion it was setting up fails several sections later
# blaming a feature that is fine.
#
# So: no -f. Ask for the status code explicitly, judge it here, and put the
# server's own error body in the failure message. Reads do NOT go through this
# — they are asserted on directly, and wrapping them would be churn.
seed() { # label curl-args... -> the response body
  local label=$1 out status=0 code
  shift
  out=$(curl -sS -w '\n%{http_code}' "$@" 2>&1) || status=$?
  code=${out##*$'\n'}   # the -w line
  out=${out%$'\n'*}     # everything before it: the body, or curl's own error
  [ "$status" = 0 ] || fail "seed '$label' never reached the server (curl exit $status): $out"
  case "$code" in
    2*) ;;
    *) fail "seed '$label' was refused with HTTP $code: $out" ;;
  esac
  printf '%s' "$out"
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
    # TASK-143: the move alone is not the report. A stray file written by an
    # earlier demo (`lll up` with no configured team writes .lll.toml into the
    # CURRENT directory) once made the gate die at 'FAIL: seeding teams' with a
    # JSON decode error, and nothing in that output pointed back here. The move
    # aside makes the run hermetic; ECHOING THE CONTENTS is what lets the next
    # reader connect a weird failure to a file they did not know they had.
    echo "e2e: repo-root .lll.toml moved aside for this run, restored on exit" >&2
    echo "e2e:   its contents were: $(tr '\n' ' ' < .lll.toml)" >&2
    mv .lll.toml "$DATA_DIR/.lll.toml.saved"
    RESTORE_TOML=1
  fi
}

# Kill a list of PIDs and WAIT for them to actually be gone (TASK-153).
#
# The waiting is the point. `kill` only delivers the signal; a bare `kill`
# followed by e2e_end's `rm -rf "$DATA_DIR"` races the server's own shutdown,
# and PocketBase loses that race often enough to have been seen in the wild:
# the --pb-dir vanishes, the process keeps running on its port with deleted
# files, and it outlives the suite as an orphan. Orphans have to be hunted by
# PID here, because `pkill -f "bin/lll up"` would kill a sibling agent's
# server, so the suite that started one is the only thing that can end it.
#
# Empty and already-reaped PIDs are normal (the non-trap paths kill and clear
# their own), hence the guards: `wait` on a non-child is an error we do not
# care about, and under `set -e` an unguarded non-zero here would abort the
# trap before e2e_end ran.
#
# The wait is BOUNDED. PocketBase's TERM handler is its own graceful shutdown,
# which is normally instant but is not contractually instant, and a cleanup
# trap that blocked forever would trade a loud failure for a silent hang - the
# opposite of what TASK-121 wants. The bound is a detached watchdog that sends
# KILL after E2E_REAP_GRACE seconds, so the `wait` below always returns. It
# cannot be a poll on `kill -0`, because a child that has already died but not
# been waited for is a zombie, and signalling a zombie succeeds: the only
# thing that distinguishes dead from alive here is `wait` itself.
E2E_REAP_GRACE=${E2E_REAP_GRACE:-10}
e2e_reap() { # pid...
  local _pid _pids="" _guard
  for _pid in "$@"; do
    [ -n "$_pid" ] || continue
    _pids="$_pids $_pid"
    kill "$_pid" 2>/dev/null || true
  done
  [ -n "$_pids" ] || return 0
  # setsid-free detachment: a plain background subshell is enough, because it
  # is reaped explicitly below and never waited on by the caller's `wait`
  # loop (which names PIDs).
  ( sleep "$E2E_REAP_GRACE"
    for _pid in $_pids; do kill -9 "$_pid" 2>/dev/null || true; done ) &
  _guard=$!
  for _pid in $_pids; do
    wait "$_pid" 2>/dev/null || true
  done
  kill "$_guard" 2>/dev/null || true
  wait "$_guard" 2>/dev/null || true
}

# The failure path must never be silent (TASK-121).
#
# A run once exited 1 having printed only its two `lis build` lines: no FAIL,
# no assertion, no log tail, nothing for the next agent to read. Any death
# that does not go through fail() looks like that - a `set -e` abort on a bare
# command, a signal from outside the suite - because only fail() prints.
#
# So the EXIT trap says the two things that are always available: the status,
# and the tail of every registered log. It runs FIRST in each trap, before the
# kills and before e2e_end removes DATA_DIR (the logs live in there), and it
# stays quiet on both the success path and after fail(), which has already
# printed all of this and left its marker.
#
# Nothing in here may abort: a failure inside the trap would swallow the very
# message the trap exists to print, so every step is unconditional or guarded.
e2e_diagnose() { # exit-status
  [ "${1:-0}" -ne 0 ] 2>/dev/null || return 0
  [ ! -f "${DATA_DIR:-${TMPDIR:-/tmp}}/.e2e_failed" ] || return 0
  echo "FAIL: ${0##*/} exited $1 without naming an assertion - the tails below are all there is" >&2
  e2e_log_tails || true
}

# Install a suite's cleanup on EXIT and on the signals that otherwise skip it.
#
# EXIT alone is not enough for TASK-121: bash runs no EXIT trap for a TERM it
# has no trap for, so a suite killed from outside (the suspected cause in that
# report - a sibling's pkill) dies printing nothing at all and leaks its
# server on top. Re-raising with the default handler after cleanup keeps the
# exit status honest: 130 for INT, 143 for TERM, not a laundered 0.
#
# The status passed on a signal is the conventional 128+signo rather than `$?`,
# which inside a signal trap is whatever the interrupted command last set -
# frequently 0, which would make e2e_diagnose stay silent on exactly the death
# it is here to report.
e2e_trap_cleanup() { # cleanup-function-name
  trap "$1 \$?" EXIT
  trap "$1 130; trap - EXIT INT;  kill -INT  \$\$" INT
  trap "$1 143; trap - EXIT TERM; kill -TERM \$\$" TERM
  trap "$1 129; trap - EXIT HUP;  kill -HUP  \$\$" HUP
}

# TASK-187: pin HOME for the REST of the suite, so plain CLI invocations stop
# reading the developer's own ~/.config/lll/lll.toml. Config LAYERS (TASK-168),
# so that file is consulted on every run; the individual `HOME="$E2E_HOME"`
# spellings cover `lll up` and the config assertions, but the bulk of plain
# invocations still inherited the real one. Today they mostly survive because
# they pin LLL_URL/LLL_TEAM in env and env outranks files - a home config
# setting 'sort' or 'me' steers any assertion that pins neither, and the gate
# then fails for exactly one person. Worse, a home config with a deployed
# 'url' plus a 'token' aims an unpinned command at a live server.
#
# CALL THIS AFTER `lis build`, NEVER BEFORE. The lis, go and mise caches all
# live under HOME (~/.lisette, ~/Library/Caches/go-build, ~/go/pkg/mod), so
# exporting a scratch HOME first moves every one of them and each run
# recompiles from scratch. The build is the only step that wants the real one.
#
# E2E_REAL_HOME is recorded for the same reason: e2e.sh ends by running
# e2e_web.sh and e2e_up.sh, and each of those runs its own `lis build` before
# calling this itself. A child that inherited the pinned HOME would build
# against a cold cache, so e2e.sh hands the real one back when it invokes them.
e2e_pin_home() {
  E2E_REAL_HOME="$HOME"
  export HOME="$E2E_HOME"
}

# The tail of every suite's EXIT trap: put the repo's own .lll.toml back.
#
# It restores rather than deletes because .lll.toml is TRACKED now (TASK-168):
# `rm -f` on a committed file leaves git status dirty after every run, and on
# a checkout whose copy is already missing it deletes it for good. The bare
# `rm` is kept only for the case where there was nothing to move aside, where
# any file present was written by this run.
e2e_end() {
  # TASK-143: a .lll.toml present at the END that this run did not put back is
  # a file something WROTE during the run - `lll up` with no configured team
  # writes one into the current directory. Name it here, at the moment it can
  # still be attributed, instead of leaving it to poison a later run that will
  # only manage to say 'FAIL: seeding teams'. Report, never remove: which
  # process wrote it is the open question (TASK-115), and a silent delete is
  # how the question stays open.
  if [ "${RESTORE_TOML:-}" = 1 ] && [ -f .lll.toml ]; then
    echo "e2e: a .lll.toml APPEARED at the repo root during this run (something wrote it):" >&2
    echo "e2e:   $(tr '\n' ' ' < .lll.toml)" >&2
    echo "e2e:   the run's saved copy is restored over it; see TASK-143/TASK-115" >&2
  fi
  if [ "${RESTORE_TOML:-}" != 1 ]; then
    rm -f .lll.toml
  elif [ -f "$DATA_DIR/.lll.toml.saved" ]; then
    mv -f "$DATA_DIR/.lll.toml.saved" .lll.toml
  else
    echo "e2e: the saved .lll.toml is gone; restore it with 'git checkout .lll.toml'" >&2
  fi
  rm -rf "$DATA_DIR"
}
