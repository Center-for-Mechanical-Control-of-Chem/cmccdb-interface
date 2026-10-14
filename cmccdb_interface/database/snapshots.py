"""Native PostgreSQL snapshots, checksums and restore into a fresh database."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, text
from psycopg2 import sql

from cmccdb_schema.orm import schema_updates
from cmccdb_schema.orm.mappers import Base
from . import manage


def root():
    default = Path(__file__).parents[1] / '.snapshots' if os.getenv('CMCCDB_DEV_BACKEND', '').lower() in {'1', 'true', 'yes', 'on'} else Path('/app/backups')
    path = Path(os.getenv('CMCCDB_SNAPSHOT_DIR', str(default))).resolve()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def identifier(value):
    return str(uuid.UUID(value))


def allowed_database(database):
    if database in {'cmcc', 'staging'}:
        return True
    if not re.fullmatch(r'cmccdb_restore_[0-9a-f]{32}', database):
        return False
    for record in root().glob('*/restore-' + database + '.json'):
        try:
            identifier(record.parent.name)
            result = json.loads(record.read_text())
            if result.get('database') == database and result.get('verified') is True:
                return True
        except (ValueError, OSError):
            continue
    return False


def _directory(snapshot_id):
    return root() / identifier(snapshot_id)


def _atomic_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True))
    temporary.chmod(0o600)
    temporary.replace(path)


def tool(name):
    directory = os.getenv('CMCCDB_PG_BIN')
    # Optional verified client binaries in the mounted development source.
    development = Path(__file__).parents[1] / '.pg-tools' / 'usr/lib/postgresql/15/bin'
    result = str(Path(directory) / name) if directory else shutil.which(name)
    if not result and os.getenv('CMCCDB_DEV_BACKEND', '').lower() in {'1', 'true', 'yes', 'on'} and development.exists():
        result = str(development / name)
    if not result or not Path(result).is_file():
        raise ValueError('PostgreSQL client tools are missing; rebuild with postgresql-client or set CMCCDB_PG_BIN')
    return result


def environment():
    result = os.environ.copy()
    result['PGPASSWORD'] = manage.get_password()
    result['PGCONNECT_TIMEOUT'] = '10'
    result['PGOPTIONS'] = '-c timezone=UTC'
    libraries = Path(__file__).parents[1] / '.pg-tools/usr/lib/x86_64-linux-gnu'
    if libraries.exists() and os.getenv('CMCCDB_DEV_BACKEND', '').lower() in {'1', 'true', 'yes', 'on'}:
        result['LD_LIBRARY_PATH'] = str(libraries) + ':' + result.get('LD_LIBRARY_PATH', '')
    return result


def _run(arguments, timeout=3600):
    result = subprocess.run(arguments, env=environment(), capture_output=True, timeout=timeout)
    if result.returncode:
        # Neither connection strings nor credentials are command arguments.
        raise ValueError(result.stderr.decode(errors='replace')[-3000:])
    return result.stdout


def _connection_arguments(database):
    return ['--host', manage.get_host(), '--port', str(manage.get_port()),
            '--username', manage.get_user(), '--dbname', database, '--no-password']


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inventory(connection):
    """Hash every user-table row, including raw protobufs and auxiliary bytes.

    Sorted row hashes preserve duplicates and avoid relying on sequence/row order.
    A server-side cursor keeps memory bounded for large databases.
    """
    connection.execute(text("SET LOCAL timezone = 'UTC'"))
    inspector = inspect(connection)
    result = {}
    for schema in sorted(inspector.get_schema_names()):
        if schema == 'information_schema' or schema.startswith('pg_'):
            continue
        for table in sorted(inspector.get_table_names(schema=schema)):
            quote = connection.dialect.identifier_preparer.quote
            qualified = quote(schema) + '.' + quote(table)
            digest = hashlib.sha256()
            count = 0
            rows = connection.execution_options(stream_results=True).execute(text(
                f'SELECT md5(row_to_json(t)::text) AS hash FROM {qualified} AS t ORDER BY hash'))
            for (row_hash,) in rows:
                digest.update(row_hash.encode('ascii'))
                count += 1
            rows.close()
            connection.execution_options(stream_results=False)
            result[schema + '.' + table] = {'rows': count, 'sha256': digest.hexdigest()}
    return result


def _cartridge_context(connection):
    result = {'postgres_major': connection.scalar(text('SHOW server_version')).split('.')[0],
              'rdkit_extension': connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='rdkit'"))}
    # The supported legacy cartridge exposes rdkit_version; newer cartridges
    # additionally expose rdkit_toolkit_version. Record the actual function and
    # version, without issuing an undefined-function query in the snapshot.
    for function in ('public.rdkit_toolkit_version()', 'public.rdkit_version()'):
        if connection.scalar(text('SELECT to_regprocedure(:function) IS NOT NULL'), {'function': function}):
            result.update(rdkit_runtime_function=function,
                          rdkit_runtime=connection.scalar(text('SELECT ' + function)))
            return result
    raise ValueError('Cannot determine the RDKit binary runtime version')


def _reaction_cache_present(connection):
    return connection.scalar(text("""
        SELECT EXISTS(SELECT 1 FROM pg_attribute a
          JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='rdkit' AND c.relname='reactions' AND a.attname='reaction'
            AND a.atttypid=to_regtype('public.reaction') AND NOT a.attisdropped)
    """))


def _reaction_cache_rows(connection, *, compare_constructor=False):
    rebuilt = (', CASE WHEN reaction IS NULL THEN NULL ELSE '
               'public.reaction_send(public.reaction_from_smiles(reaction_smiles::cstring)) '
               'END AS reconstructed') if compare_constructor else ''
    return connection.execute(text('SELECT id, public.reaction_send(reaction) AS original' + rebuilt +
                                   ' FROM rdkit.reactions ORDER BY id')).mappings().all()


def _reaction_cache_hashes(rows, *, verify_constructor=False):
    result, seen = [], set()
    for row in rows:
        original = bytes(row['original']) if row['original'] is not None else None
        if verify_constructor:
            rebuilt = bytes(row['reconstructed']) if row['reconstructed'] is not None else None
            if original != rebuilt:
                raise ValueError('Native SMILES constructor does not reproduce reaction cache id ' + str(row['id']))
        if row['id'] in seen:
            raise ValueError('Duplicate reaction cache row identity')
        seen.add(row['id'])
        result.append({'id': row['id'], 'sha256': hashlib.sha256(original).hexdigest() if original is not None else None})
    return result


def _capture_reaction_cache(connection):
    """Prove that the established ORM constructor reproduces every cached object.

    The logical dump preserves the authoritative reaction_smiles. Cartridge text
    input can rebuild different query templates, and this legacy cartridge's
    binary receiver crashed in the development test. Record a reconstruction
    recipe only after byte-for-byte equality has been proved in the same MVCC
    snapshot as pg_dump; otherwise refuse the backup.
    """
    if not _reaction_cache_present(connection):
        return None
    return {'method': 'native-smiles-cache-v1', 'context': _cartridge_context(connection),
            'rows': _reaction_cache_hashes(_reaction_cache_rows(connection, compare_constructor=True),
                                           verify_constructor=True)}


def _restore_reaction_cache(connection, data):
    recipe = data.get('reaction_cache')
    if recipe is None:
        return
    if recipe.get('method') != 'native-smiles-cache-v1' or not _reaction_cache_present(connection):
        raise ValueError('Unsupported reaction cache restoration recipe')
    if _cartridge_context(connection) != recipe['context']:
        raise ValueError('Reaction cache restore requires the original PostgreSQL major and RDKit runtime')
    before = _reaction_cache_hashes(_reaction_cache_rows(connection))
    if [row['id'] for row in before] != [row['id'] for row in recipe['rows']]:
        raise ValueError('Restored reaction cache row identities differ from the snapshot')
    if [row['id'] for row in before if row['sha256'] is None] != [row['id'] for row in recipe['rows'] if row['sha256'] is None]:
        raise ValueError('Restored reaction cache null states differ from the snapshot')
    # This is the same constructor used by cmccdb_schema.orm.database to build
    # the search cache. Only isolated restored cached objects are updated; ids,
    # reaction_smiles, source protobufs and attachments stay from the dump.
    connection.execute(text('UPDATE rdkit.reactions SET reaction = '
                            'public.reaction_from_smiles(reaction_smiles::cstring) '
                            'WHERE reaction IS NOT NULL'))
    after = _reaction_cache_hashes(_reaction_cache_rows(connection))
    if after != recipe['rows']:
        raise ValueError('Reconstructed reaction cache bytes differ from the original snapshot')


def bootstrap(engine):
    """Record the installed descriptor only when it matches the existing database."""
    with schema_updates.migration_lock(engine) as connection:
        preview = schema_updates.plan(connection, Base.metadata)
        connection.commit()
        if preview['required'] or not preview['compatible']:
            raise ValueError('Baseline must be recorded using the old, matching schema before deploying updates')
        if not preview['tracked']:
            with connection.begin():
                schema_updates.record_version(connection)


def create(engine, database, connection=None, *, legacy=False):
    snapshot_id = str(uuid.uuid4())
    directory = _directory(snapshot_id)
    directory.mkdir(mode=0o700)
    dump = directory / 'database.dump'
    own = connection is None
    connection = engine.connect() if own else connection
    try:
        with connection.begin():
            connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            server = connection.scalar(text('SHOW server_version'))
            version = _run([tool('pg_dump'), '--version']).decode().strip()
            match = re.search(r'(\d+)\.\d+', version)
            if not match or int(match.group(1)) < int(server.split('.')[0]):
                raise ValueError(f'pg_dump must be at least PostgreSQL {server.split(".")[0]}')
            exported = connection.scalar(text('SELECT pg_export_snapshot()'))
            baseline = schema_updates._baseline(connection)
            # A legacy replay must never label its old database with the new proto.
            # The archived old source is the recovery source when no descriptor was tracked.
            payload = bytes(baseline) if baseline is not None else (b'' if legacy else schema_updates.descriptors())
            (directory / 'schema.pb').write_bytes(payload)
            (directory / 'schema.pb').chmod(0o600)
            _run([tool('pg_dump'), '--format=custom', '--snapshot', exported,
                  '--file', str(dump)] + _connection_arguments(database))
            dump.chmod(0o600)
            reaction_cache = _capture_reaction_cache(connection)
            tables = inventory(connection)
            extensions = dict(connection.execute(text('SELECT extname, extversion FROM pg_extension')).all())
            sequences = []
            for schema, name in connection.execute(text("SELECT schemaname, sequencename FROM pg_sequences WHERE schemaname NOT LIKE 'pg_%'")).all():
                quote = connection.dialect.identifier_preparer.quote
                # Sequence state is not MVCC; pg_dump saves it separately. Restore validates
                # sequence existence; nextval safety is checked against table ownership below.
                sequences.append(schema + '.' + name)
        _run([tool('pg_restore'), '--list', str(dump)])
        manifest = {'format': 'cmccdb-postgresql-custom-v1', 'id': snapshot_id,
                    'created_at': datetime.now(timezone.utc).isoformat(), 'database': database,
                    'server_version': server, 'pg_dump_version': version, 'extensions': extensions,
                    'dump_sha256': _digest(dump), 'schema_sha256': _digest(directory / 'schema.pb'),
                    'schema_tracked': baseline is not None,
                    'reaction_cache': reaction_cache,
                    'schema_descriptor_source': 'tracked database descriptor' if baseline is not None else (
                        'unavailable; use archived old source' if legacy else 'installed untracked descriptor'),
                    'tables': tables, 'sequences': sorted(sequences),
                    'verified': True, 'verification': 'archive-readable, checksummed; restore verification is separate',
                    'scope': 'Database data, schemas, indexes, constraints, sequences, extensions and large objects. Cluster roles, credentials, application source and external files are separate.'}
        _atomic_json(directory / 'manifest.json', manifest)
        with zipfile.ZipFile(directory / 'backup.zip.part', 'w', compression=zipfile.ZIP_STORED) as archive:
            for name in ['database.dump', 'schema.pb', 'manifest.json']:
                archive.write(directory / name, name)
        (directory / 'backup.zip.part').chmod(0o600)
        (directory / 'backup.zip.part').replace(directory / 'backup.zip')
        return manifest
    except Exception:
        _atomic_json(directory / 'failed.json', {'id': snapshot_id, 'status': 'failed'})
        raise
    finally:
        if own:
            connection.close()


def manifest(snapshot_id):
    directory = _directory(snapshot_id)
    data = json.loads((directory / 'manifest.json').read_text())
    if data['format'] != 'cmccdb-postgresql-custom-v1' or not data['verified']:
        raise ValueError('Snapshot is not complete')
    if data.get('binary_tables'):
        raise ValueError('Experimental binary cartridge snapshots cannot be restored; create a new native-cache snapshot')
    if _digest(directory / 'database.dump') != data['dump_sha256'] or _digest(directory / 'schema.pb') != data['schema_sha256']:
        raise ValueError('Snapshot checksum mismatch')
    return data


def create_verified(engine, database, connection=None, *, legacy=False):
    """Exercise recovery before applying a migration, not only archive readability."""
    data = create(engine, database, connection, legacy=legacy)
    data['restore_verification'] = restore(data['id'])
    _atomic_json(_directory(data['id']) / 'manifest.json', data)
    # Republish the downloadable manifest along with the unchanged dump.
    with zipfile.ZipFile(_directory(data['id']) / 'backup.zip.part', 'w', compression=zipfile.ZIP_STORED) as archive:
        for name in ['database.dump', 'schema.pb', 'manifest.json']:
            archive.write(_directory(data['id']) / name, name)
    (_directory(data['id']) / 'backup.zip.part').chmod(0o600)
    (_directory(data['id']) / 'backup.zip.part').replace(_directory(data['id']) / 'backup.zip')
    return data


def _verification_differences(data, tables, extensions, sequences):
    """Report only names, counts and digests, never restored row contents."""
    expected = data['tables']
    table_differences = {
        name: {'expected': expected.get(name), 'actual': tables.get(name)}
        for name in sorted(set(expected) | set(tables))
        if expected.get(name) != tables.get(name)
    }
    extension_differences = {
        name: {'expected': data['extensions'].get(name), 'actual': extensions.get(name)}
        for name in sorted(set(data['extensions']) | set(extensions))
        if data['extensions'].get(name) != extensions.get(name)
    }
    expected_sequences, actual_sequences = set(data['sequences']), set(sequences)
    sequence_differences = {
        'missing': sorted(expected_sequences - actual_sequences),
        'unexpected': sorted(actual_sequences - expected_sequences),
    }
    if not (table_differences or extension_differences or
            sequence_differences['missing'] or sequence_differences['unexpected']):
        return {}
    return {'tables': table_differences, 'extensions': extension_differences,
            'sequences': sequence_differences}


def restore(snapshot_id):
    """Never accept a destination name, arbitrary archive or --clean option."""
    data = manifest(snapshot_id)
    destination = 'cmccdb_restore_' + uuid.uuid4().hex
    connection = manage.create_raw_connection(database_name='postgres', readonly=False)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(destination)))
        _run([tool('pg_restore'), '--single-transaction', '--exit-on-error', '--no-owner', '--no-acl',
              '--no-tablespaces'] + _connection_arguments(destination) + [str(_directory(snapshot_id) / 'database.dump')])
        engine = manage.get_engine(database_name=destination)
        try:
            with engine.begin() as restored:
                _restore_reaction_cache(restored, data)
                tables = inventory(restored)
                extensions = dict(restored.execute(text('SELECT extname, extversion FROM pg_extension')).all())
                sequences = sorted(s + '.' + n for s, n in restored.execute(text("SELECT schemaname, sequencename FROM pg_sequences WHERE schemaname NOT LIKE 'pg_%'")).all())
                # Check each serial sequence cannot issue an existing primary key.
                for table in inspect(restored).get_table_names(schema='cmccdb'):
                    sequence = restored.scalar(text('SELECT pg_get_serial_sequence(:table, :column)'), {'table':'cmccdb.' + table, 'column':'id'})
                    if sequence:
                        q = restored.dialect.identifier_preparer.quote
                        current, called = restored.execute(text(f'SELECT last_value, is_called FROM {sequence}')).one()
                        maximum = restored.scalar(text(f'SELECT max(id) FROM cmccdb.{q(table)}'))
                        if maximum is not None and (current < maximum or (current == maximum and not called)):
                            raise ValueError(f'Unsafe restored sequence for {table}')
            differences = _verification_differences(data, tables, extensions, sequences)
            if differences:
                # Preserve the evidence while withholding the verified-restore
                # record that would allow this database to be migrated.
                report = {'snapshot_id': snapshot_id, 'database': destination,
                          'verified': False, 'differences': differences}
                _atomic_json(_directory(snapshot_id) / ('verification-failed-' + destination + '.json'), report)
                raise ValueError('Restored database failed table/extension/sequence verification: ' +
                                 json.dumps(differences, sort_keys=True))
        finally:
            engine.dispose()
        result = {'snapshot_id': snapshot_id, 'database': destination, 'verified': True,
                  'tables_verified': len(tables), 'rows_verified': sum(t['rows'] for t in tables.values())}
        _atomic_json(_directory(snapshot_id) / ('restore-' + destination + '.json'), result)
        return result
    except Exception as error:
        raise ValueError(f'Restore failed in isolated database {destination}; source was unchanged: {error}') from error
    finally:
        connection.close()
