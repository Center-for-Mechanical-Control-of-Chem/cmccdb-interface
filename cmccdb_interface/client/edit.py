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

import dataclasses
import gzip
import io
import os
import uuid
import subprocess
from typing import List, Optional, Tuple

import flask
from rdkit import Chem

import sqlalchemy
from sqlalchemy import orm

import google.protobuf.message  # pytype: disable=import-error
from ord_schema.orm import database
from google.protobuf import text_format  # pytype: disable=import-error
from ord_schema.proto import dataset_pb2, reaction_pb2

bp = flask.Blueprint("edit", __name__, url_prefix="/client", template_folder=".")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "ord-postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "ord-postgres")
POSTGRES_DATABASE = os.getenv("POSTGRES_DATABASE", "ord")

from .. import client

def get_engine(database_name=None):
    if database_name is None:
        database_name = POSTGRES_DATABASE or client.POSTGRES_DB
    connection_string = database.get_connection_string(
        database=database_name,
        username=POSTGRES_USER or client.POSTGRES_USER,
        password=POSTGRES_PASSWORD or client.POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT or client.POSTGRES_PORT,
    )
    engine = sqlalchemy.create_engine(connection_string, future=True)
    return engine
def get_session(database_name=None):
    engine = get_engine(database_name=database_name)
    database.prepare_database(engine)
    return orm.Session(engine)
def get_isolated_connection():
    import psycopg2

    return psycopg2.connect(
        # dbname=POSTGRES_DATABASE,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, host=POSTGRES_HOST, port=POSTGRES_PORT, options="-c search_path=public,ord"
    )

DATA_DIR = "/home/cmccdb-data"
BACKUP_DIR = DATA_DIR + "/uploads"

@bp.route("/api/upload", methods=["POST"])
def upload_dataset():
    """Writes the request body to the datasets table without validation."""

    database_name = flask.request.args.get("database")
    if database_name is None:
        database_name = POSTGRES_DATABASE or client.POSTGRES_DB

    try:
        file_name = flask.request.args.get("filename")
        data = flask.request.get_data()

        file_id = uuid.uuid4()
        if file_name is None:
            file_name = "Untitled.pbtxt"

        file_name, ext = os.path.splitext(os.path.basename(file_name))[0]
        file_name = f"{file_name}-{file_id}{ext}"

        proper_file = os.path.join(BACKUP_DIR, file_name)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        with open(proper_file, "w+") as dataset_file:
            dataset_file.write(data)

        cur_dir = os.getcwd()
        os.chdir(BACKUP_DIR)
        subprocess.call(
            ["git", "commit", "-a", "-m", "'new data upload'"]
        )
        subprocess.call(
            ["git", "push", "-a"]
        )

        if ext in {".xlsx", ".csv"}:
            from ord_schema.scripts.construct_database import main

            main({
                "--data":proper_file,
                "--name":flask.request.args.get("user", "Web Uploader"),
                "--email":flask.request.args.get("email", "maboyer@tamu.edu")
            })

            proper_file = os.path.splitext(proper_file)[0] + ".pbtxt"

            with open(proper_file) as dataset_file:
                data = dataset_file.read()

        try:
            dataset = dataset_pb2.Dataset.FromString(data)
        except (google.protobuf.message.DecodeError, TypeError):
            dataset = dataset_pb2.Dataset()
            text_format.Parse(flask.request.get_data(as_text=True), dataset)
        with get_session(database_name) as session:
            database.add_dataset(dataset, session)
            session.flush()
            # database.update_rdkit_tables(dataset.dataset_id, session=session)
            # session.flush()
            # database.update_rdkit_ids(dataset.dataset_id, session=session)
            session.commit()
        return "ok"
    except Exception as error:  # pylint: disable=broad-except
        flask.abort(flask.make_response(str(error), 406))

@bp.route("/api/reconfigure", methods=["POST"])
def reconfigure_database():
    """Writes the request body to the datasets table without validation."""

    database_name = flask.request.args.get("database")
    if database_name is None:
        database_name = POSTGRES_DATABASE or client.POSTGRES_DB

    try:
        conn = get_isolated_connection()
        with conn.cursor() as cur:
            conn.autocommit = True
            cur.execute(f"DROP DATABASE IF EXISTS {database_name};")
            cur.execute(f"CREATE DATABASE {database_name};")
        database.prepare_database(get_engine(database_name))
        return "ok"
    except Exception as error:  # pylint: disable=broad-except
        flask.abort(flask.make_response(str(error), 406))

@bp.route("/api/delete/<dataset_id>", methods=["POST"])
def delete_dataset(dataset_id):
    """Writes the request body to the datasets table without validation."""
    try:
        # try:
        #     dataset = dataset_pb2.Dataset.FromString(flask.request.get_data())
        # except (google.protobuf.message.DecodeError, TypeError):
        #     dataset = dataset_pb2.Dataset()
        #     text_format.Parse(flask.request.get_data(as_text=True), dataset)

        database_name = flask.request.args.get("database")
        if database_name is None:
            database_name = POSTGRES_DATABASE or client.POSTGRES_DB

        with get_session(database_name) as session:
            database.delete_dataset(dataset_id, session)
            session.flush()
            # database.update_rdkit_tables(dataset.dataset_id, session=session)
            # session.flush()
            # database.update_rdkit_ids(dataset.dataset_id, session=session)
            session.commit()
        return "ok"
    except Exception as error:  # pylint: disable=broad-except
        flask.abort(flask.make_response(str(error), 406))