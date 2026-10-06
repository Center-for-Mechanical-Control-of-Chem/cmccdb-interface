#!/usr/bin/env bash
# Build and replace only the requested web service; leave the database running.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export CONTAINER_ENGINE=${CONTAINER_ENGINE:-podman}
target=${1:-production}
case "$target" in
  production)
    image=${CMCCDB_INTERFACE_IMAGE:-cmccdb/interface:2025.09.3}
    restart_script=restart_containers.sh
    ;;
  preview)
    image=${CMCCDB_PREVIEW_IMAGE:-cmccdb/interface-preview:2025.09.3}
    restart_script=restart_preview.sh
    ;;
  *) echo "Target must be production or preview" >&2; exit 1 ;;
esac
bash "$repo_root/build_image.sh" "$target" "$image"
bash "$repo_root/$restart_script"
