# Batch XLSX re-submission and the initial migration

The first backend migration can replay a folder of original XLSX contributions through the new parser into fresh databases. It does not require migration helpers or `/opt/venv` in the old backend. It keeps the old database container/image/volume, archives old images/source, and retains every old logical database after promotion. Only `main` and `preview` production deployments are supported; all dev checks from the updater still apply.

## First run on preview

Apply/commit this patch with the new backend and schema changes, then fetch candidate commits on the deployment host without checking new schema code out into a running preview source mount. The candidate refs must include this patch's new Python modules and snapshot support. Use the same rootless Podman account and exported `CONTAINERS_STORAGE_CONF` as the existing stack.

From `cmccdb-interface`, first run the read-only deployment preflight:

```sh
bash update_backend.sh preview --plan \
  --resubmit-folder /home/migration-xlsx/main \
  --staging-resubmit-folder /home/migration-xlsx/staging \
  --uploader-name 'Your name' --uploader-email 'your.email@example.com'
```

This verifies the existing deployment/cluster and folder availability; it does not parse workbooks using the old parser or create databases. The actual replay uses the new candidate image:

```sh
bash update_backend.sh preview --build-target preview \
  --interface-ref origin/cmcc --schema-ref origin/cmcc \
  --resubmit-folder /home/migration-xlsx/main \
  --staging-resubmit-folder /home/migration-xlsx/staging \
  --uploader-name 'Your name' --uploader-email 'your.email@example.com'
```

Use `main --build-target preview` to test that image target against main, or `main --build-target production` for a normal main release. These are separate deployment choices. A nonempty existing `staging` database requires its own folder; an empty staging database can omit the staging folder and gets a fresh empty schema. To replay the same contributions into both databases, explicitly supply the same folder for both options.

The default archive location is `../archives/<UTC-date>-<target>-<id>`; `--archive-root` or `CMCCDB_ARCHIVES` can select another consistent local path. No GitHub upload, commit or push is performed by XLSX replay, including imports to main. XLSX parsing and storage use the established constructor, validation, attachment and ORM code directly in an operator CLI.

## Folder contents and attribution

XLSX discovery is recursive and case insensitive. Excel lock files beginning `~$` are ignored. Symlinks, escaping paths and contributions exceeding the existing 5 MB upload limit are rejected. Workbook sheet sizes, multiple worksheets and different header blocks use the existing parser.

```text
main/
  paper-one.xlsx
  paper-one.files/
    spectrum.csv
    image.png
  another-paper/
    paper-two.xlsx
  batch.json                    optional per-file settings
```

For each workbook, `<workbook-stem>.files/` supplies auxiliary files. The usual limit of five attachments, each at most 5 MB, applies. References to local files must resolve to supplied attachments; dangling references are reported instead of silently losing their data. External URLs are left intact. Do not put unrelated files into the sidecar folder.

An optional `batch.json` supplies per-file creator attribution, dataset names, old dataset IDs and auxiliary paths. All paths are relative to the input root, and auxiliary mapping keys are basenames:

```json
{
  "files": {
    "paper-one.xlsx": {
      "dataset_name": "Paper one",
      "uploader_name": "Original uploader",
      "uploader_email": "uploader@example.com",
      "dataset_id": "cmcc_dataset-0123456789abcdef0123456789abcdef",
      "auxiliary": {
        "spectrum.csv": "aux/spectrum.csv"
      }
    }
  }
}
```

The explicit auxiliary map takes precedence over automatic sidecar discovery. Workbook author/provenance fields are retained; creator name/email defaults fill missing fields as in normal contributions. Without an explicit legacy ID, the dataset ID is the original XLSX MD5, matching the normal contribution constructor. Reaction IDs follow the established constructor too.

Re-saving an XLSX changes its bytes and can change its default dataset/reaction IDs. If an original file was corrected or renamed after submission, map its original dataset ID explicitly and check the coverage report. The script never guesses a correspondence between scientific records. This is a re-import through the new parser, so fixes may change reaction content or add previously missed rows; it is not a byte-identical SQL migration. Missing creator fields receive the migration attribution/time, while the old database and native backups retain the original records. Contributions whose original data are not represented by XLSX, including separate dataset-reference collections, need an explicit representation/import plan; coverage blocks silently dropping their IDs.

## Sequence and recovery

