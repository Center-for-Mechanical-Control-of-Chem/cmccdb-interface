#!/usr/bin/env bash
# Build without restarting a deployment. Repositories are sibling directories.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
engine=${CONTAINER_ENGINE:-docker}
target=${1:-production}
image=${2:-cmccdb/interface:2025.09.3}
case "$target" in production|preview) ;; *) echo "Target must be production or preview" >&2; exit 1 ;; esac
args=(build)
if [ "$(basename -- "$engine")" = podman ]; then
  args+=(--ignorefile "$repo_root/cmccdb_interface/Dockerfile.dockerignore")
fi
"$engine" "${args[@]}" --target "$target" -t "$image" \
  -f "$repo_root/cmccdb_interface/Dockerfile" "$(dirname -- "$repo_root")"
