# Copyright 2020 Open Reaction Database Project Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Query web interface to the Open Reaction Database in Postgres.

The client is stateless. Full information is in the URL so results can be
linked. Query parameters are communicated in URL GET params:

  component=<pattern;source;(exact|substructure|similarity|smarts)>

    The second token specifies whether the predicate should match an input or
    an output.

    The last token specifies the matching criterion. The default is "exact".
    The pattern is a SMILES string, unless the token is "smarts" in which case
    the pattern is a SMARTS string.

    Component may be repeated any number of times.

  reaction_ids=<ids>

  reaction_smarts=<smarts>

These query types are mutually exclusive. All query parameters are assumed to
be URL-encoded.
"""

# pylint: disable=too-many-locals

import os
import flask
from ..database import manage, datasets, backups

from . import handlers

bp = flask.Blueprint("edit", __name__, url_prefix="/client", template_folder=".")

WEB_UPLOADER_NAME = "Web Uploader"
WEB_UPLOADER_EMAIL = "maboyer@tamu.edu"
@bp.route("/api/upload", methods=["POST"])
def upload_dataset():
    """Writes the request body to the datasets table without validation."""

    database_name = flask.request.args.get("database")
    default_uploader = os.environ.get("CMCCDB_UPLOADER_NAME", WEB_UPLOADER_NAME)
    default_email = os.environ.get("CMCCDB_UPLOADER_EMAIL", WEB_UPLOADER_EMAIL)

    try:
        file_name = flask.request.files['uploadFile'].filename
        body = flask.request.files['uploadFile'].read()

        dataset = datasets.prep_and_create_pb_dataset(
            file_name,
            body,
            uploader_name=flask.request.args.get("user", default_uploader),
            uploader_email=flask.request.args.get("email", default_email)
            )
        manage.add_dataset(dataset, database_name=database_name)
        # backups.commit_backup()
        return flask.jsonify({"redirect_url":"browse"})
    except Exception as error:  # pylint: disable=broad-except
        return flask.abort(handlers.make_error_response(error, 406))

@bp.route("/api/reconfigure", methods=["POST"])
def reconfigure_database():
    """Writes the request body to the datasets table without validation."""

    database_name = flask.request.args.get("database")
    try:
        manage.reset_database(database_name, rebuild=True)
        manage.configure_database(database_name)
        return handlers.make_string_response("ok")
    except Exception as error:  # pylint: disable=broad-except
        return flask.abort(handlers.make_error_response(error, 406))

@bp.route("/api/delete/<dataset_id>", methods=["POST"])
def delete_dataset(dataset_id):
    """Writes the request body to the datasets table without validation."""
    try:
        database_name = flask.request.args.get("database")
        manage.delete_dataset(dataset_id, database_name=database_name)
        return handlers.make_string_response("ok")
    except Exception as error:  # pylint: disable=broad-except
        return flask.abort(handlers.make_error_response(error, 406))

ENDPOINT_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "endpoints")
@bp.route("/api/dev/<endpoint>/<name>", methods=["GET", "POST"])
def test_endpoint(endpoint, name):
    import importlib, os, sys

    if ENDPOINT_FOLDER not in sys.path:
        sys.path.insert(0, ENDPOINT_FOLDER)
    
    try:
        caller = None
        if endpoint+".py" in os.listdir(ENDPOINT_FOLDER):
            if endpoint in sys.modules:
                mod = importlib.reload(sys.modules[endpoint])
            else:
                mod = importlib.import_module(endpoint)
            caller = getattr(mod, name)
        if caller is None:
            raise ImportError(f"No endpoint module {endpoint}")
        return caller()

    except Exception as error:  # pylint: disable=broad-except
        return flask.abort(handlers.make_error_response(error, 406))
