#!/usr/bin/env bash
# Starts (or restarts) the development instance, cmccdb_interface/docker-compose-dev.yml, with the development
# support asked for; without --frontend or --backend it runs the image's own code and front end.
#   restart_dev.sh [--frontend] [--backend] [--build] [--down]
#     --frontend  the Vue development server from your app/ (hot reload), on the web port
#     --backend   your cmccdb-interface and cmccdb-schema Python code, reloaded on change, and the /api/dev endpoints
#     --build     build the image (the Dockerfile's `preview` target) first
#     --down      stop it instead (its database stays)
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
engine=${CONTAINER_ENGINE:-podman}
compose=("$engine" compose --file "$repo_root/cmccdb_interface/docker-compose-dev.yml")
export CMCCDB_DEV_FRONTEND=false CMCCDB_DEV_BACKEND=false
build=false
for arg in "$@"; do
  case "$arg" in
    --frontend) CMCCDB_DEV_FRONTEND=true ;;
    --backend) CMCCDB_DEV_BACKEND=true ;;
    --build) build=true ;;
    --down) exec "${compose[@]}" down ;;
    *) echo "usage: restart_dev.sh [--frontend] [--backend] [--build] [--down]" >&2; exit 2 ;;
  esac
done
if [ "$build" = true ]; then
  CONTAINER_ENGINE=$engine bash "$repo_root/build_image.sh" preview "${CMCCDB_DEV_IMAGE:-cmccdb/interface-dev:latest}"
fi
"${compose[@]}" up --detach --no-build --force-recreate web_dev
echo "development instance: http://127.0.0.1:${CMCCDB_DEV_WEB_PORT:-92}" \
  "(front end: $([ "$CMCCDB_DEV_FRONTEND" = true ] && echo "development server" || echo built);" \
  "back end: $([ "$CMCCDB_DEV_BACKEND" = true ] && echo "your copy, reloaded" || echo "the image's"))"
