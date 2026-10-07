"""Fixed maintenance operations, run inside the old/candidate web image by its operator.

This is a CLI worker, never an HTTP endpoint. It reuses the backup/migration
implementation and will not run for a development deployment.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path


def guard():
    if os.getenv('CMCCDB_RELEASE_TARGET') not in {'main', 'preview'}:
        raise ValueError('Release target must be main or preview')
    if any(os.getenv(key, '').lower() in {'1', 'true', 'yes', 'on'} for key in
           ['CMCCDB_DEV_BACKEND', 'CMCCDB_DEV_FRONTEND', 'CMCCDB_DEV_FRONTEND_PROXY']):
        raise ValueError('Development backends/frontends cannot be updated by this worker')


def connect(database):
    from cmccdb_interface.database import manage
    engine = manage.get_engine(database_name=database)
    from sqlalchemy import text
    with engine.connect() as connection:
        actual = str(connection.scalar(text('SELECT system_identifier FROM pg_control_system()')))
    if actual != os.environ['CMCCDB_EXPECTED_CLUSTER']:
        engine.dispose()
        raise ValueError('Connected to a different PostgreSQL cluster; refusing operation')
    return engine


def quiet(connection):
    from sqlalchemy import text
    count = connection.scalar(text("""SELECT count(*) FROM pg_stat_activity
        WHERE datname=current_database() AND backend_type='client backend'
          AND pid<>pg_backend_pid()"""))
    if count:
        raise ValueError('Other database clients are connected; pause external writers first')


def columns(connection):
    from sqlalchemy import inspect
    inspector = inspect(connection)
    return {schema+'.'+table: [c['name'] for c in inspector.get_columns(table, schema=schema)]
        for schema in sorted(inspector.get_schema_names())
        if schema != 'information_schema' and not schema.startswith('pg_')
        for table in sorted(inspector.get_table_names(schema=schema))}


def compare_saved_rows(connection, baseline):
    """Compare all old columns, even when a migration added nullable columns."""
    from sqlalchemy import text
    connection.execute(text("SET LOCAL timezone='UTC'"))
    quote = connection.dialect.identifier_preparer.quote
    for name, names in baseline['columns'].items():
        if name.startswith('cmccdb_meta.'):
            continue  # Descriptor history changes intentionally.
        schema, table = name.split('.', 1)
        projection = ','.join(quote(column) for column in names)
        digest, count = hashlib.sha256(), 0
        query = f'SELECT md5(row_to_json(t)::text) AS hash FROM (SELECT {projection} FROM {quote(schema)}.{quote(table)}) t ORDER BY hash'
        rows = connection.execution_options(stream_results=True).execute(text(query))
        for (row_hash,) in rows:
            digest.update(row_hash.encode('ascii'))
            count += 1
        rows.close()
        connection.execution_options(stream_results=False)
        if {'rows': count, 'sha256': digest.hexdigest()} != baseline['tables'][name]:
            raise ValueError('Existing data changed during update: '+name)


def verify(engine, baseline=None):
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session
    from cmccdb_schema.orm import schema_updates
    from cmccdb_schema.orm.mappers import Base, Mappers, to_proto
    from cmccdb_schema.proto import reaction_pb2
    with engine.begin() as connection:
        connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        preview = schema_updates.plan(connection, Base.metadata)
        if preview['required'] or not preview['compatible']:
            raise ValueError('Schema is not synchronized: '+json.dumps(preview))
        if baseline:
            compare_saved_rows(connection, baseline)
        # Check every original Reaction proto against the new ORM reconstruction.
        count, first, last = 0, None, 0
        with Session(bind=connection) as session:
            while True:
                batch = session.execute(select(Mappers.Reaction).where(Mappers.Reaction.id>last)
                    .order_by(Mappers.Reaction.id).limit(100)).scalars().all()
                if not batch:
                    break
                for reaction in batch:
                    if to_proto(reaction) != reaction_pb2.Reaction.FromString(reaction.proto):
                        raise ValueError('ORM/raw protobuf mismatch: '+reaction.reaction_id)
                    first = first or reaction.reaction_id
                    count += 1
                last = batch[-1].id
                session.expunge_all()
    return {'required': False, 'compatible': True, 'reactions_verified': count,
            'first_reaction': first, 'schema_sha256': preview['schema_sha256']}


def execute(action, database, baseline_path=None):
    guard()
    from sqlalchemy import inspect, text
    from cmccdb_schema.orm import schema_updates
    from cmccdb_schema.orm.mappers import Base
    from cmccdb_interface.database import snapshots
    engine = connect(database)
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table('dataset', schema='cmccdb'):
                raise ValueError('Not an existing CMCCDB database: '+database)
            preview = schema_updates.plan(connection, Base.metadata)
        if action == 'probe':
            snapshots.tool('pg_dump'); snapshots.tool('pg_restore')
            if preview['required'] or not preview['compatible']:
                raise ValueError('Old installed schema must match its database before updating')
            return preview
        baseline = json.loads(Path(baseline_path).read_text()) if baseline_path else None
        if action == 'backup':
            if database not in {'cmcc', 'staging'}:
                raise ValueError('Only production application databases may be archived')
            with engine.connect() as connection:
                quiet(connection)
            snapshots.bootstrap(engine)
            data = snapshots.create_verified(engine, database)
            with engine.connect() as connection:
                data['columns'] = columns(connection)
            return data
        if action in {'rehearse', 'apply'}:
            if not baseline or baseline['database'] not in {'cmcc', 'staging'}:
                raise ValueError('A verified baseline snapshot is required')
            if not baseline.get('verified') or not baseline.get('restore_verification', {}).get('verified'):
                raise ValueError('Baseline has not passed restoration')
            if action == 'rehearse' and database != baseline['restore_verification']['database']:
                raise ValueError('Rehearsal requires the verified isolated restore')
            if action == 'apply' and database != baseline['database']:
                raise ValueError('Live database does not match baseline')
            with engine.connect() as connection:
                quiet(connection)
                compare_saved_rows(connection, baseline)
            if not preview['compatible']:
                raise ValueError('Incompatible migration: '+json.dumps(preview))
            snapshot = (lambda _: baseline) if action=='rehearse' else (
                lambda connection: snapshots.create_verified(engine, database, connection=connection))
            result = schema_updates.apply(engine, Base.metadata, preview['fingerprint'], snapshot)
            result['verification'] = verify(engine, baseline)
            return result
        if action == 'verify':
            return verify(engine, baseline)
        if action == 'http':
            with urllib.request.urlopen('http://127.0.0.1/', timeout=10) as response:
                if response.status != 200:
                    raise ValueError('Nginx/frontend health check failed')
            result = verify(engine)
            body = json.dumps([result['first_reaction']] if result['first_reaction'] else []).encode()
            request = urllib.request.Request('http://127.0.0.1/api/fetch_reactions?database='+database,
                data=body, headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200:
                    raise ValueError('Nginx/Gunicorn/database health check failed')
            return result
        raise ValueError('Unknown maintenance operation')
    finally:
        engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['probe','backup','rehearse','apply','verify','http'])
    parser.add_argument('database')
    parser.add_argument('--baseline')
    args = parser.parse_args()
    result = execute(args.action, args.database, args.baseline)
    print('CMCCDB_RELEASE_RESULT='+json.dumps(result, sort_keys=True))
