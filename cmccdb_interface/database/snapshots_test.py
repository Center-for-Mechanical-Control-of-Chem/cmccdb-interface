"""Corruption, path and retry boundaries for the snapshot service."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, Mock
import pytest
from cmccdb_interface.database import snapshots, maintenance_jobs


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('CMCCDB_SNAPSHOT_DIR',str(tmp_path))
    return tmp_path


@pytest.mark.parametrize('value',['../credentials','/app/credentials','not-a-uuid'])
def test_paths_are_not_accepted_as_ids(store,value):
    with pytest.raises(ValueError):snapshots._directory(value)


def test_only_verified_restore_databases_join_allowlist(store):
    database='cmccdb_restore_'+uuid.uuid4().hex
    assert not snapshots.allowed_database(database)
    directory=store/str(uuid.uuid4());directory.mkdir()
    record=directory/('restore-'+database+'.json')
    record.write_text(json.dumps({'database':database,'verified':False}))
    assert not snapshots.allowed_database(database)
    record.write_text(json.dumps({'database':database,'verified':True}))
    assert snapshots.allowed_database(database)


def test_corrupt_backup_cannot_be_restored(store):
    snapshot_id=str(uuid.uuid4());directory=store/snapshot_id;directory.mkdir()
    (directory/'database.dump').write_bytes(b'original')
    (directory/'schema.pb').write_bytes(b'descriptor')
    metadata={'format':'cmccdb-postgresql-custom-v1','verified':True,
              'dump_sha256':hashlib.sha256(b'original').hexdigest(),
              'schema_sha256':hashlib.sha256(b'descriptor').hexdigest()}
    (directory/'manifest.json').write_text(json.dumps(metadata))
    (directory/'database.dump').write_bytes(b'corrupted')
    with patch.object(snapshots.manage,'create_raw_connection') as connect:
        with pytest.raises(ValueError,match='checksum mismatch'):snapshots.restore(snapshot_id)
        connect.assert_not_called()


def test_restore_differences_distinguish_missing_changed_and_unexpected_tables():
    expected = {'tables': {'a': {'rows': 1, 'sha256': 'old'},
                           'missing': {'rows': 0, 'sha256': 'empty'}},
                'extensions': {'rdkit': '3.8'}, 'sequences': ['a_id_seq']}
    actual = {'a': {'rows': 1, 'sha256': 'changed'},
              'unexpected': {'rows': 0, 'sha256': 'empty'}}
    differences = snapshots._verification_differences(expected, actual, {'rdkit': '3.9'}, ['new_seq'])
    assert differences['tables']['a'] == {'expected': expected['tables']['a'], 'actual': actual['a']}
    assert differences['tables']['missing']['actual'] is None
    assert differences['tables']['unexpected']['expected'] is None
    assert differences['extensions']['rdkit'] == {'expected': '3.8', 'actual': '3.9'}
    assert differences['sequences'] == {'missing': ['a_id_seq'], 'unexpected': ['new_seq']}


def test_matching_restore_inventory_has_no_differences():
    expected = {'tables': {'a': {'rows': 2, 'sha256': 'same'}},
                'extensions': {'rdkit': '3.8'}, 'sequences': ['b', 'a']}
    assert snapshots._verification_differences(expected, expected['tables'], expected['extensions'], ['a', 'b']) == {}
@pytest.mark.parametrize('functions,expected', [
    ({'public.rdkit_version()': '2019.03.4'}, 'public.rdkit_version()'),
    ({'public.rdkit_version()': '4.8', 'public.rdkit_toolkit_version()': '2025.09.3'},
     'public.rdkit_toolkit_version()'),
])
def test_cache_runtime_guard_supports_actual_legacy_and_modern_version_functions(functions, expected):
    class CatalogConnection:
        def scalar(self, statement, parameters=None):
            query = str(statement)
            if query == 'SHOW server_version':
                return '12.3'
            if 'FROM pg_extension' in query:
                return '3.8'
            if 'to_regprocedure' in query:
                return parameters['function'] in functions
            assert query == 'SELECT ' + expected
            return functions[expected]
    result = snapshots._cartridge_context(CatalogConnection())
    assert result['rdkit_runtime_function'] == expected
    assert result['rdkit_runtime'] == functions[expected]
    assert result['postgres_major'] == '12'


def test_unknown_cache_runtime_is_rejected_instead_of_assuming_compatibility():
    class UnknownConnection:
        def scalar(self, statement, parameters=None):
            if str(statement) == 'SHOW server_version':
                return '12.3'
            if 'FROM pg_extension' in str(statement):
                return '3.8'
            return False
    with pytest.raises(ValueError, match='Cannot determine'):
        snapshots._cartridge_context(UnknownConnection())


def test_source_cache_recipe_requires_exact_native_constructor_bytes():
    rows = [{'id': 1, 'original': memoryview(b'object'), 'reconstructed': memoryview(b'object')},
            {'id': 3, 'original': None, 'reconstructed': None}]
    with patch.object(snapshots, '_reaction_cache_present', return_value=True), \
         patch.object(snapshots, '_cartridge_context', return_value={'runtime': 'same'}), \
         patch.object(snapshots, '_reaction_cache_rows', return_value=rows):
        recipe = snapshots._capture_reaction_cache(None)
    assert recipe['method'] == 'native-smiles-cache-v1'
    assert recipe['rows'] == [{'id': 1, 'sha256': hashlib.sha256(b'object').hexdigest()},
                              {'id': 3, 'sha256': None}]


def test_unreproducible_source_cache_is_refused():
    with pytest.raises(ValueError, match='does not reproduce reaction cache id 9'):
        snapshots._reaction_cache_hashes(
            [{'id': 9, 'original': b'original', 'reconstructed': b'different'}], verify_constructor=True)


def test_duplicate_cache_ids_are_refused():
    with pytest.raises(ValueError, match='Duplicate'):
        snapshots._reaction_cache_hashes([{'id': 2, 'original': b'a'}, {'id': 2, 'original': b'a'}])


def test_restore_preserves_source_null_cache_state_before_any_update():
    connection = Mock()
    data = {'reaction_cache': {'method': 'native-smiles-cache-v1', 'context': {'runtime': 'same'},
                               'rows': [{'id': 1, 'sha256': hashlib.sha256(b'original').hexdigest()}]}}
    with patch.object(snapshots, '_reaction_cache_present', return_value=True), \
         patch.object(snapshots, '_cartridge_context', return_value={'runtime': 'same'}), \
         patch.object(snapshots, '_reaction_cache_rows', return_value=[{'id': 1, 'original': None}]):
        with pytest.raises(ValueError, match='null states'):
            snapshots._restore_reaction_cache(connection, data)
    connection.execute.assert_not_called()


def test_changed_runtime_blocks_cache_reconstruction_before_update():
    connection = Mock()
    data = {'reaction_cache': {'method': 'native-smiles-cache-v1', 'context': {'runtime': 'old'}}}
    with patch.object(snapshots, '_reaction_cache_present', return_value=True), \
         patch.object(snapshots, '_cartridge_context', return_value={'runtime': 'new'}):
        with pytest.raises(ValueError, match='original PostgreSQL major and RDKit runtime'):
            snapshots._restore_reaction_cache(connection, data)
    connection.execute.assert_not_called()


def test_inexact_reconstructed_bytes_fail_restore_verification():
    connection = Mock()
    data = {'reaction_cache': {'method': 'native-smiles-cache-v1', 'context': {'runtime': 'same'},
                               'rows': [{'id': 1, 'sha256': hashlib.sha256(b'original').hexdigest()}]}}
    with patch.object(snapshots, '_reaction_cache_present', return_value=True), \
         patch.object(snapshots, '_cartridge_context', return_value={'runtime': 'same'}), \
         patch.object(snapshots, '_reaction_cache_rows', side_effect=[
             [{'id': 1, 'original': b'logical dump'}], [{'id': 1, 'original': b'inexact reconstruction'}]]):
        with pytest.raises(ValueError, match='bytes differ'):
            snapshots._restore_reaction_cache(connection, data)


def test_experimental_binary_archives_are_rejected_before_any_database_is_created(store):
    snapshot_id = str(uuid.uuid4())
    directory = store / snapshot_id
    directory.mkdir()
    (directory / 'manifest.json').write_text(json.dumps({
        'format': 'cmccdb-postgresql-custom-v1', 'verified': True,
        'binary_tables': [{'table': 'reactions', 'file': 'cartridge-reactions.copy'}]}))
    with patch.object(snapshots.manage, 'create_raw_connection') as connect:
        with pytest.raises(ValueError, match='Experimental binary'):
            snapshots.restore(snapshot_id)
        connect.assert_not_called()


def test_retries_do_not_launch_duplicate_jobs(store):
    key=str(uuid.uuid4())
    with patch.object(maintenance_jobs.subprocess,'Popen') as spawn:
        first=maintenance_jobs.submit('backup','staging',request_id=key)
        second=maintenance_jobs.submit('backup','staging',request_id=key)
        assert first==second
        assert spawn.call_count==1
        with pytest.raises(ValueError,match='different request'):
            maintenance_jobs.submit('migration','staging',request_id=key)
        assert spawn.call_count==1


def test_missing_worker_is_reported(store):
    job_id=str(uuid.uuid4());(store/'jobs').mkdir()
    path=store/'jobs'/(job_id+'.json')
    path.write_text(json.dumps({'id':job_id,'status':'running','pid':99999999}))
    with patch.object(maintenance_jobs.os,'kill',side_effect=ProcessLookupError):
        assert maintenance_jobs.status(job_id)['status']=='failed'


def test_abandoned_queued_job_does_not_wait_forever(store):
    job_id=str(uuid.uuid4());(store/'jobs').mkdir()
    path=store/'jobs'/(job_id+'.json')
    path.write_text(json.dumps({'id':job_id,'status':'queued',
        'created_at':(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()}))
    assert maintenance_jobs.status(job_id)['status']=='failed'


@pytest.mark.parametrize('action,database',[('shell','staging'),('backup','postgres')])
def test_jobs_accept_only_maintenance_actions(store,action,database):
    with pytest.raises(ValueError):maintenance_jobs.submit(action,database)
