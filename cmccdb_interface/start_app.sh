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
set -euo pipefail

if [ "${CMCCDB_LAUNCH_DEV_INTERFACE:-false}" = "true" ]; then
  curdir=$PWD
  cd /app/cmccdb-interface/dev
  dependency_hash=$(sha256sum package.json package-lock.json /app/cmccdb-schema/js/cmccdb-schema/package.json | sha256sum | cut -d ' ' -f 1)
  installed_hash=$(cat node_modules/.cmccdb-dependencies.sha256 2>/dev/null || true)
  if [ "$dependency_hash" != "$installed_hash" ]; then
    npm ci --no-audit --no-fund
    printf '%s\n' "$dependency_hash" > node_modules/.cmccdb-dependencies.sha256
  fi
  npm run serve -- --port=95 &
  cd "$curdir"
fi

# Start nginx server.
nginx -g 'daemon off;' &

# Start gunicorn.
LOG_FORMAT='GUNICORN %(t)s %({user-id}o)s %(U)s %(s)s %(L)s %(b)s %(f)s "%(r)s" "%(a)s"'
exec gunicorn cmccdb_interface.interface:app \
  --bind unix:/run/gunicorn.sock \
  --workers 2 \
  --access-logfile - \
  --access-logformat "${LOG_FORMAT}"
