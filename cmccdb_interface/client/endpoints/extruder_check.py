"""Read-only development diagnostics for extruder schema work."""
import shutil
import subprocess
import sys
import os
import flask
from sqlalchemy import text
from cmccdb_interface.database import manage


def runtime():
    from cmccdb_interface.database import snapshots
    engine = manage.get_engine(database_name='staging')
    try:
        with engine.connect() as connection:
            version = connection.scalar(text('SHOW server_version'))
        return flask.jsonify(server_version=version,
            app_source=sys.modules[flask.current_app.import_name].__file__,
            maintenance_routes=[str(r) for r in flask.current_app.url_map.iter_rules() if 'maintenance' in str(r) or 'migration' in str(r) or 'backup' in str(r)],
            maintenance_enabled=os.getenv('CMCCDB_MAINTENANCE_API'), development=os.getenv('CMCCDB_DEV_BACKEND'),
            pg_dump=subprocess.run([snapshots.tool('pg_dump'), '--version'], env=snapshots.environment(), capture_output=True, text=True).stdout,
            pg_restore=subprocess.run([snapshots.tool('pg_restore'), '--version'], env=snapshots.environment(), capture_output=True, text=True).stdout)
    finally:
        engine.dispose()
