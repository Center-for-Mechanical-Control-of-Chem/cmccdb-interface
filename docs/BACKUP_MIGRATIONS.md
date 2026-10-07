# Database backups and schema migrations

The maintenance API takes PostgreSQL snapshots, verifies recovery into a new database, and applies compatible additive schema changes. An upload no longer upgrades an existing database as a side effect.

## Enablement and access

The routes are registered when Flask starts. Restart/rebuild the patched application to register them; reloading an individual `/api/dev` module does not register a new Flask blueprint.

Enable `CMCCDB_MAINTENANCE_API=true` explicitly in production, or use `CMCCDB_DEV_BACKEND=true` in development. Every operation requires the ordinary signed-in GitHub session and CMCC owner status. POST requests require JSON objects and the session-specific `X-CMCCDB-CSRF` token returned by `GET /api/maintenance`. An unsigned caller gets 401, a non-owner gets 403, and a disabled API returns 404.

Nginx exposes `/api/...`; Flask's direct routes have the `/client/api/...` prefix. The `database` query parameter accepts `cmcc`, `staging`, and generated `cmccdb_restore_<32 hex digits>` names for which this service has saved a successful restore-verification record. Arbitrary database names and restore destinations are rejected.

## Routes

| Method and URL | Request / result |
| --- | --- |
| GET `/api/maintenance` | Obtain the CSRF token. Response is marked `no-store`. |
| GET `/api/migration?database=staging` | Read-only plan: SQL, blockers, compatibility, descriptor hashes, fingerprint and `required`. |
| POST `/api/backup?database=staging` | `{}` queues a snapshot. `{"record_baseline":true}` also records the old installed descriptor, provided that its ORM matches the database. |
| GET `/api/maintenance/jobs/<job UUID>` | Poll `queued`, `running`, `complete`, or `failed`; a completed job includes its result. |
| GET `/api/backup/<snapshot UUID>` | Check the dump and descriptor checksums and return the manifest. |
| GET `/api/backup/<snapshot UUID>/download` | Download a ZIP with `database.dump`, `schema.pb`, and `manifest.json`. |
| POST `/api/backup/<snapshot UUID>/restore` | `{}` queues restoration into a fresh, generated database and compares all table row hashes/counts, extensions, sequence names and serial-ID sequence safety. |
| POST `/api/migration?database=staging` | `{"fingerprint":"<current preview fingerprint>"}` applies the current compatible plan, or returns `{"updated":false,"required":false,"snapshot_id":null}` without DDL or a new backup. |

Use a fresh UUID in `Idempotency-Key` for each intended POST operation. Retry the same operation with the same key after a connection interruption: it returns the same job, rather than launching another backup, restore, or migration. Reusing a key with a different request returns 409. Long operations run as fixed maintenance workers, not inside the HTTP request timeout; no arbitrary command execution is exposed. Status and logs are persisted alongside snapshots. Interrupted workers are reported as failed and are never automatically replayed.

## First deployment to an existing database

1. Deploy the migration support in `cmccdb-schema` and the maintenance API in `cmccdb-interface` while keeping the **old proto and its generated wrappers** installed. Rebuild/restart the app. Install the PostgreSQL client tools and mount the persistent backup directory.
2. For both databases, create a baseline backup with `record_baseline:true`. Download it and run the restore operation. Keep the backup and its manifest outside the deployment host too.
3. Deploy the new proto/generated wrappers and restart the app. Preview the migration. Review its SQL and blockers before POSTing its fingerprint.
4. The migration takes an exclusive advisory lock, rechecks the plan, creates a consistent pre-change backup and **actually restores and verifies a separate copy before DDL**. It applies the SQL, records the descriptor/snapshot ID, and checks the resulting schema in one transaction. Backup/restore failure, a stale plan, a lock conflict, or failed DDL leaves the source schema unchanged.
5. Preview again. A synchronized database reports `required:false`, empty SQL and no blockers. Repeated migration calls do no DDL and create no backup. A compatible descriptor-only addition can update the descriptor history without rewriting data or requiring SQL; recording it ensures future removals are checked.

An untracked database that already needs SQL is blocked. Do not pretend the new descriptor is its old baseline. Record the baseline with the old matching code first. Fresh databases are initialized and tracked normally.

