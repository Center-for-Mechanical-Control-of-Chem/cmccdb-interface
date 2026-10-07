"""Read-only chemistry checks for the opt-in /api/dev module dispatcher."""

import sys
from pathlib import Path

import flask
from rdkit import Chem, rdBase
from rdkit.Chem import rdMolDescriptors

from cmccdb_schema.proto import reaction_pb2

SOURCE_REVISION = "dev-probe-2"


def status():
    """Identify the source currently serving requests and its chemistry runtime."""
    return flask.jsonify(
        source_revision=SOURCE_REVISION,
        source_file=str(Path(__file__).resolve()),
        python_version=sys.version.split()[0],
        rdkit_version=rdBase.rdkitVersion,
        data_kinds=[
            field.name
            for field in reaction_pb2.Data.DESCRIPTOR.oneofs_by_name["kind"].fields
        ],
    )


def molecule():
    """Inspect SMILES and exercise both SVG and Cairo/PNG rendering."""
    if flask.request.method == "POST":
        payload = flask.request.get_json(silent=True)
        if not isinstance(payload, dict):
            return flask.jsonify(error="Send a JSON object containing smiles."), 400
        smiles = payload.get("smiles")
    else:
        smiles = flask.request.args.get("smiles", "CCO")

    if not isinstance(smiles, str) or not smiles.strip() or len(smiles) > 512:
        return flask.jsonify(error="smiles must be a nonempty string of at most 512 characters."), 400
    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None or not mol.GetNumAtoms():
        return flask.jsonify(error="Invalid SMILES."), 400

    # Import here so status can still help diagnose a missing drawing dependency.
    from cmccdb_interface.visualization import drawing

    return flask.jsonify(
        source_revision=SOURCE_REVISION,
        canonical_smiles=Chem.MolToSmiles(mol),
        formula=rdMolDescriptors.CalcMolFormula(mol),
        atom_count=mol.GetNumAtoms(),
        svg=drawing.mol_to_svg(Chem.Mol(mol)),
        png_base64=drawing.mol_to_png(Chem.Mol(mol), max_size=300),
    )
