"""Replay validation and receipt safety; database integration is validated separately."""
import json
import os
import shutil
from pathlib import Path

import pytest
from cmccdb_interface.database import batch_resubmit


@pytest.fixture
def incoming(tmp_path):
    default=Path(__file__).resolve().parents[2]/'cmccdb-data/incomplete/base_template.xlsx'
    sample=Path(os.getenv('CMCCDB_BATCH_TEST_XLSX',str(default)))
    if not sample.is_file():pytest.skip('Requires the cmccdb-data base_template.xlsx fixture')
    folder=tmp_path/'incoming';folder.mkdir()
    shutil.copy2(sample,folder/'base.xlsx')
    return folder,tmp_path/'report.json'


def prepare(folder,report):
    return batch_resubmit.prepare(folder,report,'Migration Operator','migration@example.invalid','preview')


def test_dev_target_refused_before_creating_report(tmp_path):
    report=tmp_path/'private/report.json'
    with pytest.raises(ValueError,match='main and preview'):
        batch_resubmit.prepare(tmp_path,report,'Operator','test@example.invalid','dev')
    assert not report.parent.exists()


def test_active_dev_backend_refused(monkeypatch,tmp_path):
    monkeypatch.setenv('CMCCDB_DEV_BACKEND','true')
    with pytest.raises(ValueError,match='never permitted on dev'):
        batch_resubmit.prepare(tmp_path,tmp_path/'report.json','Operator','test@example.invalid','main')


def test_concurrent_report_owner_is_refused(tmp_path):
    report=tmp_path/'report.json'
    with batch_resubmit.report_lock(report):
        with pytest.raises(ValueError,match='Another process'):
            prepare(tmp_path,report)


def test_nested_xlsx_and_excel_lock_files(incoming):
    folder,report=incoming
    nested=folder/'paper';nested.mkdir()
    (folder/'base.xlsx').rename(nested/'base.XLSX')
    (nested/'~$base.XLSX').write_bytes(b'Excel lock')
    result=prepare(folder,report)
    assert result['ok'] and list(result['files'])==['paper/base.XLSX']


def test_auxiliary_escape_is_reported(incoming):
    folder,report=incoming
    (folder/'batch.json').write_text(json.dumps({'files':{'base.xlsx':{'auxiliary':{'file.csv':'../outside.csv'}}}}))
    result=prepare(folder,report)
    assert not result['ok'] and 'escapes' in result['files']['base.xlsx']['error']


def test_auxiliary_bytes_are_compiled_into_dataset(incoming):
    folder,report=incoming
    sidecar=folder/'base.files';sidecar.mkdir()
    (sidecar/'spectrum.csv').write_bytes(b'1,2\n')
    result=prepare(folder,report)
    from cmccdb_schema.proto import dataset_pb2
    artifact=report.parent/(report.stem+'.protos')/result['files']['base.xlsx']['artifact']
    dataset=dataset_pb2.Dataset.FromString(artifact.read_bytes())
    assert dataset.reactions[0].provenance.reaction_metadata['attachment:spectrum.csv'].bytes_value==b'1,2\n'


def test_committed_input_cannot_be_removed(incoming):
    folder,report=incoming
    result=prepare(folder,report)
    result['committed']={'base.xlsx':result['files']['base.xlsx']['fingerprint']}
    batch_resubmit.write_json(report,result)
    (folder/'base.xlsx').rename(folder/'another.xlsx')
    with pytest.raises(ValueError,match='committed input was removed'):prepare(folder,report)


def test_duplicate_content_ids_are_flagged(incoming):
    folder,report=incoming
    shutil.copy2(folder/'base.xlsx',folder/'duplicate.xlsx')
    result=prepare(folder,report)
    assert not result['ok'] and 'Duplicate dataset ID' in result['files']['duplicate.xlsx']['error']


def test_manifest_preserves_legacy_dataset_id(incoming):
    folder,report=incoming
    identity='cmcc_dataset-'+'b'*32
    (folder/'batch.json').write_text(json.dumps({'files':{'base.xlsx':{'dataset_id':identity}}}))
    result=prepare(folder,report)
    assert result['ok'] and result['files']['base.xlsx']['dataset_id']==identity


def test_report_binding_cannot_change_database(incoming):
    folder,report=incoming
    result=prepare(folder,report);result['binding']={'cluster':'123','database':'cmcc'}
    batch_resubmit.write_json(report,result)
    with pytest.raises(ValueError,match='another database'):
        batch_resubmit.apply(folder,report,'Operator','test@example.invalid','preview','staging','123')


def test_input_symlinks_are_refused(incoming):
    folder,report=incoming
    (folder/'link.xlsx').symlink_to('base.xlsx')
    with pytest.raises(ValueError,match='symlinks'):prepare(folder,report)
