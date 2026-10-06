#!/usr/bin/env bash
# The database must already be running; this only replaces the web container.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
engine=${CONTAINER_ENGINE:-podman}
"$engine" compose --file "$repo_root/cmccdb_interface/docker-compose.yml" \
  up --detach --no-build --no-deps --force-recreate web
