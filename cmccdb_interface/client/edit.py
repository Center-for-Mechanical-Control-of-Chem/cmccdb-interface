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

from . import handlers, authentication

bp = flask.Blueprint("edit", __name__, url_prefix="/client", template_folder=".")

WEB_UPLOADER_NAME = "Web Uploader"
WEB_UPLOADER_EMAIL = "maboyer@tamu.edu"
WEB_UPLOADER_ENV_NAME = "CMCCDB_UPLOADER_NAME"
WEB_UPLOADER_ENV_EMAIL = "CMCCDB_UPLOADER_EMAIL"
def get_uploader_info():
    name = flask.request.args.get("name")
    username = flask.request.args.get("username")
    email = flask.request.args.get("email")

    if name is None:
        if username is not None and " " in username:
            name = username
        else:
            name = os.environ.get(WEB_UPLOADER_ENV_NAME, WEB_UPLOADER_NAME)
    if email is None:
        name = os.environ.get(WEB_UPLOADER_ENV_EMAIL, WEB_UPLOADER_EMAIL)
    
    return {
        "name":name,
        "email":email
    }    

STAGING_DATABASE = "staging"
@bp.route("/api/upload", methods=["POST"])
def upload_dataset():
    """Writes the request body to the datasets table without validation."""

    database_name = flask.request.args.get("database")
    try:
        auth_info = authentication.gh_get_cache_user_info()
        if auth_info is None:
            raise ValueError("unauthenticated users can't upload data")
        if database_name != STAGING_DATABASE and not auth_info["member"]:
            raise ValueError("unauthenticated users can't upload data")

        uploader_info = get_uploader_info()
        file_name = flask.request.files['uploadFile'].filename
        body = flask.request.files['uploadFile'].read()

        dataset = datasets.prep_and_create_pb_dataset(
            file_name,
            body,
            uploader_name=uploader_info["name"],
            uploader_email=uploader_info["email"]
            )
        manage.add_dataset(dataset, database_name=database_name)
        try:
            backups.git_backup()
        except OSError as e:
            from cmccdb_schema.logging_helpers import get_logger
            logger = get_logger('uploads')
            logger.exception("Backup failed, maybe")
        return {'dataset_id':dataset.dataset_id}
    except Exception as error:  # pylint: disable=broad-except
        return flask.abort(handlers.make_error_response(error, 406))

@bp.route("/api/reconfigure", methods=["POST"])
def reconfigure_database():
    """Writes the request body to the datasets table without validation."""

    database_name = flask.request.args.get("database")
    try:
        auth_info = authentication.gh_get_cache_user_info()
        if auth_info is None:
            raise ValueError("unauthenticated users can't reconfigure databases")
        if not auth_info["owner"]:
            raise ValueError("only CMCC admins can reconfigure databases")

        manage.reset_database(database_name, force_quit=True)
        manage.configure_database(database_name)
        return handlers.make_string_response("ok")
    except Exception as error:  # pylint: disable=broad-except
        return flask.abort(handlers.make_error_response(error, 406))

@bp.route("/api/delete/<dataset_id>", methods=["POST"])
def delete_dataset(dataset_id):
    """Writes the request body to the datasets table without validation."""
    try:
        auth_info = authentication.gh_get_cache_user_info()
        if auth_info is None:
            raise ValueError("unauthenticated users can't reconfigure databases")
        if not auth_info["owner"]:
            raise ValueError("only CMCC admins can reconfigure databases")

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
        # auth_info = authentication.gh_get_cache_user_info()
        # if auth_info is None:
        #     raise ValueError("unauthenticated users can't use the dev endpoints")
        # if not auth_info["owner"]:
        #     raise ValueError("only CMCC admins can use the dev endpoints databases")

        caller = None
        if endpoint+".py" in os.listdir(ENDPOINT_FOLDER):
            if endpoint in sys.modules:
                mod = importlib.reload(sys.modules[endpoint])
            else:
                mod = importlib.import_module(endpoint)
            caller = getattr(mod, name, None)
        if caller is None:
            raise ImportError(f"No endpoint {endpoint}.{name}")
        return caller()

    except Exception as error:  # pylint: disable=broad-except
        return flask.abort(handlers.make_error_response(error, 406))
