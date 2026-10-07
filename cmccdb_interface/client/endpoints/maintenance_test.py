"""Development adapters; every maintenance action keeps the production guard."""
import flask
import hashlib
from pathlib import Path
from cmccdb_interface.client import maintenance

info = maintenance.info
backup = maintenance.backup
migration = maintenance.migration


@maintenance.protected
def setup_clients():
    """MCP transfers omit executable bits; enable only these verified Debian tools."""
    hashes = {'pg_dump':'8e66e95531070796aebb01bea1282949535c5d17b44117ade6e1655adc370225',
              'pg_restore':'da48dd313cdfa368b379fca784b4e586f80c8b2cb9795f49241568fe9ff36c52'}
    root = Path(__file__).parents[2] / '.pg-tools/usr/lib/postgresql/15/bin'
    for name, digest in hashes.items():
        file = root / name
        if hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise ValueError('PostgreSQL client checksum mismatch')
        file.chmod(0o755)
    return flask.jsonify(verified=True)


def job():
    return maintenance.job(flask.request.args.get('id', ''))


def restore():
    return maintenance.restore(flask.request.args.get('id', ''))


def download():
    return maintenance.download(flask.request.args.get('id', ''))
