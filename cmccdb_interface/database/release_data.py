"""Fixed operator actions for frozen CMCCDB releases. No HTTP routes or Git pushes."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def database_engine(database):
    from sqlalchemy import text
    from . import manage
    engine = manage.get_engine(database_name=database)
    with engine.connect() as connection:
        cluster = str(connection.scalar(text('SELECT system_identifier FROM pg_control_system()')))
    if cluster != os.environ['CMCCDB_EXPECTED_CLUSTER']:
        engine.dispose()
        raise ValueError('PostgreSQL cluster identity changed')
    return engine


def no_clients(connection):
    from sqlalchemy import text
    count = connection.scalar(text("""SELECT count(*) FROM pg_stat_activity
        WHERE datname=current_database() AND backend_type='client backend'
        AND pid<>pg_backend_pid()"""))
    if count:
        raise ValueError('Pause external database clients before freezing this release')


def inventory(engine, quiet=False):
    """Works with legacy tables too: never installs or labels a new schema."""
    from sqlalchemy import text
    from . import snapshots
    with engine.begin() as connection:
        connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        if quiet:
            no_clients(connection)
        datasets = dict(connection.execute(text('SELECT dataset_id, md5 FROM cmccdb.dataset')).all())
        reactions = {key: sha(bytes(body)) for key, body in connection.execute(
            text('SELECT reaction_id, proto FROM cmccdb.reaction'))}
        tables = snapshots.inventory(connection)
        oid = connection.scalar(text('SELECT oid FROM pg_database WHERE datname=current_database()'))
        extensions = dict(connection.execute(text('SELECT extname, extversion FROM pg_extension')).all())
    return {'oid': oid, 'datasets': datasets, 'reactions': reactions,
            'tables': tables, 'extensions': extensions}


def check_auxiliary(reaction, dataset_id):
    from urllib.parse import urlsplit
    from ..client.auxiliary import _data_messages, _local_path, _attachment_file
    result = []
    for data in _data_messages(reaction):
        if data.WhichOneof('kind') != 'url' or not data.url:
            continue
        parts = urlsplit(data.url)
        if parts.scheme or parts.netloc:
            continue
        relative = _local_path(data.url)
        path = _attachment_file(relative, dataset_id) if relative is not None else None
        if path is None:
            raise ValueError('Missing or ambiguous local attachment: ' + data.url)
        result.append((data.url, path))
    return result


def verify(engine, check_files=False):
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session
    from cmccdb_schema.orm import schema_updates
    from cmccdb_schema.orm.mappers import Base, Mappers, to_proto
    from cmccdb_schema.proto import reaction_pb2
    count = 0
    with engine.begin() as connection:
        connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        plan = schema_updates.plan(connection, Base.metadata)
        if plan['required'] or not plan['compatible']:
            raise ValueError('Candidate schema does not match its database')
        with Session(bind=connection) as session:
            last = 0
            while True:
                rows = session.execute(select(Mappers.Reaction).where(Mappers.Reaction.id > last)
                    .order_by(Mappers.Reaction.id).limit(100)).scalars().all()
                if not rows:
                    break
                for row in rows:
                    if to_proto(row) != reaction_pb2.Reaction.FromString(bytes(row.proto)):
                        raise ValueError('ORM/protobuf mismatch: ' + row.reaction_id)
                    if check_files:
                        from sqlalchemy import text
                        dataset_id = session.execute(select(Mappers.Dataset.dataset_id)
                            .where(Mappers.Dataset.id == row.dataset_id)).scalar_one()
                        check_auxiliary(to_proto(row), dataset_id)
                    count += 1
                last = rows[-1].id
                session.expunge_all()
    return {'schema_sha256': plan['schema_sha256'], 'reactions_verified': count}


def export(engine, destination):
    """Canonical accepted data only; staging and SQL backups never enter this export."""
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session
    from google.protobuf import text_format
    from cmccdb_schema.orm import schema_updates
    from cmccdb_schema.orm.mappers import Mappers, to_proto
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    files, datasets = {}, {}
    def save(name, body):
        (destination / name).write_bytes(body)
        files[name] = sha(body)
    with engine.begin() as connection:
        connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        with Session(bind=connection) as session:
            last = 0
            while True:
                rows = session.execute(select(Mappers.Dataset).where(Mappers.Dataset.id > last)
                    .order_by(Mappers.Dataset.id).limit(25)).scalars().all()
                if not rows:
                    break
                for row in rows:
                    dataset = to_proto(row)
                    if not re.fullmatch(r'cmcc_dataset-[a-fA-F0-9]{32}', dataset.dataset_id):
                        raise ValueError('Unexpected dataset ID; refusing to turn it into a file path')
                    binary = dataset.SerializeToString(deterministic=True)
                    save(dataset.dataset_id + '.pb', binary)
                    save(dataset.dataset_id + '.pbtxt', text_format.MessageToString(dataset).encode())
                    references = []
                    for reaction in dataset.reactions:
                        for url, path in check_auxiliary(reaction, dataset.dataset_id):
                            body = path.read_bytes()
                            name = 'aux/' + sha(body)
                            (destination / 'aux').mkdir(mode=0o700, exist_ok=True)
                            save(name, body)
                            references.append({'url': url, 'file': name, 'sha256': sha(body)})
                    datasets[dataset.dataset_id] = {'sha256': sha(binary),
                        'reactions': len(dataset.reactions), 'references': len(dataset.reaction_ids),
                        'local_attachments': references}
                last = rows[-1].id
                session.expunge_all()
    save('schema.pb', schema_updates.descriptors())
    result = {'format': 'cmccdb-data-release-v1', 'database': 'cmcc',
              'datasets': datasets, 'files': files}
    (destination / 'manifest.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result


def execute(action, database, output=None, snapshot=None, quiet=False):
    if database not in {'cmcc', 'staging', 'postgres'}:
        raise ValueError('Only fixed application database names are supported')
    engine = database_engine(database if action != 'restore' else 'postgres')
    try:
        if action == 'inventory':
            return inventory(engine, quiet)
        if action == 'verify':
            return verify(engine, check_files=True)
        if action == 'export':
            if database != 'cmcc':
                raise ValueError('Staging cannot be exported for a public data commit')
            verify(engine, check_files=True)
            return export(engine, output)
        from . import snapshots
        if action == 'snapshot':
            with engine.connect() as connection:
                no_clients(connection)
            verify(engine)
            return snapshots.create_verified(engine, database)
        if action == 'restore':
            # The destination is an entirely new release cluster. Never overwrite a database.
            from sqlalchemy import text
            from psycopg2 import sql
            from . import manage
            with engine.connect() as connection:
                exists = connection.scalar(text('SELECT count(*) FROM pg_database WHERE datname=:name'),
                                           {'name': database})
            if exists:
                raise ValueError('Candidate database already exists; retained for diagnosis')
            restored = snapshots.restore(snapshot)
            connection = manage.create_raw_connection(database_name='postgres', readonly=False)
            try:
                connection.autocommit = True
                with connection.cursor() as cursor:
                    cursor.execute(sql.SQL('ALTER DATABASE {} RENAME TO {}').format(
                        sql.Identifier(restored['database']), sql.Identifier(database)))
            finally:
                connection.close()
            return restored
        raise ValueError('Unknown release operation')
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inventory', 'verify', 'snapshot', 'restore', 'export'])
    parser.add_argument('database', choices=['cmcc', 'staging'])
    parser.add_argument('--output')
    parser.add_argument('--snapshot')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    result = execute(args.action, args.database, args.output, args.snapshot, args.quiet)
    print('CMCCDB_RELEASE_RESULT=' + json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
