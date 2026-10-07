"""Owner-only read-only fixtures and verification for the incomplete-file audit."""
import hashlib
import json
from pathlib import Path
import flask
from sqlalchemy import select
from sqlalchemy.orm import Session
from cmccdb_schema import message_helpers
from cmccdb_schema.dataset_constructor import DatasetConstructor
from cmccdb_schema.orm.mappers import Mappers, to_proto
from cmccdb_schema.proto import dataset_pb2, reaction_pb2
from cmccdb_interface.client import maintenance
from cmccdb_interface.database import manage
from cmccdb_interface.client.endpoints.dev_suite import _loads, _normalize, _differences, policy as git_policy

ROOT=Path(__file__).parent/'test_inputs/extruder-migrations-20261006'


def _manifest():return json.loads((ROOT/'manifest.json').read_text())


def _case():
    name=flask.request.args.get('file')
    result=next((c for c in _manifest()['cases'] if c['filename']==name),None)
    if result is None:flask.abort(404)
    return result


@maintenance.protected
def manifest():return flask.jsonify(_manifest())


@maintenance.protected
def file():
    case=_case();path=ROOT/case['filename']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=case['sha256']:raise ValueError('Fixture checksum mismatch')
    return flask.send_file(path,as_attachment=True,download_name=case['filename'])


@maintenance.protected
def policy():return git_policy()


@maintenance.protected
def validate():
    case=_case();path=ROOT/case['filename']
    dataset_id=case.get('dataset_id') or 'cmcc_dataset-'+case['md5']
    engine=manage.get_engine(database_name=flask.request.args.get('database','staging'))
    try:
        if case['expected_rejection']:
            with Session(engine) as session:
                stored=session.scalar(select(Mappers.Dataset.dataset_id).where(Mappers.Dataset.dataset_id==dataset_id))
            return flask.jsonify(dataset_id=dataset_id,stored=stored is not None,passed=stored is None)
        if path.suffix=='.pbtxt':
            expected=message_helpers.load_message(str(path),dataset_pb2.Dataset)
        else:
            expected=DatasetConstructor.enumerate_spreadsheet(path,id=case['md5'],name=path.stem,
                optional_fields={'record_created':{'time':{'value':'2026-10-06 00:00:00'},
                    'name':'CMCCDB Development Test Runner','email':'cmccdb-test@example.invalid'}})
        with Session(engine) as session:
            mapped=session.execute(select(Mappers.Dataset).options(*_loads(Mappers.Dataset,expected.DESCRIPTOR)).where(
                Mappers.Dataset.dataset_id==dataset_id)).scalar_one_or_none()
            if mapped is None:return flask.jsonify(dataset_id=dataset_id,stored=False,passed=False),404
            restored=to_proto(mapped)
            raw=dataset_pb2.Dataset(name=mapped.name,description=mapped.description,dataset_id=dataset_id)
            for (payload,) in session.execute(select(Mappers.Reaction.proto).join(Mappers.Dataset).where(
                Mappers.Dataset.dataset_id==dataset_id).order_by(Mappers.Reaction.id)):
                raw.reactions.add().CopyFrom(reaction_pb2.Reaction.FromString(bytes(payload)))
            generated=[i for i,r in enumerate(expected.reactions) if r.provenance.record_created.time.value=='2026-10-06 00:00:00']
            target=_normalize(expected,generated)
            orm_equal=_normalize(restored,generated)==target
            proto_equal=_normalize(raw,generated)==target
            result={'dataset_id':dataset_id,'stored':True,'reactions':len(raw.reactions),
                    'orm_equal':orm_equal,'proto_equal':proto_equal,'passed':orm_equal and proto_equal,
                    'authors':sorted({r.provenance.record_created.person.name for r in raw.reactions})}
            if 'EXTRUDER' in case['filename']:
                result['extruder_values']=[{'rpm':r.conditions.mechanochemistry.frequency.value,
                    'rpm_units':reaction_pb2.Frequency.FrequencyUnit.Name(r.conditions.mechanochemistry.frequency.units),
                    'feed_rate':r.conditions.mechanochemistry.feed_rate.value,
                    'feed_units':reaction_pb2.FlowRate.FlowRateUnit.Name(r.conditions.mechanochemistry.feed_rate.units)} for r in raw.reactions]
            if not result['passed']:result['differences']=_differences(target,_normalize(restored,generated))
            return flask.jsonify(result)
    finally:engine.dispose()
