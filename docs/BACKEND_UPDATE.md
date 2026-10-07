# Production backend updates

Run `bash update_backend.sh main` or `bash update_backend.sh preview` on the deployment host. This updates only the selected web service and migrates that cluster's existing application databases. It preserves the running database container, database image and data volume. The script refuses `dev`, dev-labeled containers, active dev backend/frontend switches, non-production logical database names, shared database persistence and a PostgreSQL cluster identity mismatch.

The optional preview **image build target** is independent of the deployment selection. Use `main --build-target preview` to test that image on main, or `preview --build-target preview` to test it on preview. The released backend uses its frozen image source and built frontend; live Python/Vue source mounts and dev endpoints are removed/disabled even when the image was built with the preview target. The old preview source mounts therefore cannot change the released backend before a future migration.

## Prerequisites

- Python 3.11 or newer on the deployment host. On the Mac workspace, the launcher uses the established native ARM environment automatically. On Linux, it uses `PYTHON` or `python3`.
- The same Podman/Docker engine account, storage configuration and Compose project that own the running deployment. For rootless Podman, retain your exported `CONTAINERS_STORAGE_CONF`; the script inherits it and never uses sudo or a separate engine store. Remote container engines are not supported because source/archive paths are host bind mounts.
- The previous backup/migration foundation must already be present in the **old running image/effective source**, with native `pg_dump` and `pg_restore` and `/opt/venv/bin/python`. The old schema must match its database. Preflight refuses an older image missing this support; deploy the foundation with the old proto first. It never invents an old baseline using new code.
- The application's PostgreSQL account needs the privileges already required for snapshots, isolated database creation/restoration and schema migration, plus reading `pg_control_system()` to prove cluster identity. With these compose stacks this is the existing PostgreSQL account; the script does not grant privileges.
- Free archive storage for both image saves, source and database backups; free database storage for retained rehearsal/restore copies. The script estimates a minimum archive requirement before stopping the backend. Keep the container engine's image-build cache storage available too.
- Pause other clients connected to the selected application databases for the maintenance window. The worker rejects other connected clients, and compares all existing rows after migration. It does not terminate their connections. Do not run other schema/deployment changes concurrently; all update invocations should use the same archive root.