1. Archive the exact legacy database/backend images and effective old source, freeze the candidate repositories and input folders, and build a unique candidate image while the old backend remains running.
2. Create migration-owned `cmccdb_import_<UUID>` databases with the new schema. Parse/validate every workbook and embed attachments. Import one file per SQL transaction, rebuilding normal ORM/RDKit indexes; verify complete dataset/protobuf equality before committing. Valid files can finish while others fail, but failures block promotion.
3. Once **both** application database replays succeed, stop the selected old backend. Pause other connected clients too; the script never terminates them.
4. Using the candidate's native PostgreSQL tools, dump each legacy database and restore it into an isolated verification copy. Generic table/row/extension/sequence inventories work without old ORM helpers. For an untracked legacy schema, `schema.pb` is empty and the manifest explicitly says to use archived old source; no new descriptor is substituted for the old one.
5. Require every old dataset ID and reaction ID to exist in its corresponding import database. Missing IDs produce `legacy-coverage.json` and block cutover. Verify all committed replay artifacts against the actual imported data again, and compare the legacy table inventories to their pre-change backups. Changes after backup block promotion.
6. Connect to the administrative `postgres` database and rename all database pairs in **one transaction**: old `cmcc`/`staging` become `cmccdb_legacy_<name>_<migration UUID>`, and their import databases become `cmcc`/`staging`. Expected database OIDs and the absence of other clients are checked; failures roll back all renames. Database ownership/creation privileges are required. See [PostgreSQL ALTER DATABASE](https://www.postgresql.org/docs/current/sql-alterdatabase.html).
7. Start only the new immutable backend and check its real API plus stored data. Publish native snapshot IDs to the backup API store. Keep old databases, restore copies, image archives, source, input XLSX files and reports; nothing is dropped or pruned.

Failures before a promotion attempt leave the old database names untouched and request an old-backend restart if it was stopped. Failures or interruptions after a promotion attempt hold the backend stopped, because the rename transaction may already have committed. Inspect `release.json`, `replay/initial.json`, actual database OIDs/names and backups before recovery. No automatic destructive rollback occurs.

## Retry failed files

Each archive contains `replay/batch-cmcc.json`, `batch-staging.json`, compiled protobuf artifacts and a durable `initial.json` ownership receipt. Per-file statuses are `invalid`, `failed`, `imported` or `already_present`, with an error and recommended fix when needed. Reports bind the deployment, cluster, import database, source fingerprints and fixed creation time.

Correct rejected files/attachments in your original input folders, then resume a **pre-promotion** archive using the same creator defaults and candidate schema:

```sh
bash update_backend.sh preview --build-target preview \
  --interface-ref origin/cmcc --schema-ref origin/cmcc \
  --resubmit-folder /home/migration-xlsx/main \
  --staging-resubmit-folder /home/migration-xlsx/staging \
  --uploader-name 'Your name' --uploader-email 'your.email@example.com' \
  --resume-import /absolute/path/to/archives/<failed-release>
```

The new attempt keeps the previous archive, reuses its owned import databases and receipts, and archives the new attempt separately. The old backend must be running for deployment preflight. Successful inputs cannot be changed or removed; their real stored protobufs are checked before marking them `already_present`. A lost receipt after a successful commit is reconciled against the actual database, so a retry does not duplicate it. Failed/invalid inputs may be corrected. After any promotion attempt, `--resume-import` is refused; inspect and complete recovery deliberately instead.

## Independent batch submission on a new-schema backend

The new backend also exposes an operator CLI module for an already prepared database. Run it in the production backend environment with a readable input mount and a persistent private report path:

```sh
/opt/venv/bin/python -m cmccdb_interface.database.batch_resubmit /incoming \
  --target preview --database cmcc --expected-cluster <system_identifier> \
  --report /app/backups/batches/paper-import.json \
  --uploader-name 'Your name' --uploader-email 'your.email@example.com'
```

The deployment plan prints the cluster identifier. This CLI requires a matching new schema and a matching cluster, obtains the existing migration lock, and makes a restore-verified native backup before its first writes. Existing conflicting dataset IDs are reported, never overwritten. Reuse the report path to resume a failed batch; use a fresh report for a new completed batch. Exit status is nonzero if any file failed. `--validate-only` parses the folder and writes artifacts/report without connecting to a database and does not require `--expected-cluster`.

Cluster roles/credentials and separately mounted external files still require their own disaster-recovery backups, as described in the main updater guide. The replay embeds supplied auxiliary bytes into the contributed protobufs.
