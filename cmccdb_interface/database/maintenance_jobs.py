"""Durable status for narrowly scoped backup/migration/restore worker processes."""
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

from . import snapshots


def submit(action, database, fingerprint=None, snapshot_id=None, request_id=None):
    if action not in {'backup', 'baseline', 'migration', 'restore'} or not snapshots.allowed_database(database):
        raise ValueError('Unsupported maintenance action/database')
    job_id = snapshots.identifier(request_id) if request_id else str(uuid.uuid4())
    directory = snapshots.root() / 'jobs'
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / (job_id + '.json')
    payload = {'action': action, 'database': database, 'fingerprint': fingerprint, 'snapshot_id': snapshot_id}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        previous = json.loads(path.read_text())
        if previous['request_sha256'] != digest:
            raise ValueError('Idempotency key already belongs to a different request')
        return previous
    state = {'id': job_id, 'status': 'queued', 'request': payload, 'request_sha256': digest,
             'created_at': datetime.now(timezone.utc).isoformat()}
    with os.fdopen(fd, 'w') as file:
        json.dump(state, file)
    try:
        log = (directory / (job_id + '.log')).open('ab')
        os.chmod(log.name, 0o600)
        with log:
            subprocess.Popen([sys.executable, '-m', 'cmccdb_interface.database.maintenance_jobs', job_id],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    except Exception:
        state['status'] = 'failed'
        state['error'] = 'Could not launch maintenance worker'
        snapshots._atomic_json(path, state)
        raise
    return state


def status(job_id):
    path = snapshots.root() / 'jobs' / (snapshots.identifier(job_id) + '.json')
    state = json.loads(path.read_text())
    created = datetime.fromisoformat(state['created_at']) if state.get('created_at') else datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    if state['status'] == 'queued' and (datetime.now(timezone.utc)-created).total_seconds()>60:
        state.update(status='failed', error='Maintenance worker did not start; inspect its saved log before retrying')
        snapshots._atomic_json(path, state)
    if state['status'] == 'running':
        try:
            os.kill(state['pid'], 0)
        except ProcessLookupError:
            state['status'] = 'failed'
            state['error'] = 'Worker stopped before completion; inspect saved backups before retrying'
            snapshots._atomic_json(path, state)
    return state


def run(job_id):
    from cmccdb_schema.orm import schema_updates
    from cmccdb_schema.orm.mappers import Base
    from . import manage
    path = snapshots.root() / 'jobs' / (snapshots.identifier(job_id) + '.json')
    state = json.loads(path.read_text())
    if state['status'] != 'queued':
        return
    state.update(status='running', pid=os.getpid())
    snapshots._atomic_json(path, state)
    request = state['request']
    engine = manage.get_engine(database_name=request['database'])
    try:
        action = request['action']
        if action == 'baseline':
            snapshots.bootstrap(engine)
            result = snapshots.create(engine, request['database'])
        elif action == 'backup':
            result = snapshots.create(engine, request['database'])
        elif action == 'restore':
            result = snapshots.restore(request['snapshot_id'])
        elif action == 'migration':
            result = schema_updates.apply(engine, Base.metadata, request['fingerprint'],
                lambda connection: snapshots.create_verified(engine, request['database'], connection=connection))
        else:
            raise ValueError('Unsupported worker action')
        state.update(status='complete', result=result)
    except Exception as error:
        state.update(status='failed', error=str(error))
    finally:
        engine.dispose()
        snapshots._atomic_json(path, state)


if __name__ == '__main__':
    run(sys.argv[1])
