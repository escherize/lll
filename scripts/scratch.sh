#!/usr/bin/env bash
# The installed binary owns scratch isolation; this checkout helper delegates.
set -euo pipefail
exec "$PWD/target/.lisette/bin/lll" up --scratch "$@"
