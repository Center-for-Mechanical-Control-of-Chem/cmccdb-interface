#!/usr/bin/env bash
# The preview database must already be running; replace only the preview web.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
engine=${CONTAINER_ENGINE:-podman}
"$engine" compose --file "$repo_root/cmccdb_interface/docker-compose-preview.yml" \
  up --detach --no-build --no-deps --force-recreate web_preview