Podman delegates Compose to its configured external provider. The script prefers `compose config --format json`; if the provider only outputs YAML, host PyYAML is required. It writes a complete resolved Compose model so provider-specific merge/reset tags are unnecessary. See [Podman Compose](https://docs.podman.io/en/stable/markdown/podman-compose.1.html) and [Docker Compose config](https://docs.docker.com/reference/cli/docker/compose/config/).

## Read-only check and update examples

From the deployed `cmccdb-interface` repository:

```sh
bash update_backend.sh preview --plan
bash update_backend.sh main --plan
```

`--plan` verifies the running service/container associations, cluster identity, installed schema and backup tools. It does not create archives, build images, stop services or run migrations.

Prefer fetching committed candidate revisions without changing the checkout that an old preview container has mounted. Both repositories currently have `origin/cmcc` as their remote default branch; substitute your intended existing branch/tag/commit if different:

```sh
git -C /home/cmccdb-interface fetch origin
git -C /home/cmccdb-schema fetch origin

# Test the preview build on the preview deployment.
bash update_backend.sh preview --build-target preview \
  --interface-ref origin/cmcc --schema-ref origin/cmcc

# The same build target also works against the main deployment.
bash update_backend.sh main --build-target preview \
  --interface-ref origin/cmcc --schema-ref origin/cmcc

# Normal main release, using the production image target.
bash update_backend.sh main --build-target production \
  --interface-ref origin/cmcc --schema-ref origin/cmcc
```

These commands are separate choices, not a sequence that must all be run. Fetching does not check out candidate files into the live preview mount. The script archives/builds the requested commits without changing either checkout. Commit the schema source and pipeline-generated wrappers together before selecting their revisions.

Without the two ref options, the script freezes the current checked-out source, including non-ignored untracked files and required generated wrappers. That mode is useful for a reviewed local patch, but do not pull new source into an old live preview mount before archiving it. If that has already happened and the old installed schema no longer matches the database, preflight deliberately stops with no deployment changes.

Use `--source-root /path/to/cmccdb-interface` for a separate candidate checkout; its schema repository must be a sibling. Use `--project-name <existing-project>` if the existing deployment has a custom Compose project name. These files must still describe the intended main/preview service and its credentials/data mounts; service/project/cluster checks must pass.

By default, archives are written to `../archives`, beside both repositories. For a local filesystem with suitable capacity/SELinux support:

```sh
bash update_backend.sh preview --archive-root /var/tmp/maboyer/cmccdb-production/archives
```

Set `CMCCDB_ARCHIVES` to use that path consistently on future runs. SELinux `:z` relabeling is used for the script's private bind mounts; the script does not disable SELinux to work around an unsuitable filesystem. Existing source symlinks or missing tracked files are rejected instead of silently producing an incomplete build context.

## Update sequence

1. Verify the existing deployment and old schema; acquire an exclusive host lock for that cluster.
2. Create a private UTC date-stamped directory such as `archives/2026-10-07T123000Z-preview-<id>`.
3. Save the exact old database and backend **images by image ID**, and archive their effective backend/schema source from the old container, including preview bind-mounted source. Freeze and hash the candidate source separately.
4. Build a uniquely tagged candidate image while the old backend is still running. No mutable old image tag is overwritten.
5. Stop only the selected web container. Using the old image plus archived old source, establish a matching descriptor baseline if needed, create a native PostgreSQL snapshot of each existing application database (`cmcc`, and `staging` when present), and restore/verify separate copies.
6. Using the candidate image, rehearse **all** planned migrations on those isolated copies. Check every old user-table column/row hash and every stored reaction's ORM/raw-protobuf equality. Incompatible or destructive plans are blocked by the existing migration engine.
7. Only after every rehearsal succeeds, migrate each live application database. Each required SQL migration also creates and restore-verifies its own fresh pre-change snapshot under the migration lock. A compatible no-DDL update is detected and does no SQL migration; compatible descriptor additions remain tracked.
8. Copy the new snapshot directories into a persistent, target-specific backup volume so the normal backup API can find their snapshot IDs. Offline copies remain in the date-stamped archive. Earlier backup volumes are retained too; preserve them if you need older API-created snapshots from before this first scripted release.
9. Replace only the selected web service with `--no-deps --no-build`. Verify its exact image ID, schema/data reconstruction and actual Nginx/Gunicorn/database API, then verify that the original database container/image/mounts are still unchanged.
10. Save checksums, health/migration evidence, a durable release journal and `archives/current-main.json` or `current-preview.json`.

There is a maintenance window after step 5. All application databases are rehearsed before any live DDL. PostgreSQL transactions are per database: if a later database migration fails after an earlier one committed, there is no fictional cross-database rollback.

## Archives and restarting a completed release

Each date-stamped folder contains:

```text
old-database-image.tar           exact database software image, not its data volume
old-backend-image.tar            exact old runtime and Python dependency image
old-source.tar.gz                effective old application/schema source
old-source/                     extracted source used for matching old-schema backups
candidate-source/               frozen candidate repositories used for the build
candidate-source-sha256.json     source hashes and commit provenance
snapshots/<UUID>/backup.zip      complete, checksummed, restore-verified snapshots
baseline-*.json                 old descriptors, rows and column inventories
rehearsal-*.json                 isolated migration verification
migration-*.json                 live migration/no-op results
health-*.json                    released backend checks
old-compose.private.json        previous resolved configuration
release-compose.private.json    exact new immutable deployment configuration
worker.private.env              private PostgreSQL connection configuration
release.json                    journal, IDs, phase and recovery state
CHECKSUMS.json                  archive file SHA-256 values
update.log                      private command/worker output
```

Directories are private and files containing credentials/configuration are private. Store archives outside the deployment machine too. Do not publish the private Compose/environment files or commit the archives to Git. Image archives retain software layers; live PostgreSQL data is recovered from the native dumps, not by loading an image. [Podman save/load documentation](https://docs.podman.io/en/latest/markdown/podman-save.1.html) describes the image archives.

The database snapshots cover application tables, schemas, indexes, constraints, sequences, extensions and large objects. Cluster roles/credentials and files on external mounts, including auxiliary contribution files under `cmccdb-data`, need separate disaster-recovery backups. This backend update preserves those existing mounts and the database container; its archives do not replace backups of the whole host.

For a routine restart after a completed update, use that release's **saved** Compose file and project, with its immutable image tag. The previous generic restart scripts use mutable image names/source mounts and should not be used to restart a scripted release:

```sh
podman compose --project-name <project-from-release.json> \
  --file /absolute/path/to/archives/<release>/release-compose.private.json \
  up --detach --no-deps --no-build web_preview
```

For main, the service is `web`. The database remains running. A future update rediscovers the running image and archives it before replacing it.

## Failure and recovery

Before a live migration attempt, failure requests a restart of the original stopped web container; the images/source/backups collected so far remain in the archive. After any live migration attempt, failure requests that the selected backend remain stopped. Inspect the journal, actual container state and SQL/health results before deciding how to recover. An interrupted migration may have committed even if its caller never received the result.

The script never overwrites a database with a backup, downgrades PostgreSQL, prunes images/volumes, drops the isolated restore copies, or switches back to old code after uncertain DDL. Recovery requires verifying a restored backup in a **new** database and a deliberate cutover with matching old source/image, or fixing the new backend and completing the release. Loading the saved old database image alone does not reverse a schema migration. Keep database major-version/RDKit-extension upgrades as separate, explicitly reviewed operations; this script updates the application backend only.

## Validation

23 local orchestration/security tests passed, covering both engines and both deployment targets, ordering of backups/rehearsals/live migrations, dev/shared-storage/project-mismatch refusal, archive capacity, frozen source/configuration, literal credential values, Git revision extraction without checkout changes, unsafe source-link refusal, and failure behavior before/after migrations. The preview build target was also exercised against main in the orchestration tests.

The exact worker also passed 12 real PostgreSQL checks on an isolated native ARM PostgreSQL 17 cluster: old-schema probes, restore-verified backups, rehearsal of the two additive extruder operations, live migrations, full row/protobuf comparisons, repeated no-ops, and wrong-cluster rejection for both target modes. Existing timestamps were tested with a non-UTC server timezone. Four synthetic template reactions per database were retained unchanged. The isolated cluster was stopped afterward; no deployed main, preview or dev container was touched.

Container build/start/Compose interactions were simulated locally because this Mac has no container engine available. A full container rollout has not been executed; the first operational run should be the preview deployment after its read-only preflight passes.
