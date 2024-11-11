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

from cmccdb_schema.proto import reaction_pb2

from ..visualization import generate_text, filters
from ..database import query
from . import handlers

bp = flask.Blueprint("api", __name__, url_prefix="/client", template_folder=".")

BOND_LENGTH = 20
MAX_RESULTS = 1000


@bp.route("/id/<reaction_id>")
def show_id(reaction_id):
    """Returns the pbtxt of a single reaction as plain text."""
    database_name = flask.request.args.get("database")

    results = query.QueryHandler(database_name).run_query(query.ReactionIdQuery([reaction_id]))
    if len(results) == 0:
        return flask.abort(404)
    reaction = results[0].reaction
    reaction_summary = generate_text.generate_html(reaction, bond_length=BOND_LENGTH)
    return flask.render_template(
        "reaction_view.html",
        reaction=reaction,
        dataset_id=results[0].dataset_id,
        reaction_summary=reaction_summary,
        bond_length=BOND_LENGTH,
    )


@bp.route("/api/render/<reaction_id>")
def render_reaction(reaction_id):
    """Renders a reaction as an HTML table with images and text."""
    database_name = flask.request.args.get("database")

    command = query.ReactionIdQuery([reaction_id])
    results = query.QueryHandler(database_name).run_query(command)
    compact = flask.request.args.get("compact") != "false"  # defaults to true
    print("compact", compact)
    if len(results) == 0 or len(results) > 1:
        return flask.abort(404)
    result = results[0]
    try:
        html = generate_text.generate_html(reaction=result.reaction, compact=compact)
        return flask.jsonify(html)
    except (ValueError, KeyError):
        return flask.jsonify("[Reaction cannot be displayed]")


@bp.route("/api/render/compound/svg", methods=["POST"])
def render_compound():
    """Returns svg of compound"""
    data = flask.request.get_data()
    compound = reaction_pb2.Compound()
    compound.ParseFromString(data)
    svg = filters._compound_svg(compound)  # pylint: disable=protected-access
    try:
        return flask.jsonify(svg)
    except (ValueError, KeyError):
        return flask.jsonify("[Compound cannot be displayed]")


@bp.route("/api/fetch_reactions", methods=["POST"])
def fetch_reactions():
    """Fetches a list of Reactions by ID."""
    database_name = flask.request.args.get("database")

    print("request", flask.request.get_json())
    reaction_ids = flask.request.get_json()
    command = query.ReactionIdQuery(reaction_ids)
    try:
        results = query.QueryHandler(database_name).run_query(command, query_props=True)
        return flask.jsonify(prep_results_for_json(results))
    except query.QueryException as error:
        return flask.abort(handlers.make_error_response(error, 400))


@bp.route("/api/fetch_datasets", methods=["GET"])
def fetch_datasets():
    """Fetches info about the current datasets."""
    database_name = flask.request.args.get("database")

    rows = [
        {
            "Dataset ID": row["dataset_id"],
            "Name": row["name"],
            "Description": row["description"],
            "Size": row["size"]
        }
        for row in query.fetch_datasets(database_name=database_name, get_sizes=True, undefined_means_empty=True)
    ]
    if len(rows) == 0:
        return {
            "response":f"No datasets found for database {database_name}"
        }
    else:
        return rows


@bp.route("/api/query")
def run_query():
    """Builds and executes a GET query.

    Returns:
        A serialized Dataset proto containing the matched reactions.
    """
    database_name = flask.request.args.get("database")

    commands, limit = build_query()
    try:
        if len(commands) == 0:
            raise ValueError("no query defined")
        return flask.jsonify(query.run_query(commands, limit=limit, database_name=database_name, prep_json=True))
    except Exception as error:
        return flask.abort(handlers.make_error_response(error, 400))


def build_query() -> Tuple[List[query.ReactionQueryBase], Optional[int]]:
    """Builds queries from GET parameters.

    Returns:
        queries: List of ReactionQueryBase subclass instances.
        limit: Maximum number of results to return, or None.
    """
    dataset_ids = flask.request.args.get("dataset_ids")
    reaction_ids = flask.request.args.get("reaction_ids")
    reaction_smarts = flask.request.args.get("reaction_smarts")
    min_conversion = flask.request.args.get("min_conversion")
    max_conversion = flask.request.args.get("max_conversion")
    min_yield = flask.request.args.get("min_yield")
    max_yield = flask.request.args.get("max_yield")
    dois = flask.request.args.get("dois")
    components = flask.request.args.getlist("component")
    use_stereochemistry = flask.request.args.get("use_stereochemistry")
    similarity = flask.request.args.get("similarity")
    limit = flask.request.args.get("limit")
    treatment_type = flask.request.args.get("treatment_type")
    liquid_assisted = flask.request.args.get("liquid_assisted")
    if limit is None:
        limit = MAX_RESULTS
    else:
        limit = min(int(limit), MAX_RESULTS)
    queries = []
    if dataset_ids is not None:
        queries.append(query.DatasetIdQuery(dataset_ids.split(",")))
    if reaction_ids is not None:
        queries.append(query.ReactionIdQuery(reaction_ids.split(",")))
    if reaction_smarts is not None:
        queries.append(query.ReactionSmartsQuery(reaction_smarts))
    if min_conversion is not None and max_conversion is not None:
        queries.append(query.ReactionConversionQuery(min_conversion, max_conversion))
    if min_yield is not None and max_yield is not None:
        queries.append(query.ReactionYieldQuery(min_yield, max_yield))
    if dois is not None:
        queries.append(query.DoiQuery(dois.split(",")))
    if treatment_type is not None:
        queries.append(
            query.TreatmentQuery(treatment_type.split(","), liquid_assisted)
        )
    if components:
        predicates = []
        for component in components:
            pattern, target_name, mode_name = component.split(";")
            target = query.ReactionComponentPredicate.Target.from_name(target_name)
            mode = query.ReactionComponentPredicate.MatchMode.from_name(mode_name)
            predicates.append(query.ReactionComponentPredicate(pattern, target, mode))
        kwargs = {}
        if use_stereochemistry is not None:
            kwargs["do_chiral_sss"] = use_stereochemistry
        if similarity is not None:
            kwargs["tanimoto_threshold"] = float(similarity)
        queries.append(query.ReactionComponentQuery(predicates, **kwargs))
    return queries, limit


@bp.route("api/ketcher/molfile", methods=["POST"])
def get_molfile():
    """Returns a molblock for the given SMILES."""
    smiles = flask.request.get_data()
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"could not parse SMILES: {smiles}")
        return flask.jsonify(Chem.MolToMolBlock(mol))
    except Exception as error:
        return flask.abort(handlers.make_error_response(error, 400))

SEARCH_RESULTS_FILE_NAME = "cmccdb_search_results"
@bp.route("/api/download_results", methods=["POST"])
def download_results():
    """Downloads search results as a Dataset proto."""
    database_name = flask.request.args.get("database")
    file_name = flask.request.args.get("filename", SEARCH_RESULTS_FILE_NAME)

    reaction_ids = [row["Reaction ID"] for row in flask.request.get_json()]
    command = query.ReactionIdQuery(reaction_ids[:MAX_RESULTS])
    try:
        results = query.QueryHandler(database_name).run_query(command)
    except query.QueryException as error:
        return flask.abort(handlers.make_error_response(error, 400))
    return flask.send_file(
        query.serialize_query_results(file_name, results),
        as_attachment=True,
        download_name=file_name+".pb.gz",
    )