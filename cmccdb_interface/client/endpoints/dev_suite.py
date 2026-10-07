"""Read-only inputs and verification for the authorized XLSX contribution suite."""
import hashlib
import json
import subprocess
from pathlib import Path

import flask
from google.protobuf.json_format import MessageToDict
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from cmccdb_interface.database import backups, datasets, manage
from cmccdb_schema.dataset_constructor import DatasetConstructor
from cmccdb_schema.orm.mappers import Mappers, to_proto
from cmccdb_schema.orm.rdkit_mappers import RDKitMol, RDKitReaction
from cmccdb_schema.proto import reaction_pb2

ROOT = Path(__file__).parent / 'test_inputs' / 'live-contributions-20261006'


def _manifest():
    return json.loads((ROOT / 'manifest.json').read_text())


def _case():
    name = flask.request.args.get('file')
    case = next((c for c in _manifest()['cases'] if c['filename'] == name), None)
    if case is None:
        flask.abort(404)
    return case


def _database():
    name = flask.request.args.get('database', 'staging')
    if name not in {'cmcc', 'staging'}:
        flask.abort(400)
    return name


def _git_snapshot():
    def git(*args):
        result = subprocess.run(['git', '-c', f'safe.directory={backups.BACKUP_DIR}',
                                 '-C', backups.BACKUP_DIR, *args],
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()
    return {'head': git('rev-parse', 'HEAD'), 'status': git('status', '--porcelain')}


def policy():
    if backups.github_backups_enabled():
        return flask.jsonify(error='Development GitHub backup guard is not active'), 409
    return flask.jsonify(backup_enabled=False, backup_attempt=backups.git_backup(),
                         data_repo=_git_snapshot(), source_file=str(Path(__file__).resolve()))


def manifest():
    return flask.jsonify(_manifest())


def file():
    case = _case()
    return flask.send_file(ROOT / case['filename'], as_attachment=True,
                           download_name=case['filename'])


def auxiliary():
    name = flask.request.args.get('name')
    allowed = {n for c in _manifest()['cases'] for n in c.get('auxiliary', [])}
    if name not in allowed:
        flask.abort(404)
    return flask.send_file(ROOT / name, as_attachment=True, download_name=name)


def _normalize(message, generated_times=()):
    # The uploader generates these timestamps; all chemical and author fields remain checked.
    for index in generated_times:
        message.reactions[index].provenance.record_created.ClearField('time')
    return MessageToDict(message, preserving_proto_field_name=True)


def _differences(expected, actual, path='', found=None):
    found = [] if found is None else found
    if len(found) >= 15:
        return found
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(expected.keys() | actual.keys()):
            _differences(expected.get(key), actual.get(key), path+'.'+key, found)
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            found.append({'path':path+'.length','expected':len(expected),'actual':len(actual)})
        for i,(left,right) in enumerate(zip(expected,actual)):
            _differences(left,right,f'{path}[{i}]',found)
    elif expected != actual:
        found.append({'path':path,'expected':str(expected)[:200],'actual':str(actual)[:200]})
    return found


def _loads(mapper, descriptor):
    """Read the full mapped dataset without a query for every nested field."""
    options=[]
    for field in descriptor.fields:
        if field.message_type is None:
            continue
        child=field.message_type
        if child.GetOptions().map_entry:
            child=child.fields_by_name['value'].message_type
        relationship=getattr(mapper,field.name)
        options.append(selectinload(relationship).options(*_loads(relationship.property.mapper.class_,child)))
    return options


def validate():
    case = _case()
    path = ROOT / case['filename']
    digest = hashlib.md5(path.read_bytes()).hexdigest()
    dataset_id = 'cmcc_dataset-' + digest
    if case.get('expected_rejection'):
        engine = manage.get_engine(database_name=_database())
        try:
            with Session(engine) as session:
                stored = session.scalar(select(Mappers.Dataset.dataset_id).where(Mappers.Dataset.dataset_id == dataset_id))
            return flask.jsonify(dataset_id=dataset_id, stored=stored is not None,
                                 passed=stored is None, expected_rejection=True)
        finally:
            engine.dispose()
    expected = DatasetConstructor.enumerate_spreadsheet(path, id=digest, name=path.stem,
        optional_fields={'record_created': {
            'time': {'value': '2026-10-06 00:00:00'},
            'name': 'CMCCDB Development Test Runner',
            'email': 'cmccdb-test@example.invalid'}})
    attachments = {n: (ROOT / n).read_bytes() for n in case.get('auxiliary', [])}
    datasets.attach_auxiliary_files(expected, attachments)
    engine = manage.get_engine(database_name=_database())
    try:
        with Session(engine) as session:
            mapped = session.execute(select(Mappers.Dataset).options(*_loads(Mappers.Dataset,expected.DESCRIPTOR)).where(
                Mappers.Dataset.dataset_id == dataset_id)).scalar_one_or_none()
            if mapped is None:
                return flask.jsonify(dataset_id=dataset_id, stored=False, passed=False), 404
            restored = to_proto(mapped)
            protos = session.execute(select(Mappers.Reaction.reaction_id, Mappers.Reaction.proto)
                                    .join(Mappers.Dataset).where(Mappers.Dataset.dataset_id == dataset_id)
                                    .order_by(Mappers.Reaction.id)).all()
            raw = type(expected)(name=mapped.name, description=mapped.description, dataset_id=dataset_id)
            for _, payload in protos:
                raw.reactions.add().CopyFrom(reaction_pb2.Reaction.FromString(bytes(payload)))
            generated_times = [i for i,r in enumerate(expected.reactions)
                               if r.provenance.record_created.time.value == '2026-10-06 00:00:00']
            expected_dict = _normalize(expected, generated_times)
            proto_equal = _normalize(raw, generated_times) == expected_dict
            orm_equal = _normalize(restored, generated_times) == expected_dict
            result = {
                'dataset_id': dataset_id, 'database': _database(),
                'expected_reactions': case['expected_reactions'],
                'stored_reactions': len(raw.reactions),
                'proto_equal': proto_equal, 'orm_equal': orm_equal,
                'authors': sorted({r.provenance.record_created.person.name for r in raw.reactions}),
                'reaction_types': sorted({i.value for r in raw.reactions for i in r.identifiers
                                          if i.type == reaction_pb2.ReactionIdentifier.REACTION_TYPE}),
                'passed': proto_equal and orm_equal and len(raw.reactions) == case['expected_reactions'],
            }
            if not result['passed']:
                result['proto_differences'] = _differences(expected_dict,_normalize(raw,generated_times))
                result['orm_differences'] = _differences(expected_dict,_normalize(restored,generated_times))
            return flask.jsonify(result)
    finally:
        engine.dispose()


def context():
    result = {}
    for name in ['cmcc', 'staging']:
        engine = manage.get_engine(database_name=name)
        try:
            with engine.connect() as connection:
                result[name] = {
                    'actual_database': connection.scalar(text('SELECT current_database()')),
                    'rdkit_extension': connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='rdkit'")),
                    'datasets': connection.scalar(select(__import__('sqlalchemy').func.count()).select_from(Mappers.Dataset)),
                }
        finally:
            engine.dispose()
    return flask.jsonify(result)


def integrity():
    """Check counts and structure-index associations without changing either database."""
    cases = _manifest()['cases']
    positive = [c for c in cases if not c.get('expected_rejection')]
    negative = [c for c in cases if c.get('expected_rejection')]
    ids = ['cmcc_dataset-' + c['md5'] for c in positive]
    rejected_ids = ['cmcc_dataset-' + c['md5'] for c in negative]
    engine = manage.get_engine(database_name=_database())
    try:
        with Session(engine) as session:
            result = {
                'database': _database(),
                'datasets': session.scalar(select(func.count()).select_from(Mappers.Dataset).where(
                    Mappers.Dataset.dataset_id.in_(ids))),
                'reactions': session.scalar(select(func.count()).select_from(Mappers.Reaction)
                    .join(Mappers.Dataset).where(Mappers.Dataset.dataset_id.in_(ids))),
                'rejected_datasets_stored': session.scalar(select(func.count()).select_from(Mappers.Dataset)
                    .where(Mappers.Dataset.dataset_id.in_(rejected_ids))),
            }
            associations = [
                ('reaction', Mappers.Reaction, RDKitReaction, 'reaction_smiles', 'rdkit_reaction_id', []),
                ('input_compound', Mappers.Compound, RDKitMol, 'smiles', 'rdkit_mol_id',
                    [Mappers.ReactionInput, Mappers.Reaction]),
                ('product_compound', Mappers.ProductCompound, RDKitMol, 'smiles', 'rdkit_mol_id',
                    [Mappers.ReactionOutcome, Mappers.Reaction]),
            ]
            result['rdkit_associations'] = {}
            for name, mapper, index, structure, foreign_key, parents in associations:
                query = select(func.count()).select_from(mapper).outerjoin(
                    index, getattr(mapper, foreign_key) == index.id)
                for parent in parents:
                    query = query.join(parent)
                query = query.join(Mappers.Dataset).where(Mappers.Dataset.dataset_id.in_(ids),
                    getattr(mapper, structure).is_not(None))
                checked = session.scalar(query)
                mismatch = session.scalar(query.where(or_(index.id.is_(None),
                    getattr(mapper, structure) != getattr(index, structure))))
                result['rdkit_associations'][name] = {'checked': checked, 'mismatches': mismatch}
            result['passed'] = (
                result['datasets'] == len(positive)
                and result['reactions'] == sum(c['expected_reactions'] for c in positive)
                and result['rejected_datasets_stored'] == 0
                and all(v['mismatches'] == 0 for v in result['rdkit_associations'].values())
            )
            return flask.jsonify(result)
    finally:
        engine.dispose()
