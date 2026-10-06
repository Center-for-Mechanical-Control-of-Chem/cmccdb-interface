"""Exercise upload formats, auxiliary bytes, and dataset-reference queries."""
import gzip
import io
import os
from pathlib import Path

import pytest
from google.protobuf import json_format, text_format
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from cmccdb_interface.database import datasets, backups, manage, query
from cmccdb_schema import message_helpers
from cmccdb_schema.orm import database
from cmccdb_schema.orm.mappers import Mappers, to_proto
from cmccdb_schema.proto import dataset_pb2


@pytest.fixture
def sample():
    dataset = dataset_pb2.Dataset(dataset_id='cmcc_dataset-' + 'a' * 32)
    reaction = dataset.reactions.add(reaction_id='cmcc-' + 'b' * 32)
    reaction.outcomes.add().analyses['xas'].data['spectrum'].url = 'a' * 32 + '_spectrum.csv'
    return dataset


@pytest.fixture
def upload_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, 'TEMPORARY_DIR', str(tmp_path / 'temporary'))
    monkeypatch.setattr(backups, 'BACKUP_DIR', str(tmp_path / 'backup'))
    return tmp_path


@pytest.mark.parametrize('suffix', ['.pb', '.pbtxt', '.json', '.pb.gz', '.pbtxt.gz', '.json.gz'])
def test_upload_formats(suffix, sample, upload_storage):
    base = suffix.removesuffix('.gz')
    body = {'.pb': sample.SerializeToString(), '.pbtxt': text_format.MessageToBytes(sample),
            '.json': json_format.MessageToJson(sample).encode()}[base]
    if suffix.endswith('.gz'):
        body = gzip.compress(body)
    result = datasets.prep_and_create_pb_dataset('data' + suffix, body, perform_backup=False,
        uploader_username='tester', auxiliary_files={'spectrum.csv': b'energy,value\n1,2\n'})
    assert result.reactions[0].outcomes[0].analyses['xas'].data['spectrum'].bytes_value == b'energy,value\n1,2\n'
    assert result.reactions[0].outcomes[0].analyses['xas'].data['spectrum'].format == 'csv'
    compiled = list(upload_storage.rglob('*.pbtxt'))
    assert compiled and message_helpers.load_message(str(compiled[0]), dataset_pb2.Dataset) == result


def test_external_urls_and_all_auxiliary_bytes(sample):
    external = sample.reactions[0].provenance.reaction_metadata['remote']
    external.url = 'https://example.com/spectrum.csv'
    body = b'\x00\xffpng-data'
    datasets.attach_auxiliary_files(sample, {'spectrum.csv': b'1,2', 'image.png': body})
    assert external.url == 'https://example.com/spectrum.csv'
    assert sample.reactions[0].provenance.reaction_metadata['attachment:image.png'].bytes_value == body


@pytest.mark.parametrize('files,reason', [({'../escape.csv': b''}, 'basenames'),
    ({'a.csv': b'x' * (datasets.MAX_UPLOAD_BYTES + 1)}, '5 MB'),
    ({f'{i}.csv': b'' for i in range(6)}, 'five')])
def test_attachment_limits(sample, files, reason):
    with pytest.raises(ValueError, match=reason):
        datasets.attach_auxiliary_files(sample, files)


def test_csv_and_xlsx_upload(upload_storage):
    root = Path(os.environ['CMCCDB_DATA_ROOT'])
    path = root / 'tests/url_link_test.xlsx'
    files = {p.name: p.read_bytes() for p in (root / 'aux').iterdir() if p.is_file()}
    import pandas as pd
    csv_body = pd.read_excel(path, header=None, dtype=str, keep_default_na=False).to_csv(header=False, index=False).encode()
    for name, body in [('data.xlsx', path.read_bytes()), ('data.csv', csv_body)]:
        dataset = datasets.prep_and_create_pb_dataset(name, body, perform_backup=False,
            uploader_username='tester', uploader_name='Tester', uploader_email='test@example.com', auxiliary_files=files)
        assert dataset.reactions
        embedded = [d.bytes_value for d in datasets.iter_data(dataset) if d.WhichOneof('kind') == 'bytes_value']
        assert all(body in embedded for body in files.values())


def test_upload_and_download_database(sample, upload_storage, monkeypatch):
    url = os.environ.get('CMCCDB_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set CMCCDB_TEST_DATABASE_URL for the upload/database integration test')
    assert make_url(url).database.startswith('cmccdb_test_')
    engine = create_engine(url, future=True)
    cartridge = database.prepare_database(engine)
    monkeypatch.setenv('CMCCDB_SESSION_KEY', 'isolated-test-key')
    from cmccdb_interface.interface import app
    from cmccdb_interface.client import edit
    monkeypatch.setattr(edit.authentication, 'gh_get_cache_user_info',
        lambda: {'username': 'tester', 'member': True, 'owner': False})
    monkeypatch.setattr(manage, 'get_engine', lambda **kwargs: engine)
    backup_calls = []
    monkeypatch.setattr(backups, 'git_backup', lambda: backup_calls.append(True))

    def store(dataset, **kwargs):
        with Session(engine) as session:
            database.add_dataset(dataset, session, rdkit_cartridge=cartridge)
            session.commit()
        return dataset.dataset_id

    monkeypatch.setattr(manage, 'add_dataset', store)
    client = app.test_client()
    try:
        body = text_format.MessageToBytes(sample)
        response = client.post('/client/api/upload?database=staging&perform_backup=false', data={
            'uploadFile': (io.BytesIO(body), 'data.pbtxt'),
            'auxFile0': (io.BytesIO(b'\x00\xffcsv'), 'spectrum.csv')})
        assert response.status_code == 200, response.data
        assert response.json['dataset_id'] == sample.dataset_id
        assert not backup_calls
        response = client.get(f'/client/api/auxiliary/{sample.dataset_id}/spectrum.csv?database=staging')
        assert response.status_code == 200 and response.data == b'\x00\xffcsv'
        assert client.get(f'/client/api/auxiliary/{sample.dataset_id}/missing.csv?database=staging').status_code == 404
        with Session(engine) as session:
            stored = to_proto(session.execute(select(Mappers.Dataset).where(Mappers.Dataset.dataset_id == sample.dataset_id)).scalar_one())
            assert stored.reactions[0].outcomes[0].analyses['xas'].data['spectrum'].bytes_value == b'\x00\xffcsv'
            reference = dataset_pb2.Dataset(dataset_id='cmcc_dataset-' + 'c' * 32, reaction_ids=[sample.reactions[0].reaction_id])
            database.add_dataset(reference, session, rdkit_cartridge=cartridge)
            session.commit()
        connection = engine.raw_connection()
        try:
            with connection.cursor() as cursor:
                results = query.DatasetIdQuery([reference.dataset_id]).run(cursor)
                assert len(results) == 1 and results[0].reaction_id == sample.reactions[0].reaction_id
                assert results[0].dataset_id == reference.dataset_id
        finally:
            connection.close()
    finally:
        with Session(engine) as session:
            for dataset_id in [sample.dataset_id, 'cmcc_dataset-' + 'c' * 32]:
                database.delete_dataset(dataset_id, session)
            session.commit()
        engine.dispose()
