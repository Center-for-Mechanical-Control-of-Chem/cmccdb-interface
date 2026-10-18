"""Request-time write gate for a prepared, private release candidate."""
import os
from pathlib import Path
import flask


def read_only(control):
    return bool(control and (Path(control, 'read-only').exists() or not Path(control, 'writable').is_file()))


def install(app):
    @app.before_request
    def frozen_release():
        control = os.environ.get('CMCCDB_RELEASE_CONTROL')
        if not control:
            return None
        # Unknown routes are blocked too. Search endpoints include POST reads.
        if read_only(control) and flask.request.blueprint not in {
            'api', 'authentication', 'auxiliary'
        } and flask.request.endpoint not in {'static', 'show_ketcher', 'edit.download_auxiliary',
                                              'release_info'}:
            return flask.jsonify(error='This release is read-only during validation or cutover'), 503
        return None

    @app.get('/client/api/release')
    def release_info():
        control = os.environ.get('CMCCDB_RELEASE_CONTROL')
        return flask.jsonify(release=os.environ.get('CMCCDB_RELEASE_ID'),
            read_only=read_only(control))
