"""Preserve embedded metadata through actual upload and batch constructors."""
import json
import os
import shutil
from pathlib import Path
import pytest
from cmccdb_interface.database import backups, batch_resubmit, datasets
from cmccdb_schema.dataset_constructor import DatasetConstructor
from cmccdb_schema.proto import dataset_pb2


@pytest.fixture
def workbook():
    path = Path(os.environ.get("CMCCDB_METADATA_TEST_XLSX", ""))
    if not path.is_file():
        pytest.skip("Set CMCCDB_METADATA_TEST_XLSX to a valid metadata-bearing XLSX")
    expected = DatasetConstructor.enumerate_spreadsheet(path)
    assert expected.name and expected.description
    return path, expected


def test_upload_filename_is_only_a_fallback(workbook, tmp_path, monkeypatch):
    path, expected = workbook
    monkeypatch.setattr(backups, "TEMPORARY_DIR", str(tmp_path))
    actual = datasets.prep_and_create_pb_dataset(
        "A different upload filename.xlsx", path.read_bytes(), perform_backup=False,
        uploader_name="Metadata fixture", uploader_email="fixture@example.invalid")
    assert actual.name == expected.name and actual.description == expected.description


def test_batch_fallback_and_explicit_override(workbook, tmp_path):
    path, expected = workbook
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    shutil.copyfile(path, incoming / "Different filename.xlsx")
    def prepare(report):
        result = batch_resubmit.prepare(incoming, report, "Metadata fixture",
                                       "fixture@example.invalid", "preview")
        assert result["ok"]
        entry = result["files"]["Different filename.xlsx"]
        artifact = report.parent / (report.stem + ".protos") / entry["artifact"]
        return dataset_pb2.Dataset.FromString(artifact.read_bytes())
    actual = prepare(tmp_path / "fallback.json")
    assert actual.name == expected.name and actual.description == expected.description
    (incoming / "batch.json").write_text(json.dumps({"files": {
        "Different filename.xlsx": {"dataset_name": "Explicit operator title"}}}))
    overridden = prepare(tmp_path / "override.json")
    assert overridden.name == "Explicit operator title"
    assert overridden.description == expected.description