The extruder update needs two operations: add nullable `cmccdb.flow_rate.mechanochemistry_conditions_id`, then add its cascading foreign key to `cmccdb.mechanochemistry_conditions.id`. Existing frequency/RPM fields, reactions, and raw protobufs are preserved. Optional field additions preserve protobuf wire compatibility; field removal, renaming, renumbering, type/presence changes and removal/renumbering of enum values are blocked. See [Protobuf schema-update guidance](https://protobuf.dev/programming-guides/proto3/#updating).

The planner covers additive nullable columns, tables, enums and their foreign keys. It blocks destructive or ambiguous changes, including required new columns and changed/removed field types. This is not a general data-transformation engine: renames, backfills, required fields, changed scientific meaning, PostgreSQL major upgrades, and RDKit extension upgrades require a separately reviewed migration and rehearsal. Never reuse a protobuf field number.

## Storage and PostgreSQL clients

Set `CMCCDB_SNAPSHOT_DIR=/app/backups`; the compose stacks mount separate persistent backup volumes. Preserve these volumes when rebuilding. Do not use `compose down --volumes` as a restart procedure. Development without a configured path uses `.snapshots` under the mounted backend source. Treat backups as private database copies; UUID directories and job files are private to the app's filesystem user.

When switching an existing dev instance from the fallback `.snapshots` directory to the new `/app/backups` volume, retain the old directory and copy its complete UUID snapshot directories and verification records into the persistent store with the same app ownership and private permissions. Keep downloaded ZIPs separately too. Changing the storage setting alone does not move earlier snapshots or their restore records.

The Dockerfile installs PostgreSQL client 16 from the [official signed PGDG repository](https://www.postgresql.org/download/linux/debian/). This supports the configured PostgreSQL 16 local stack and avoids PostgreSQL 17's unconditional `SET transaction_timeout`, which older servers cannot execute during restoration. For a PostgreSQL 17 server, build with `--build-arg PG_CLIENT_MAJOR=17` and rehearse recovery on an appropriate destination. `pg_dump` must be at least as new as the source server. A mismatched client or extension cannot silently pass the mandatory restore check.

The current development server is PostgreSQL 12.3 with RDKit 3.8. It was tested with checksum-verified official Debian PostgreSQL 15.19 client binaries in its mounted development source. That temporary client provisioning is a test facility; the production image installs its own clients. The new Docker image itself was not built in this session.

## What the backup contains and recovery boundaries

The dump uses PostgreSQL's custom format and an exported repeatable-read snapshot. All user-table rows are hashed under that same snapshot, including original protobuf bytes and embedded auxiliary-file bytes. The ZIP also saves the protobuf descriptor, checksums, extension versions, table inventories and sequence names. Custom-format archives are intended for `pg_restore`; see [PostgreSQL pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html) and [pg_restore](https://www.postgresql.org/docs/current/app-pgrestore.html).

Database snapshots include schemas, tables, indexes, constraints, sequences, extensions, data and large objects. Cluster roles, credentials, app source, the Git repository and files that were never embedded in the database need separate backups. Restore uses `--no-owner --no-acl`; deployment role grants must be reapplied deliberately at cutover. Extension packages must be available at matching versions; extension verification fails if recovery changes them.

The restore API accepts only complete, checksummed snapshots already in its private store and always creates a new database. It never drops or overwrites `cmcc`/`staging`, accepts `--clean`, terminates their sessions, or performs a cutover. Failed isolated restores are retained for diagnosis. Successful isolated copies can be previewed/migrated with the same API before a separately planned cutover. A snapshot taken after a migration cannot make an older app understand the added fields; use matching code/descriptors when restoring an older snapshot.

For disaster recovery from an externally stored ZIP, verify its manifest's SHA-256 values, extract it to a private directory, and restore into a **new** database on a compatible server. For example, after setting ordinary PostgreSQL connection settings and choosing a new name:

```sh
createdb --template=template0 cmccdb_recovery_review
pg_restore --single-transaction --exit-on-error --no-owner --no-acl --no-tablespaces \
  --dbname=cmccdb_recovery_review database.dump
```

Do not run this over an existing database. Check the tables, stored reactions/attachments, sequences, extensions and application behavior before cutover. These archives come from your own database; PostgreSQL restoration executes database definitions and should not be used on untrusted third-party dumps. Save manifests and successful verification records with external backups.
