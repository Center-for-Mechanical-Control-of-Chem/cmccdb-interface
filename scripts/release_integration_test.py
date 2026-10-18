"""Synthetic source/restore checks, exclusively for server_rehearsal.py's new clusters."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['source', 'restore'])
    args = parser.parse_args()
    root = Path('/release')
    if not os.getenv('CMCCDB_REHEARSAL_TOKEN') or (root / 'token').read_text() != os.environ['CMCCDB_REHEARSAL_TOKEN']:
        raise ValueError('Only run through the isolated rehearsal driver')
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from psycopg2 import sql
    from cmccdb_interface.database import manage, release_data
    from cmccdb_schema.orm import database as orm_database
    from cmccdb_schema.proto import dataset_pb2, reaction_pb2
    engine = release_data.database_engine('postgres')
    with engine.connect() as connection:
        existing = connection.execute(text("SELECT datname FROM pg_database WHERE datname IN ('cmcc','staging')")).all()
    engine.dispose()
    if existing:
        raise ValueError('Rehearsal requires fresh clusters; never overwrite an existing application database')
    if args.action == 'source':
        connection = manage.create_raw_connection(database_name='postgres', readonly=False)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                for name in ('cmcc', 'staging'):
                    cursor.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
        finally:
            connection.close()
        for name in ('cmcc', 'staging'):
            engine = manage.get_engine(database_name=name)
            try:
                cartridge = orm_database.prepare_database(engine)
                if name == 'cmcc':
                    reaction = reaction_pb2.Reaction(reaction_id='cmcc-' + '1' * 32)
                    reaction.provenance.reaction_metadata['local-spectrum'].url = 'alice/spectrum.csv'
                    reaction.provenance.reaction_metadata['embedded-note'].bytes_value = b'embedded rehearsal bytes'
                    dataset = dataset_pb2.Dataset(dataset_id='cmcc_dataset-' + '1' * 32,
                        name='Synthetic release rehearsal', reactions=[reaction])
                    with Session(engine) as session:
                        orm_database.add_dataset(dataset, session, rdkit_cartridge=cartridge)
                        session.commit()
            finally:
                engine.dispose()
        result = {'snapshots': {}, 'inventories': {}}
        for name in ('cmcc', 'staging'):
            result['snapshots'][name] = release_data.execute('snapshot', name)
            result['inventories'][name] = release_data.execute('inventory', name, quiet=True)
        result['export'] = release_data.execute('export', 'cmcc', '/release/source-export')
        (root / 'source-results.json').write_text(json.dumps(result, indent=2, sort_keys=True))
    else:
        source = json.loads((root / 'source-results.json').read_text())
        result = {'verified': {}, 'inventories': {}}
        for name in ('cmcc', 'staging'):
            release_data.execute('restore', name, snapshot=source['snapshots'][name]['id'])
            result['verified'][name] = release_data.execute('verify', name)
            result['inventories'][name] = release_data.execute('inventory', name, quiet=True)
            for key in ('datasets', 'reactions', 'tables', 'extensions'):
                if source['inventories'][name][key] != result['inventories'][name][key]:
                    raise AssertionError('Cross-cluster restore changed ' + name + ' ' + key)
        result['export'] = release_data.execute('export', 'cmcc', '/release/candidate-export')
        if source['export'] != result['export']:
            raise AssertionError('Canonical data/attachments changed across restore')
        (root / 'restore-results.json').write_text(json.dumps(result, indent=2, sort_keys=True))
    print('CMCCDB_INTEGRATION_' + args.action.upper() + '_COMPLETE')


if __name__ == '__main__':
    main()
