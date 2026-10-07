"""Initial legacy-backend migration through isolated XLSX replay databases.

Old databases are retained by name. Promotion renames all application database
pairs in one PostgreSQL transaction and never drops/cleans a database.
"""
import json
import re
from pathlib import Path

from sqlalchemy import inspect, text

from . import batch_resubmit, manage, snapshots


def cluster(engine, expected):
    with engine.connect() as connection:
        actual = str(connection.scalar(text('SELECT system_identifier FROM pg_control_system()')))
    if actual != str(expected):
        raise ValueError('Connected to another PostgreSQL cluster')


def spec_file(path):
    path = Path(path)
    spec = json.loads(path.read_text())
    batch_resubmit.guard(spec['target'])
    if not re.fullmatch(r'[0-9a-f]{32}', spec['id']):
        raise ValueError('Invalid migration identity')
    for name, item in spec['databases'].items():
        if name not in {'cmcc', 'staging'}:
            raise ValueError('Only cmcc and staging may be promoted')
        if item['import_name'] != 'cmccdb_import_' + item['id'] or not re.fullmatch(r'[0-9a-f]{32}', item['id']):
            raise ValueError('Invalid import database identity')
        if item['retained_name'] != 'cmccdb_legacy_' + name + '_' + spec['id']:
            raise ValueError('Invalid retained database identity')
    return path, spec


def prepare(path):
    path, spec = spec_file(path)
    if spec.get('promoted'):
        raise ValueError('Migration was already promoted; do not prepare it again')
    from cmccdb_schema.orm import database as orm_database, schema_updates
    from cmccdb_schema.orm.mappers import Base
    schema_hash = schema_updates.descriptor_hash(schema_updates.descriptors())
    if spec.get('schema_sha256') and spec['schema_sha256'] != schema_hash:
        raise ValueError('Resume requires the same schema; this import needs a separate reviewed migration')
    spec['schema_sha256'] = schema_hash
    admin = manage.get_engine(database_name='postgres').execution_options(isolation_level='AUTOCOMMIT')
    try:
        cluster(admin, spec['cluster'])
        for name, item in spec['databases'].items():
            with admin.connect() as connection:
                oid = connection.scalar(text('SELECT oid FROM pg_database WHERE datname=:name'), {'name': name})
                if not oid or (item.get('old_oid') and item['old_oid'] != oid):
                    raise ValueError('Legacy database changed or is no longer available: ' + name)
                item['old_oid'] = oid
                existing = connection.scalar(text('SELECT oid FROM pg_database WHERE datname=:name'), {'name': item['import_name']})
                if existing and not item.get('create_attempted'):
                    raise ValueError('Import database already exists without a migration receipt')
                if not existing:
                    item['create_attempted'] = True
                    batch_resubmit.write_json(path, spec)
                    quote = connection.dialect.identifier_preparer.quote
                    connection.execute(text('CREATE DATABASE ' + quote(item['import_name']) + ' TEMPLATE template0'))
                item['import_oid'] = connection.scalar(text('SELECT oid FROM pg_database WHERE datname=:name'), {'name': item['import_name']})
                batch_resubmit.write_json(path, spec)
            engine = manage.get_engine(database_name=item['import_name'])
            try:
                orm_database.prepare_database(engine)
                with engine.connect() as connection:
                    plan = schema_updates.plan(connection, Base.metadata)
                    if plan['required'] or not plan['compatible']:
                        raise ValueError('Import database schema differs from the candidate image')
            finally:
                engine.dispose()
        spec['prepared'] = True
        batch_resubmit.write_json(path, spec)
        return spec
    finally:
        admin.dispose()


def replay(path, database, folder, report, name, email):
    path, spec = spec_file(path)
    if not spec.get('prepared'):
        raise ValueError('Migration databases have not been prepared')
    item = spec['databases'][database]
    if item.get('empty'):
        # An empty legacy database still gets a fresh, current schema.
        result = {'ok': True, 'empty': True, 'database': item['import_name']}
    else:
        if Path(report).parent.resolve() != path.parent.resolve():
            raise ValueError('Replay report must be stored beside its migration receipt')
        result = batch_resubmit.apply(folder, report, name, email, spec['target'],
                                     item['import_name'], spec['cluster'], backup=False)
        item['report'] = Path(report).name
    item['replay_ok'] = result['ok']
    batch_resubmit.write_json(path, spec)
    return result


def identifiers(engine):
    with engine.connect() as connection:
        inspector = inspect(connection)
        if not inspector.has_table('dataset', schema='cmccdb'):
            raise ValueError('Legacy database has no CMCCDB dataset table')
        datasets = set(connection.execute(text('SELECT dataset_id FROM cmccdb.dataset')).scalars())
        reactions = set(connection.execute(text('SELECT reaction_id FROM cmccdb.reaction')).scalars())
    return datasets, reactions


