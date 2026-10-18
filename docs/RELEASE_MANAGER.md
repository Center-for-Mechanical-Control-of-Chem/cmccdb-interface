# Preview releases, data batches, and promotion

This is an operator draft. The offline tests cover orchestration and Git boundaries;
the real container/database rehearsal must pass before deploying it. The first
rehearsal uses synthetic data and separate containers, never the live preview/main
databases. Do not test a public cutover on the live site first.

## Three separate operations

1. Deploy committed interface/schema revisions to **preview** with the existing
   `update_backend.sh`. Use `--build-target production` to test the built interface.
   The image must include this patch's release-control and release-data modules.
2. `release_manager.py prepare` freezes that tested preview release into a fresh
   candidate PostgreSQL cluster and a read-only web service. Main keeps serving
   users throughout preparation. Preview is briefly stopped for consistent
   `cmcc`/`staging` snapshots and original-file capture, then restarted.
3. Review the candidate, create one local accepted-data Git commit, then promote
   the candidate with the reviewed manifest's SHA-256. Publishing that Git commit
   is a separate explicit operation.

The manager runs with host Python 3.9+ and the existing engine account/storage
configuration. Its database operations run in the image's Python 3.11 environment.
The earlier `update_backend.sh` still requires host Python 3.11+; the inspected dev
host currently has Python 3.9 and lacks those earlier deployment modules. The
self-contained rehearsal does not require upgrading the host Python.

## Preview isolation and existing files

The compose patch removes live source mounts, the Node development server, dev
endpoints, SSH keys and the unused port 91 mapping. Development remains in the
existing dedicated dev stack. Preview gets `/home/cmccdb-preview-data` and
`/home/cmccdb-preview-tmp`; main retains its existing paths. Automatic preview Git
backups are disabled. Save/copy existing preview contributions and auxiliary files
into the separate preview folders before deploying that compose change. Do not
move or delete files from the shared old folders: main may still need them.

Use the completed updater release's saved Compose configuration for restarts.
Do not use the generic pull/restart scripts for a frozen release.

## Persistent proxy configuration

The proxy compose patch gives Nginx a named DNS-enabled network
(`cmccdb-public-proxy`, overridable with `CMCCDB_PROXY_NETWORK`) and a persistent
writable config file (`/home/cmccdb-proxy-runtime/nginx.conf`, overridable with
`CMCCDB_PROXY_CONFIG`). Seed that file **from the current running proxy** before
recreating the proxy with the new compose definition. Keep a backup outside the
source repositories. The manager refuses a proxy without this persistent mount.

After reviewing the proxy change, an operator can seed it with:

```sh
mkdir -p /home/cmccdb-proxy-runtime
podman exec <current-proxy-container> cat /etc/nginx/nginx.conf \
  > /home/cmccdb-proxy-runtime/nginx.conf
```

Validate the file, then perform the reviewed proxy recreation separately. Do not
run this against an already-promoted proxy with an old repository config. Routing
updates after initial setup write this mounted file, test it with `nginx -t`, and
reload Nginx; they survive container recreation using this compose definition.

## Prepare a candidate

Use the **same archive root** as the backend updater. Both tools use its
`.locks/<cluster>.lock`, and the manager also locks its own operations. Direct
database maintenance clients must be paused for freeze/cutover; the manager refuses
connected clients rather than killing them. All operators must use the same root.

```sh
python3 scripts/release_manager.py --root /path/to/archives prepare \
  --preview-release /path/to/archives/<completed-preview-release> \
  --main-web <current-main-web-container> \
  --main-database <current-main-database-container> \
  --proxy-container <current-proxy-container> \
  --proxy-network cmccdb-public-proxy \
  --public-url https://mechanochemistry.chem.tamu.edu \
  --port 9086
```

The candidate reuses the exact tested interface **image ID** and preview database
image. No image is rebuilt during promotion. Image archives and source provenance
are retained. The candidate gets a new database volume/cluster, its own temporary
and contribution files, main's authentication settings, and no Git push credentials.
Database ports are not published. Only `127.0.0.1:9086` is published for inspection;
the proxy reaches the web through the named container network.

