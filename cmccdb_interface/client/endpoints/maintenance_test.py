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


"""Draft additions to the existing owner-only development maintenance endpoint."""


@maintenance.protected
def restore_diagnostics():
    """Inspect only a failed, recorded restore; accept no SQL or arbitrary target."""
    import json
    import re
    from sqlalchemy import text
    from cmccdb_interface.database import manage, snapshots

    if flask.request.method != 'GET':
        flask.abort(405)
    snapshot_id = snapshots.identifier(flask.request.args.get('id', ''))
    original = snapshots.manifest(snapshot_id)
    source = flask.request.args.get('database', 'staging')
    if original['database'] != source:
        flask.abort(400)
    reports = sorted(snapshots._directory(snapshot_id).glob('verification-failed-cmccdb_restore_*.json'),
                     key=lambda path: path.stat().st_mtime_ns)
    if not reports:
        flask.abort(404)
    report = json.loads(reports[-1].read_text())
    restored = report['database']
    if (report.get('snapshot_id') != snapshot_id or report.get('verified') is not False or
            not re.fullmatch(r'cmccdb_restore_[0-9a-f]{32}', restored) or
            reports[-1].name != 'verification-failed-' + restored + '.json'):
        flask.abort(400)

    inventories, rows, types, reconstruction = {}, {}, {}, {}
    for label, database in [('source', source), ('restored', restored)]:
        engine = manage.get_engine(database_name=database)
        try:
            with engine.begin() as connection:
                connection.execute(text('SET TRANSACTION READ ONLY'))
                inventories[label] = snapshots.inventory(connection)
                rows[label] = {row.id: dict(row._mapping) for row in connection.execute(text(
                    'SELECT id, reaction_smiles, reaction::text AS reaction_text '
                    'FROM rdkit.reactions ORDER BY id'))}
                types[label] = [dict(row._mapping) for row in connection.execute(text(
                    "SELECT t.typname, n.nspname AS type_schema, "
                    "t.typinput::regproc::text AS input, t.typoutput::regproc::text AS output, "
                    "t.typsend::regproc::text AS send FROM pg_type t "
                    "JOIN pg_namespace n ON n.oid=t.typnamespace WHERE t.typname='reaction'"))]
                reconstruction[label] = dict(connection.execute(text(
                    'SELECT count(*) AS rows, count(*) FILTER (WHERE reaction IS NULL) AS nulls, '
                    'count(*) FILTER (WHERE reaction IS NOT NULL AND '
                    'reaction_send(reaction) IS DISTINCT FROM '
                    'reaction_send(reaction_from_smiles(reaction_smiles::cstring))) AS binary_mismatches '
                    'FROM rdkit.reactions')).one()._mapping)
        finally:
            engine.dispose()
    differences = []
    for row_id in sorted(set(rows['source']) | set(rows['restored'])):
        left, right = rows['source'].get(row_id), rows['restored'].get(row_id)
        if left != right:
            differences.append({'id': row_id, 'source': left, 'restored': right})
    result = dict(snapshot_id=snapshot_id, source_database=source, restored_database=restored,
                         snapshot_inventory=original['tables']['rdkit.reactions'],
                         current_inventory={k: v['rdkit.reactions'] for k, v in inventories.items()},
                         source_versus_snapshot=snapshots._verification_differences(
                             original, inventories['source'], original['extensions'], original['sequences']),
                         differing_reaction_rows=len(differences), samples=differences[:3],
                         reaction_types=types, cache_reconstruction=reconstruction, database_writes=False)
    if flask.request.args.get('format') == 'html':
        return flask.render_template_string(
            '<!doctype html><title>CMCCDB restore diagnostics</title>'
            '<h1>Read-only restore diagnostics</h1>'
            '<p>Source and failed isolated restore comparison; no database writes.</p>'
            '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">{{report}}</pre>',
            report=json.dumps(result, indent=2))
    return flask.jsonify(result)