def legacy_backup(path, database):
    path, spec = spec_file(path)
    engine = manage.get_engine(database_name=database)
    try:
        cluster(engine, spec['cluster'])
        with engine.connect() as connection:
            count = connection.scalar(text("""SELECT count(*) FROM pg_stat_activity
                WHERE datname=current_database() AND backend_type='client backend' AND pid<>pg_backend_pid()"""))
            if count:
                raise ValueError('Pause other connected clients before the legacy backup')
        # Generic native dump/restore/inventory requires no old ORM or old helpers.
        result = snapshots.create_verified(engine, database, legacy=True)
        spec['databases'][database]['legacy_snapshot_id'] = result['id']
        batch_resubmit.write_json(path, spec)
        return result
    finally:
        engine.dispose()


def verify_legacy_snapshot(engine, snapshot_id):
    baseline = snapshots.manifest(snapshot_id)
    if not baseline.get('restore_verification', {}).get('verified'):
        raise ValueError('Legacy snapshot has not passed restore verification')
    with engine.begin() as connection:
        connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        if snapshots.inventory(connection) != baseline['tables']:
            raise ValueError('Legacy data changed after its backup; repeat maintenance before promotion')


def coverage(path):
    path, spec = spec_file(path)
    results = {}
    for database, item in spec['databases'].items():
        old = manage.get_engine(database_name=database)
        new = manage.get_engine(database_name=item['import_name'])
        try:
            cluster(old, spec['cluster'])
            before_datasets, before_reactions = identifiers(old)
            after_datasets, after_reactions = identifiers(new)
            missing_datasets = sorted(before_datasets - after_datasets)
            missing_reactions = sorted(before_reactions - after_reactions)
            results[database] = {'ok': not missing_datasets and not missing_reactions,
                'old_datasets': len(before_datasets), 'new_datasets': len(after_datasets),
                'old_reactions': len(before_reactions), 'new_reactions': len(after_reactions),
                'missing_dataset_ids': missing_datasets, 'missing_reaction_ids': missing_reactions}
        finally:
            old.dispose()
            new.dispose()
    spec['coverage'] = results
    batch_resubmit.write_json(path, spec)
    return {'ok': all(item['ok'] for item in results.values()), 'databases': results}


def promote(path):
    path, spec = spec_file(path)
    if spec.get('promoted'):
        raise ValueError('Migration was already promoted; inspect its journal before recovery')
    for item in spec['databases'].values():
        if not item.get('replay_ok'):
            raise ValueError('Every XLSX replay must succeed before promotion')
        if not item.get('empty'):
            report = path.parent / item['report']
            if report.resolve().parent != path.parent.resolve():
                raise ValueError('Replay report path escapes its migration receipt')
            batch_resubmit.verify_receipts(report, item['import_name'], spec['cluster'])
    for name, item in spec['databases'].items():
        if not item.get('legacy_snapshot_id'):
            raise ValueError('Every legacy database requires a restore-verified backup')
        engine = manage.get_engine(database_name=name)
        try:
            cluster(engine, spec['cluster'])
            verify_legacy_snapshot(engine, item['legacy_snapshot_id'])
        finally:
            engine.dispose()
    if not spec.get('coverage') or not all(item['ok'] for item in spec['coverage'].values()):
        raise ValueError('Every legacy dataset/reaction must be covered before promotion')
    # Recheck coverage just before beginning the rename transaction.
    if not coverage(path)['ok']:
        raise ValueError('Legacy coverage changed before promotion')
    admin = manage.get_engine(database_name='postgres')
    try:
        cluster(admin, spec['cluster'])
        with admin.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout='5s'"))
            connection.execute(text("SET LOCAL statement_timeout='60s'"))
            if not connection.scalar(text('SELECT pg_try_advisory_xact_lock(:lock)'), {'lock': 0x434D43435250}):
                raise ValueError('Another database promotion is running')
            for name, item in spec['databases'].items():
                rows = dict(connection.execute(text('SELECT datname, oid FROM pg_database WHERE datname IN (:old,:new,:retained)'),
                    {'old': name, 'new': item['import_name'], 'retained': item['retained_name']}).all())
                if rows.get(name) != item['old_oid'] or rows.get(item['import_name']) != item['import_oid'] or item['retained_name'] in rows:
                    raise ValueError('Database identities changed before promotion')
                clients = connection.scalar(text('SELECT count(*) FROM pg_stat_activity WHERE datname IN (:old,:new)'),
                    {'old': name, 'new': item['import_name']})
                if clients:
                    raise ValueError('Other sessions are connected; promotion never terminates their connections')
            quote = connection.dialect.identifier_preparer.quote
            for name, item in spec['databases'].items():
                connection.execute(text('ALTER DATABASE ' + quote(name) + ' RENAME TO ' + quote(item['retained_name'])))
                connection.execute(text('ALTER DATABASE ' + quote(item['import_name']) + ' RENAME TO ' + quote(name)))
        spec['promoted'] = True
        batch_resubmit.write_json(path, spec)
        return {'promoted': True, 'retained_databases': {
            name: item['retained_name'] for name, item in spec['databases'].items()}}
    finally:
        admin.dispose()
