#!/usr/bin/env bash
# An isolated board, including config and identity, using the same free-port
# probe as the gate. Migrations are embedded; no checkout cwd is required.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

scratch_binary="$PWD/target/.lisette/bin/lll"
scratch_db_port=$(free_port 20000 39999)
scratch_web_port=$(free_port 40000 59999)
scratch_dir=$(mktemp -d "${TMPDIR:-/tmp}/lll-scratch.XXXXXX")
scratch_team=${LLL_TEAM:-SCRAT}
mkdir -p "$scratch_dir/home"

# Env beats files. A hosted token, identity, bind address or admin pair must
# not steer this fresh database. Only the explicitly selected team is kept.
for scratch_var in ${!LLL_@}; do
  unset "$scratch_var"
done

echo "scratch board: db :$scratch_db_port, web :$scratch_web_port, data $scratch_dir"
echo "  isolated config: $scratch_dir/home/.config/lll/lll.toml"
echo "  temporary - after stopping, delete with: rm -rf '$scratch_dir'"

# HOME is scoped to the child process; cwd is outside every attached repo.
# exec leaves the server in charge of SIGINT/SIGTERM and its own shutdown.
cd "$scratch_dir/home"
exec env HOME="$scratch_dir/home" \
  LLL_ADMIN_EMAIL=admin@local.dev LLL_ADMIN_PASSWORD=admin-local-123 \
  LLL_URL="http://127.0.0.1:$scratch_db_port" LLL_TEAM="$scratch_team" \
  LLL_ME=scratch LLL_BIND=127.0.0.1 \
  "$scratch_binary" up --port "$scratch_web_port" --pb-dir "$scratch_dir/pb_data" "$@"
