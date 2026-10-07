"""Validated XLSX replay with per-file transactions and durable, resumable reports.

Use the established spreadsheet constructor, attachment handler, validations and
ORM ingestion. This operator CLI does not contact GitHub or bypass a web login.
"""
import argparse
import fcntl
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager


@contextmanager
def report_lock(path):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.with_name(path.name + '.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Another process owns this replay report') from error
        yield


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('w') as stream:
        temporary.chmod(0o600)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def guard(target):
    if target not in {'main', 'preview'}:
        raise ValueError('Only main and preview production deployments are supported')
    if any(os.getenv(key, '').lower() in {'1', 'true', 'yes', 'on'} for key in
           ['CMCCDB_DEV_BACKEND', 'CMCCDB_DEV_FRONTEND', 'CMCCDB_DEV_FRONTEND_PROXY']):
        raise ValueError('Batch migration is never permitted on dev')


def input_file(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root):
        raise ValueError('Input path escapes the XLSX folder: ' + relative)
    if any(parent.is_symlink() for parent in [path, *path.parents] if parent != root.parent):
        raise ValueError('Input symlinks are not supported: ' + relative)
    if not path.is_file():
        raise ValueError('Input file is missing: ' + relative)
    from .datasets import MAX_UPLOAD_BYTES
    if path.stat().st_size > MAX_UPLOAD_BYTES:
        raise ValueError('Input exceeds the contribution limit of 5 MB: ' + relative)
    return path


def recommendation(error):
    text = str(error).lower()
    if 'auxiliary' in text or 'local file' in text:
        return 'Supply the referenced file in <workbook-stem>.files/ or batch.json auxiliary mapping.'
    if 'already exists' in text or 'conflict' in text:
        return 'Review the existing dataset and manifest IDs; this process never overwrites a contribution.'
    if 'unit' in text or 'enum' in text:
        return 'Use the current schema field names and supported units in the workbook headers.'
    if 'name' in text or 'email' in text:
        return 'Supply valid contributor attribution in the workbook, manifest or CLI defaults.'
    return 'Correct the reported workbook/template field and rerun with the same report path.'


