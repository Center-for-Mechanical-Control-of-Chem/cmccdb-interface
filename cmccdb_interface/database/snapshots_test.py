"""Corruption, path and retry boundaries for the snapshot service."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
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
