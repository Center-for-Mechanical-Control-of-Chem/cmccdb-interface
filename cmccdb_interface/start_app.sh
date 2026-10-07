#!/bin/bash
# Copyright 2023 Open Reaction Database Project Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#
# Runs the app with gunicorn behind a nginx proxy.
#
# Development support (docker-compose-dev.yml; all off by default):
#   CMCCDB_DEV_FRONTEND=true   run the Vue development server (port 95, hot reload) from the front end in
#                              /app/cmccdb-interface/dev (mount your app/ there; needs the `preview` image target).
#                              CMCCDB_LAUNCH_DEV_INTERFACE is its older name.
#   CMCCDB_DEV_FRONTEND_PROXY=true
#                              serve that development server on port 80 as well, in place of the built front end
#                              (one port for everything, e.g. through a tunnel)
#   CMCCDB_DEV_BACKEND=true    run the Python code mounted in CMCCDB_DEV_SOURCE_DIR (default /app/dev-src:
#                              cmccdb-interface/cmccdb_interface and cmccdb-schema/cmccdb_schema), reloaded when it
#                              changes, with the /api/dev endpoints on (CMCCDB_DEV_ENDPOINTS, unless set)
set -euo pipefail

truthy() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    true|1|yes|on) return 0 ;;
  esac
  return 1
}

frontend_dev=${CMCCDB_DEV_FRONTEND:-${CMCCDB_LAUNCH_DEV_INTERFACE:-false}}
frontend_proxy=${CMCCDB_DEV_FRONTEND_PROXY:-false}
backend_dev=${CMCCDB_DEV_BACKEND:-false}
dev_src=${CMCCDB_DEV_SOURCE_DIR:-/app/dev-src}

if truthy "$frontend_dev"; then
  if ! command -v npm > /dev/null 2>&1; then
    echo "CMCCDB_DEV_FRONTEND: this image has no npm; build the 'preview' target" >&2
    exit 1
  fi
  curdir=$PWD
  cd /app/cmccdb-interface/dev
  dependency_hash=$(sha256sum package.json package-lock.json /app/cmccdb-schema/js/cmccdb-schema/package.json | sha256sum | cut -d ' ' -f 1)
  installed_hash=$(cat node_modules/.cmccdb-dependencies.sha256 2>/dev/null || true)
  if [ "$dependency_hash" != "$installed_hash" ]; then
    npm ci --no-audit --no-fund
    printf '%s\n' "$dependency_hash" > node_modules/.cmccdb-dependencies.sha256
  fi
  # polling sees edits on mounted (and network) file systems, where change notifications may not arrive
  WATCHPACK_POLLING=${WATCHPACK_POLLING:-true} npm run serve -- --port=95 &
  echo "front end: development server on port 95 from /app/cmccdb-interface/dev"
  cd "$curdir"
else
  frontend_proxy=false
fi

# What nginx serves on port 80 (nginx.conf includes this)
if truthy "$frontend_proxy"; then
  cat > /etc/nginx/cmccdb-frontend.conf <<'NGINX'
location / {
    proxy_pass http://127.0.0.1:95;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_read_timeout 3600;
}
NGINX
  echo "front end: port 80 serves the development server"
else
  cat > /etc/nginx/cmccdb-frontend.conf <<'NGINX'
location / {
    root /app/cmccdb-interface/vue;
    index index.html;
    try_files $uri $uri/ /index.html;
}
NGINX
fi

gunicorn_args=(--workers 2)
if truthy "$backend_dev"; then
  for package in "$dev_src/cmccdb-interface/cmccdb_interface" "$dev_src/cmccdb-schema/cmccdb_schema"; do
    if [ ! -f "$package/__init__.py" ]; then
      echo "CMCCDB_DEV_BACKEND: no Python package at $package; mount your copy there" >&2
      exit 1
    fi
  done
  # the mounted copies come before the image's (gunicorn puts its --chdir first on the path)
  export PYTHONPATH="$dev_src/cmccdb-interface:$dev_src/cmccdb-schema${PYTHONPATH:+:$PYTHONPATH}"
  export CMCCDB_STANDALONE_DIR=${CMCCDB_STANDALONE_DIR:-/app/cmccdb-interface/cmccdb_interface/standalone}
  export CMCCDB_DEV_ENDPOINTS=${CMCCDB_DEV_ENDPOINTS:-true}
  # polling, for the same reason as the front end's
  gunicorn_args+=(--chdir "$dev_src/cmccdb-interface" --reload --reload-engine poll)
  echo "back end: code from $dev_src, reloaded when it changes; /api/dev endpoints: $CMCCDB_DEV_ENDPOINTS"
fi

# Start nginx server.
nginx -g 'daemon off;' &

# Start gunicorn.
LOG_FORMAT='GUNICORN %(t)s %({user-id}o)s %(U)s %(s)s %(L)s %(b)s %(f)s "%(r)s" "%(a)s"'
exec gunicorn cmccdb_interface.interface:app \
  --bind unix:/run/gunicorn.sock \
  "${gunicorn_args[@]}" \
  --access-logfile - \
  --access-logformat "${LOG_FORMAT}"
