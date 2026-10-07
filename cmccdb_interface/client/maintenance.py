"""Owner-only, CSRF-protected database maintenance API."""
import hmac
import os
import secrets
from functools import wraps

import flask
from cmccdb_schema.orm import schema_updates
from cmccdb_schema.orm.mappers import Base
from cmccdb_interface.database import manage, snapshots, maintenance_jobs
from . import authentication

bp = flask.Blueprint('maintenance', __name__, url_prefix='/client')


def protected(function):
    @wraps(function)
    def call(*args, **kwargs):
        enabled = os.getenv('CMCCDB_MAINTENANCE_API', '').lower() in {'true', '1', 'yes', 'on'}
        development = os.getenv('CMCCDB_DEV_BACKEND', '').lower() in {'true', '1', 'yes', 'on'}
        if not (enabled or development):
            flask.abort(404)
        info = authentication.gh_get_cache_user_info()
        if info is None:
            flask.abort(401)
        if not info.get('owner'):
            flask.abort(403)
        if not snapshots.allowed_database(flask.request.args.get('database', 'staging')):
            flask.abort(400)
        if flask.request.method == 'POST':
            token = flask.session.get('maintenance_csrf')
            supplied = flask.request.headers.get('X-CMCCDB-CSRF', '')
            if not token or not hmac.compare_digest(token, supplied):
                flask.abort(403)
            if not flask.request.is_json:
                flask.abort(415)
            if not isinstance(flask.request.get_json(), dict):
                flask.abort(400)
        try:
            return function(*args, **kwargs)
        except FileNotFoundError:
            flask.abort(404)
        except (ValueError, schema_updates.MigrationRequired) as error:
            return flask.jsonify(error=str(error)), 409
    return call


def _database():
    return flask.request.args.get('database', 'staging')


@bp.route('/api/maintenance', methods=['GET'])
@protected
def info():
    flask.session.setdefault('maintenance_csrf', secrets.token_urlsafe(32))
    response = flask.jsonify(csrf_token=flask.session['maintenance_csrf'],
                             actions=['backup', 'baseline', 'migration', 'restore'])
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/api/migration', methods=['GET', 'POST'])
@protected
def migration():
    engine = manage.get_engine(database_name=_database())
    try:
        with engine.connect() as connection:
            preview = schema_updates.plan(connection, Base.metadata)
        if flask.request.method == 'GET':
            return flask.jsonify(preview)
        payload = flask.request.get_json()
        if payload.get('fingerprint') != preview['fingerprint'] or not preview['compatible']:
            return flask.jsonify(error='Stale or incompatible migration plan', plan=preview), 409
        if not preview['required']:
            result = schema_updates.apply(engine, Base.metadata, preview['fingerprint'],
                lambda _: None)  # No DDL means no backup is needed.
            return flask.jsonify(result)
        if not preview['tracked']:
            return flask.jsonify(error='Create a baseline backup with the old schema before deployment'), 409
        return flask.jsonify(maintenance_jobs.submit('migration', _database(),
            fingerprint=preview['fingerprint'], request_id=flask.request.headers.get('Idempotency-Key'))), 202
    finally:
        engine.dispose()


@bp.route('/api/backup', methods=['POST'])
@protected
def backup():
    payload = flask.request.get_json()
    action = 'baseline' if payload.get('record_baseline') is True else 'backup'
    return flask.jsonify(maintenance_jobs.submit(action, _database(),
        request_id=flask.request.headers.get('Idempotency-Key'))), 202


@bp.route('/api/maintenance/jobs/<job_id>', methods=['GET'])
@protected
def job(job_id):
    return flask.jsonify(maintenance_jobs.status(job_id))


@bp.route('/api/backup/<snapshot_id>', methods=['GET'])
@protected
def backup_info(snapshot_id):
    return flask.jsonify(snapshots.manifest(snapshot_id))


@bp.route('/api/backup/<snapshot_id>/download', methods=['GET'])
@protected
def download(snapshot_id):
    snapshots.manifest(snapshot_id)
    return flask.send_file(snapshots._directory(snapshot_id) / 'backup.zip', as_attachment=True,
                           download_name='cmccdb-' + snapshots.identifier(snapshot_id) + '.zip')


@bp.route('/api/backup/<snapshot_id>/restore', methods=['POST'])
@protected
def restore(snapshot_id):
    snapshots.manifest(snapshot_id)
    if flask.request.get_json():
        flask.abort(400)  # Destination selection and arbitrary restore options are prohibited.
    return flask.jsonify(maintenance_jobs.submit('restore', _database(), snapshot_id=snapshot_id,
        request_id=flask.request.headers.get('Idempotency-Key'))), 202
