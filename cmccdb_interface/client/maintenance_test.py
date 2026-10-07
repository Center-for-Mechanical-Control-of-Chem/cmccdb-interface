"""Security boundaries for the database maintenance API."""
import uuid
import flask
import pytest
from unittest.mock import patch
from cmccdb_interface.client import maintenance


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('CMCCDB_MAINTENANCE_API', 'true')
    monkeypatch.delenv('CMCCDB_DEV_BACKEND', raising=False)
    app = flask.Flask(__name__)
    app.secret_key = 'test-only-secret'
    app.register_blueprint(maintenance.bp)
    return app.test_client()


@pytest.mark.parametrize('identity,code', [(None,401),({'owner':False},403)])
def test_owner_required(client, identity, code):
    with patch.object(maintenance.authentication,'gh_get_cache_user_info',return_value=identity):
        assert client.get('/client/api/maintenance').status_code == code


def test_disabled_api(client, monkeypatch):
    monkeypatch.setenv('CMCCDB_MAINTENANCE_API','false')
    assert client.get('/client/api/maintenance').status_code == 404


def test_mutations_require_csrf_and_json(client):
    with patch.object(maintenance.authentication,'gh_get_cache_user_info',return_value={'owner':True}):
        assert client.post('/client/api/backup',json={}).status_code == 403
        token=client.get('/client/api/maintenance').get_json()['csrf_token']
        assert client.post('/client/api/backup',json={},headers={'X-CMCCDB-CSRF':'wrong'}).status_code == 403
        assert client.post('/client/api/backup',data='x',headers={'X-CMCCDB-CSRF':token}).status_code == 415
        assert client.post('/client/api/backup',json=[],headers={'X-CMCCDB-CSRF':token}).status_code == 400


def test_database_allowlist(client):
    with patch.object(maintenance.authentication,'gh_get_cache_user_info',return_value={'owner':True}):
        assert client.get('/client/api/maintenance?database=postgres').status_code == 400


def test_backup_queued_without_request_timeout(client):
    with patch.object(maintenance.authentication,'gh_get_cache_user_info',return_value={'owner':True}), \
         patch.object(maintenance.maintenance_jobs,'submit',return_value={'status':'queued','id':str(uuid.uuid4())}) as submit:
        token=client.get('/client/api/maintenance').get_json()['csrf_token']
        response=client.post('/client/api/backup?database=staging',json={'record_baseline':True},headers={'X-CMCCDB-CSRF':token})
        assert response.status_code == 202
        assert submit.call_args.args == ('baseline','staging')


def test_restore_does_not_accept_destination(client):
    with patch.object(maintenance.authentication,'gh_get_cache_user_info',return_value={'owner':True}), \
         patch.object(maintenance.snapshots,'manifest',return_value={}), \
         patch.object(maintenance.maintenance_jobs,'submit') as submit:
        token=client.get('/client/api/maintenance').get_json()['csrf_token']
        response=client.post('/client/api/backup/'+str(uuid.uuid4())+'/restore',json={'database':'cmcc'},headers={'X-CMCCDB-CSRF':token})
        assert response.status_code == 400
        submit.assert_not_called()
