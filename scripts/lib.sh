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

# A scratch DATA_DIR, and hermeticity: a developer's repo-root .lll.toml must
# not leak into assertions. It is announced by name because the reverse — a
# stray config quietly steering a run — once cost hours (TASK-143).
e2e_begin() {
  DATA_DIR="$(mktemp -d)"
  if [ -f .lll.toml ]; then
    echo "e2e: repo-root .lll.toml moved aside for this run, restored on exit" >&2
    mv .lll.toml "$DATA_DIR/.lll.toml.saved"
    RESTORE_TOML=1
  fi
}

# The tail of every suite's EXIT trap: `lll up` writes a .lll.toml on a first
# boot, so drop it and put the developer's own back on top.
e2e_end() {
  rm -f .lll.toml
  if [ "${RESTORE_TOML:-}" = 1 ] && [ -f "$DATA_DIR/.lll.toml.saved" ]; then
    mv "$DATA_DIR/.lll.toml.saved" .lll.toml
  fi
  rm -rf "$DATA_DIR"
}
