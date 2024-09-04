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

def get_session():
    connection_string = database.get_connection_string(
        database=POSTGRES_HOST or client.POSTGRES_DB,
        username=POSTGRES_USER or client.POSTGRES_USER,
        password=POSTGRES_PASSWORD or client.POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT or client.POSTGRES_PORT,
    )
    engine = sqlalchemy.create_engine(connection_string, future=True)
    with engine.begin() as connection:  # pytype: disable=attribute-error
        connection.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS tsm_system_rows"))
    database.prepare_database(engine)
    return orm.Session(engine)

@bp.route("/api/upload", methods=["POST"])
def upload_dataset():
    """Writes the request body to the datasets table without validation."""
    try:
        try:
            dataset = dataset_pb2.Dataset.FromString(flask.request.get_data())
        except (google.protobuf.message.DecodeError, TypeError):
            dataset = dataset_pb2.Dataset()
            text_format.Parse(flask.request.get_data(as_text=True), dataset)
        with get_session() as session:
            database.add_dataset(dataset, session)
            session.flush()
            # database.update_rdkit_tables(dataset.dataset_id, session=session)
            # session.flush()
            # database.update_rdkit_ids(dataset.dataset_id, session=session)
            session.commit()
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

        with get_session() as session:
            database.delete_dataset(dataset_id, session)
            session.flush()
            # database.update_rdkit_tables(dataset.dataset_id, session=session)
            # session.flush()
            # database.update_rdkit_ids(dataset.dataset_id, session=session)
            session.commit()
        return "ok"
    except Exception as error:  # pylint: disable=broad-except
        flask.abort(flask.make_response(str(error), 406))