Preparation makes native restore-verified snapshots, restores both databases, and
checks schema, stored reactions, extensions, sequences and row inventories. It
preserves both main and preview's original data/temp files privately, merges
identical files, and blocks conflicting paths. Existing local attachment URLs are
resolved through the application's existing attachment resolver; missing or
ambiguous files block preparation. Custom auxiliary directories need a separately
specified migration plan. No live database is renamed, overwritten or dropped.

Preview must contain every main dataset and reaction ID in its corresponding
database, including private staging. Missing records block preparation. Changed
records are listed with before/after hashes in `review.json`; additions are listed
too. There is no automatic scientific-record merge or deletion approval. Reconcile
missing/conflicting records deliberately on preview before preparing a new release.

The candidate blocks uploads, deletion, maintenance and unknown routes while
allowing search, reads, attachment downloads and authentication. Its write gate is
checked on every request and fails closed when its control markers are missing.
Do not connect direct SQL writers to the candidate.

## Review and commit the data batch

Inspect `review.json`, browser search/reaction views and attachments, then:

```sh
python3 scripts/release_manager.py --root /path/to/archives commit-data \
  /path/to/archives/cmccdb-release-<id> \
  --data-repo /home/cmccdb-data \
  --name 'Your name' --email 'your.email@example.com' \
  --message 'CMCCDB accepted data release <id>'
```

This clones the local data repository into the private release folder, creates a
`release/<id>` branch, and commits only `releases/<id>/` in that clone. The original
checkout, its uncommitted files, and remote branches are untouched. It makes no
network call and never pushes. No secrets, SQL dumps, private staging data or
rejected inputs enter the public export.

The accepted export contains complete canonical `.pb` and `.pbtxt` datasets,
embedded auxiliary bytes, referenced local attachments, the schema descriptor,
and a checksummed manifest. Original XLSX files and other input material are retained
in private input archives and runtime directories; they are not automatically
published to Git because they can include rejected/private submissions. This is a
database-derived data release rather than `git add -A` over the shared upload folder.

The printed local data commit is recorded in the release journal. If publication
is wanted, review that branch and explicitly publish it through your normal Git
workflow. The clone's `origin` points to the local input repository, not GitHub.

## Promote

```sh
python3 scripts/release_manager.py --root /path/to/archives promote \
  /path/to/archives/cmccdb-release-<id> \
  --approve <sha256-printed-by-prepare-and-matching-reviewed-review.json>
```

Promotion drains/stops the candidate and old main web services, checks that main's
database rows, identity and contribution files have not changed since preparation,
and checks the candidate against its exported state. Changed main data/files block
cutover and request an old-main restart. Prepare a new reconciled release; the
tool never silently overwrites newer production contributions.

It starts the frozen candidate, verifies its built frontend/API, installs/tests/
reloads the proxy config, and verifies that the public URL serves the expected
release in read-only mode. Only then does it enable writes and record the current
main pointer. The old main database and stopped backend remain available together.

There is a main availability window during final drain, full inventory/file checks
and routing. Its duration must be measured in the server rehearsal with realistic
data; this draft does **not** promise zero downtime or seconds for large databases.
Build/import/restore work happens while main stays online. A later application
write gate on the old main could preserve reads through the final verification,
but this draft does not assume old images already support that gate.

Failures before enabling writes request restoration of the old route/main web.
Failures around/after activation hold the new route and report uncertainty; never
automatically roll back after the candidate may have accepted contributions.
An operator must reconcile those contributions before any later reversal. Failed
attempts retain evidence and require a fresh preparation or deliberate recovery.

## Ongoing operation

`status <release-folder>` prints a concise, non-secret release summary. Private
`release.private.json` records container IDs, exact images, phase, snapshots, data
commit and recovery state; `current-main.private.json` points to the active release.
Use the recorded active web/database IDs and upstream for the next promotion.
After the first promotion, main is the prepared deployment, not the old base
Compose project's `web`; do not run generic old main restart/update commands.

Restart an active candidate with its own `compose.private.json` and recorded project.
Retain `control/writable` and the absence of `control/read-only`. All candidate
volumes, files, config and credential mounts are required. Preserve old stacks,
archives and snapshots off-host too. PostgreSQL/RDKit version upgrades and host role
recovery are separate operations. No cleanup or destructive rollback is automatic.