def _prepare(folder, report_path, uploader_name, uploader_email, target):
    """Compile every file; successful entries are immutable when a report is reused."""
    guard(target)
    if not uploader_name.strip() or not uploader_email.strip():
        raise ValueError('Uploader name and email are required')
    original = Path(folder)
    if original.is_symlink():
        raise ValueError('XLSX folder must not be a symlink')
    root = original.resolve()
    if not root.is_dir():
        raise ValueError('XLSX folder is missing')
    report_path = Path(report_path)
    if report_path.resolve().is_relative_to(root):
        raise ValueError('Store the replay report and artifacts outside the input folder')
    previous = json.loads(report_path.read_text()) if report_path.exists() else {}
    if previous and (previous.get('format') != 'cmccdb-xlsx-replay-v1' or previous.get('target') != target):
        raise ValueError('Report belongs to another replay or deployment target')
    record = {**previous, 'format': 'cmccdb-xlsx-replay-v1', 'target': target,
              'created_at': previous.get('created_at', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')),
              'folder': str(root), 'files': {}, 'ok': False}
    artifacts = report_path.parent / (report_path.stem + '.protos')
    artifacts.mkdir(mode=0o700, parents=True, exist_ok=True)
    manifest_path = root / 'batch.json'
    manifest = json.loads(input_file(root, 'batch.json').read_text()) if manifest_path.exists() else {}
    if set(manifest) - {'files'} or not isinstance(manifest.get('files', {}), dict):
        raise ValueError('batch.json must contain only a files mapping')
    options = manifest.get('files', {})
    paths = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Input symlinks are not supported: ' + str(path.relative_to(root)))
        if path.is_file() and path.suffix.lower() == '.xlsx' and not path.name.startswith('~$'):
            paths.append(path)
    if not paths:
        raise ValueError('Folder has no XLSX contributions')
    actual = {str(path.relative_to(root)) for path in paths}
    if set(options) - actual:
        raise ValueError('Manifest lists missing XLSX files: ' + ', '.join(sorted(set(options) - actual)))
    committed = previous.get('committed', {})
    removed = (set(committed) - actual) | {name for name, entry in previous.get('files', {}).items()
               if entry.get('status') in {'imported', 'already_present', 'validated'} and name not in actual}
    if removed:
        raise ValueError('A committed input was removed; keep it for resume: ' + ', '.join(sorted(removed)))
    from cmccdb_schema.dataset_constructor import DatasetConstructor
    from cmccdb_schema import validations
    from . import datasets
    identities = {}
    for path in paths:
        name = str(path.relative_to(root))
        entry = {'status': 'invalid', 'path': name}
        try:
            config = options.get(name, {})
            allowed = {'dataset_id', 'dataset_name', 'uploader_name', 'uploader_email', 'auxiliary'}
            if not isinstance(config, dict) or set(config) - allowed:
                raise ValueError('Unknown manifest options for ' + name)
            body = input_file(root, name).read_bytes()
            files = config.get('auxiliary', {})
            if not isinstance(files, dict):
                raise ValueError('Auxiliary mapping must map basenames to relative input paths')
            if not files:
                sidecar = path.with_suffix('.files')
                if sidecar.is_dir():
                    files = {item.name: str(item.relative_to(root)) for item in sorted(sidecar.iterdir()) if item.is_file()}
            attachments = {filename: input_file(root, relative).read_bytes() for filename, relative in files.items()}
            identity = config.get('dataset_id', 'cmcc_dataset-' + hashlib.md5(body).hexdigest())
            if not re.fullmatch(r'cmcc_dataset-[0-9a-f]{32}', identity):
                raise ValueError('Manifest dataset_id must be cmcc_dataset- followed by 32 lowercase hex digits')
            contributor = {'name': config.get('uploader_name', uploader_name),
                           'email': config.get('uploader_email', uploader_email)}
            if not all(isinstance(value, str) and value.strip() for value in contributor.values()):
                raise ValueError('Contributor name and email must be nonempty strings')
            fingerprint = {'xlsx_sha256': hashlib.sha256(body).hexdigest(), 'options': config,
                           'uploader': contributor, 'auxiliary_sha256': {
                               key: hashlib.sha256(value).hexdigest() for key, value in attachments.items()}}
            old = previous.get('files', {}).get(name, {})
            saved = committed.get(name) or (old.get('fingerprint') if old.get('status') in {'imported', 'already_present', 'validated'} else None)
            if saved is not None and fingerprint != saved:
                raise ValueError('Committed input changed; use a separate reviewed contribution: ' + name)
            # The established parser dispatches on a lowercase .xlsx suffix.
            # Compile the exact hashed bytes from a private normalized copy.
            artifact_name = hashlib.sha256(name.encode()).hexdigest() + '.pb'
            normalized = artifacts / (artifact_name + '.source.xlsx')
            normalized.write_bytes(body)
            normalized.chmod(0o600)
            dataset = DatasetConstructor.enumerate_spreadsheet(normalized,
                name=config.get('dataset_name', path.stem), id=identity.removeprefix('cmcc_dataset-'),
                optional_fields={'record_created': {'time': {'value': record['created_at']}, **contributor}})
            if not dataset.reactions:
                raise ValueError('XLSX contribution has no reactions')
            datasets.attach_auxiliary_files(dataset, attachments)
            for data in datasets.iter_data(dataset):
                from urllib.parse import urlsplit
                if data.WhichOneof('kind') == 'url' and not urlsplit(data.url).scheme:
                    raise ValueError('Unresolved local file reference: ' + data.url)
            validations.validate_datasets({name: dataset})
            proto = dataset.SerializeToString(deterministic=True)
            proto_hash = hashlib.sha256(proto).hexdigest()
            if identity in identities:
                raise ValueError('Duplicate dataset ID in folder conflicts with ' + identities[identity])
            identities[identity] = name
            artifact = artifacts / artifact_name
            artifact.write_bytes(proto)
            artifact.chmod(0o600)
            entry.update(status='validated', dataset_id=identity, reactions=len(dataset.reactions),
                         fingerprint=fingerprint, proto_sha256=proto_hash, artifact=artifact_name)
        except Exception as error:
            entry.update(error=str(error)[:4000], recommended_fix=recommendation(error))
        record['files'][name] = entry
        write_json(report_path, record)
    record['validation_complete'] = True
    record['ok'] = all(entry['status'] == 'validated' for entry in record['files'].values())
    write_json(report_path, record)
    return record


def _apply(folder, report_path, uploader_name, uploader_email, target, database,
          expected_cluster, *, backup=True):
    """Resume safely even if a commit succeeded before its report was written."""
    guard(target)
    if database not in {'cmcc', 'staging'} and not re.fullmatch(r'cmccdb_import_[0-9a-f]{32}', database):
        raise ValueError('Only application databases or migration-owned import databases are supported')
    report_path = Path(report_path)
    previous = json.loads(report_path.read_text()) if report_path.exists() else {}
    binding = {'cluster': str(expected_cluster), 'database': database}
    if previous.get('binding') and previous['binding'] != binding:
        raise ValueError('Report belongs to another database or PostgreSQL cluster')
    record = _prepare(folder, report_path, uploader_name, uploader_email, target)
    record['binding'] = binding
    write_json(report_path, record)
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session
    from cmccdb_schema.orm import database as orm_database, schema_updates
    from cmccdb_schema.orm.mappers import Base, Mappers, to_proto
    from cmccdb_schema.proto import dataset_pb2
    from . import manage, snapshots
    engine = manage.get_engine(database_name=database)
    try:
        with engine.connect() as connection:
            actual = str(connection.scalar(text('SELECT system_identifier FROM pg_control_system()')))
        if actual != str(expected_cluster):
            raise ValueError('Connected to another PostgreSQL cluster')
        with schema_updates.migration_lock(engine) as connection:
            preview = schema_updates.plan(connection, Base.metadata)
            if preview['required'] or not preview['compatible']:
                raise ValueError('Batch replay requires a database already prepared with the new schema')
            cartridge = bool(connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='rdkit')")))
            connection.commit()
            if backup and any(entry['status'] == 'validated' for entry in record['files'].values()):
                if previous.get('snapshot_id'):
                    snapshot = snapshots.manifest(previous['snapshot_id'])
                    if not snapshot.get('restore_verification', {}).get('verified'):
                        raise ValueError('Previous replay backup did not pass restore verification')
                    if snapshot['database'] != database:
                        raise ValueError('Previous replay snapshot belongs to another database')
                    record['snapshot_id'] = snapshot['id']
                else:
                    snapshot = snapshots.create_verified(engine, database, connection=connection)
                    record['snapshot_id'] = snapshot['id']
                write_json(report_path, record)
            artifacts = report_path.parent / (report_path.stem + '.protos')
            for name, entry in record['files'].items():
                if entry['status'] != 'validated':
                    continue
                try:
                    body = (artifacts / entry['artifact']).read_bytes()
                    if hashlib.sha256(body).hexdigest() != entry['proto_sha256']:
                        raise ValueError('Compiled dataset artifact checksum mismatch')
                    expected = dataset_pb2.Dataset.FromString(body)
                    with connection.begin(), Session(bind=connection) as session:
                        connection.execute(text("SET LOCAL lock_timeout='5s'"))
                        stored = session.scalar(select(Mappers.Dataset).where(Mappers.Dataset.dataset_id == expected.dataset_id))
                        status = 'already_present' if stored is not None else 'imported'
                        if stored is None:
                            orm_database.add_dataset(expected, session, rdkit_cartridge=cartridge)
                            session.flush()
                            stored = session.scalar(select(Mappers.Dataset).where(Mappers.Dataset.dataset_id == expected.dataset_id))
                        if to_proto(stored) != expected:
                            raise ValueError('Dataset already exists with conflicting data or attribution: ' + expected.dataset_id)
                        for reaction in stored.reactions:
                            from cmccdb_schema.proto import reaction_pb2
                            if to_proto(reaction) != reaction_pb2.Reaction.FromString(reaction.proto):
                                raise ValueError('Stored ORM/raw reaction protobuf mismatch')
                    entry['status'] = status
                    record.setdefault('committed', {})[name] = entry['fingerprint']
                except Exception as error:
                    entry.update(status='failed', error=str(error)[:4000], recommended_fix=recommendation(error))
                # Commit has finished before the durable receipt; retries inspect the DB.
                write_json(report_path, record)
    finally:
        engine.dispose()
    record['ok'] = all(entry['status'] in {'imported', 'already_present'} for entry in record['files'].values())
    record['counts'] = {status: sum(entry['status'] == status for entry in record['files'].values())
                        for status in ['imported', 'already_present', 'invalid', 'failed']}
    write_json(report_path, record)
    return record


def prepare(folder, report_path, uploader_name, uploader_email, target):
    guard(target)
    with report_lock(report_path):
        return _prepare(folder, report_path, uploader_name, uploader_email, target)


def apply(folder, report_path, uploader_name, uploader_email, target, database,
          expected_cluster, *, backup=True):
    guard(target)
    with report_lock(report_path):
        return _apply(folder, report_path, uploader_name, uploader_email, target,
                      database, expected_cluster, backup=backup)


def verify_receipts(report_path, database, expected_cluster):
    """Verify committed spreadsheet artifacts against the actual pre-cutover data."""
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session
    from cmccdb_schema.orm.mappers import Mappers, to_proto
    from cmccdb_schema.proto import dataset_pb2, reaction_pb2
    from . import manage
    report_path = Path(report_path)
    report = json.loads(report_path.read_text())
    if not report.get('ok') or report['binding'] != {'cluster':str(expected_cluster),'database':database}:
        raise ValueError('Replay has not completed for this database')
    engine = manage.get_engine(database_name=database)
    try:
        with engine.begin() as connection:
            connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            if str(connection.scalar(text('SELECT system_identifier FROM pg_control_system()'))) != str(expected_cluster):
                raise ValueError('Connected to another PostgreSQL cluster')
            with Session(bind=connection) as session:
                for entry in report['files'].values():
                    if entry['status'] not in {'imported', 'already_present'}:
                        raise ValueError('Replay includes an unsuccessful file')
                    body=(report_path.parent/(report_path.stem+'.protos')/entry['artifact']).read_bytes()
                    if hashlib.sha256(body).hexdigest()!=entry['proto_sha256']:
                        raise ValueError('Replay artifact checksum mismatch')
                    expected=dataset_pb2.Dataset.FromString(body)
                    stored=session.scalar(select(Mappers.Dataset).where(Mappers.Dataset.dataset_id==expected.dataset_id))
                    if stored is None or to_proto(stored)!=expected:
                        raise ValueError('Imported contribution changed before promotion: '+expected.dataset_id)
                    for reaction in stored.reactions:
                        if to_proto(reaction)!=reaction_pb2.Reaction.FromString(reaction.proto):
                            raise ValueError('Stored ORM/raw reaction protobuf mismatch')
                    session.expunge_all()
    finally:
        engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--target', choices=['main', 'preview'], required=True)
    parser.add_argument('--database', choices=['cmcc', 'staging'], default='cmcc')
    parser.add_argument('--expected-cluster', help='Required for writes; PostgreSQL system_identifier')
    parser.add_argument('--report', type=Path, required=True, help='Reuse this path to resume')
    parser.add_argument('--uploader-name', required=True)
    parser.add_argument('--uploader-email', required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args(argv)
    os.umask(0o077)
    if args.validate_only:
        result = prepare(args.folder, args.report, args.uploader_name, args.uploader_email, args.target)
    else:
        if not args.expected_cluster or not args.expected_cluster.isdigit():
            parser.error('--expected-cluster is required for writes')
        result = apply(args.folder, args.report, args.uploader_name, args.uploader_email,
                       args.target, args.database, args.expected_cluster)
    print(json.dumps({'ok': result['ok'], 'report': str(args.report), 'counts': result.get('counts')}))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
