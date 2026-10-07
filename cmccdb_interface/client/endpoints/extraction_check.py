"""Read-only development checks. No database writes or dependency installation."""
import hashlib
import importlib.metadata
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import flask
from google.protobuf.json_format import ParseDict, ParseError
from cmccdb_schema import dataset_constructor
from cmccdb_schema.proto import dataset_pb2, reaction_pb2

ROOT = Path(__file__).parent / 'test_inputs' / 'extraction-check-20261007'


def info():
    packages = {}
    for name in ['mcp', 'pydantic', 'protobuf', 'rdkit', 'pandas', 'openpyxl']:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    commands = {n: shutil.which(n) for n in ['node', 'pdftotext', 'pdftoppm', 'pg_dump', 'pg_restore']}
    artifact = False
    if commands['node']:
        proc = subprocess.run([commands['node'], '-e', "require.resolve('@oai/artifact-tool')"],
                              capture_output=True, timeout=10)
        artifact = proc.returncode == 0
    fields = reaction_pb2.MechanochemistryConditions.DESCRIPTOR.fields_by_name
    return flask.jsonify(python=platform.python_version(), machine=platform.machine(),
        packages=packages, commands=commands, artifact_writer_available=artifact,
        constructor_source=dataset_constructor.__file__,
        constructor_sha256=hashlib.sha256(Path(dataset_constructor.__file__).read_bytes()).hexdigest(),
        feed_rate_present='feed_rate' in fields,
        rpm_present='RPM' in reaction_pb2.Frequency.DESCRIPTOR.enum_types_by_name['FrequencyUnit'].values_by_name,
        source_file=str(Path(__file__).resolve()))


def check():
    """Parse only fixed staged inputs, using either baseline or isolated patched converter."""
    mode = flask.request.args.get('converter', 'baseline')
    if mode not in {'baseline', 'patched'}:
        flask.abort(400)
    module = dataset_constructor
    if mode == 'patched':
        path = ROOT / 'dataset_constructor.py'
        expected = json.loads((ROOT / 'checksums.json').read_text())['dataset_constructor.py']
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Patched converter checksum mismatch')
        spec = importlib.util.spec_from_file_location('cmccdb_schema._extraction_check_converter', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    rows = [
        ['REACTION'], ['', 'notes'], ['', 'procedure_details'], ['', 'NO'],
        ['VARIANTS'], ['', 'inputs'], ['', 'key', 'components'],
        ['', '', 'identifiers'], ['', '', 'type', 'value'],
        ['DATA'], ['', '123', 'NAME', '00123']]
    width = max(map(len, rows))
    parser, data = module.DatasetConstructor.from_iter([r + ['']*(width-len(r)) for r in rows])[0]
    values = module.DatasetConstructor.sanitize_csv_data(data[0], len(parser.template.template_paths),
        **({'template':parser.template} if mode == 'patched' else {}))
    string_result = {'passed': False}
    try:
        applied = parser.template.apply(values)
        reaction = ParseDict(module.ProtoTemplater.prep_proto(applied,
            descriptor=reaction_pb2.Reaction.DESCRIPTOR), reaction_pb2.Reaction())
        string_result = dict(passed=reaction.notes.procedure_details == 'NO' and
            reaction.inputs['123'].components[0].identifiers[0].value == '00123',
            notes=reaction.notes.procedure_details,
            identifier=reaction.inputs['123'].components[0].identifiers[0].value)
    except (ValueError, TypeError, ParseError) as error:
        string_result['error'] = str(error)[:1000]
    expected = ParseDict(json.loads((ROOT / 'dataset.json').read_text()), dataset_pb2.Dataset())
    reference_result = {'passed':False}
    try:
        actual = module.DatasetConstructor.enumerate_spreadsheet(ROOT / 'extraction.xlsx',
            name=expected.name, id=expected.dataset_id.removeprefix('cmcc_dataset-'))
        expected_rxns = {r.reaction_id:r for r in expected.reactions}
        actual_rxns = {r.reaction_id:r for r in actual.reactions}
        reference_result = dict(passed=expected_rxns == actual_rxns, reactions=len(actual.reactions))
    except (ValueError, TypeError, ParseError) as error:
        reference_result['error'] = str(error)[:1000]
    return flask.jsonify(converter=mode, string_cells=string_result,
        reference_xlsx=reference_result,
        database_writes=False, patched_module_isolated=True)
