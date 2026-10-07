#!/usr/bin/env bash
# Operator-only backend deployment. The database container is never replaced.
set -euo pipefail
umask 077
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workspace=$(dirname -- "$repo_root")
if [ "$(uname -s)" = Darwin ] && [ -x "$workspace/.codex/envs/python3.11-codex/bin/python" ]; then
  exec /usr/bin/arch -arm64 "$workspace/.codex/envs/python3.11-codex/bin/python" \
    "$repo_root/scripts/update_backend.py" "$@"
fi
exec "${PYTHON:-python3}" "$repo_root/scripts/update_backend.py" "$@"
