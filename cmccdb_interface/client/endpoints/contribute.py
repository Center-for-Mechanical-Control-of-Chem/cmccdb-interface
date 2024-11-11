

import flask
import os
import sys
import importlib
from cmccdb_interface.client import handlers
from cmccdb_interface.database import manage, datasets

# WEB_UPLOADER_NAME = "Web Uploader"
# WEB_UPLOADER_EMAIL = "maboyer@tamu.edu"
# def upload():
#     import cmccdb_interface.database.datasets
#     datasets = importlib.reload(cmccdb_interface.database.datasets)
#     import cmccdb_schema.scripts.construct_dataset
#     importlib.reload(cmccdb_schema.scripts.construct_dataset)

#     database_name = flask.request.args.get("database")
#     default_uploader = os.environ.get("CMCCDB_UPLOADER_NAME", WEB_UPLOADER_NAME)
#     default_email = os.environ.get("CMCCDB_UPLOADER_EMAIL", WEB_UPLOADER_EMAIL)

#     try:
#         file_name = flask.request.files['uploadFile'].filename
#         body = flask.request.files['uploadFile'].read()

#         dataset = datasets.prep_and_create_pb_dataset(
#             file_name,
#             body,
#             uploader_name=flask.request.args.get("user", default_uploader),
#             uploader_email=flask.request.args.get("email", default_email)
#             )
#         manage.add_dataset(dataset, database_name=database_name)
#         # backups.commit_backup()
#         return flask.jsonify({"redirect_url":"browse"})
#     except Exception as error:  # pylint: disable=broad-except
#         return flask.abort(handlers.make_error_response(error, 406))

# def delete_dataset():
#     """Writes the request body to the datasets table without validation."""
#     try:
#         database_name = flask.request.args.get("database")
#         dataset_id = flask.request.args.get("dataset_id")
#         manage.delete_dataset(dataset_id, database_name=database_name)
#         return handlers.make_string_response("ok")
#     except Exception as error:  # pylint: disable=broad-except
#         flask.abort(handlers.make_error_response(error, 406))