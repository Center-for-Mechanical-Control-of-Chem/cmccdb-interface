"""Real multipart/constructor/batch preparation; database and GitHub are never written."""
import gzip
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import flask
from google.protobuf import text_format
from werkzeug.datastructures import FileStorage, MultiDict
from cmccdb_schema.proto import dataset_pb2
from cmccdb_interface.client import edit
from cmccdb_interface.database import auxiliary, backups, batch_resubmit, datasets, upload_limits


class AuditAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='audit-attachment-tests-',dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.dataset=dataset_pb2.Dataset(dataset_id='cmcc_dataset-'+'a'*32,name='Attachment format fixture')
        reaction=self.dataset.reactions.add(reaction_id='cmcc-'+'b'*32)
        reaction.provenance.record_created.time.value='2026-10-08T00:00:00+0000'
        reaction.provenance.record_created.person.name='Attachment format fixture'
        reaction.provenance.record_created.person.email='fixture@example.invalid'
        component=reaction.inputs['fixture'].components.add(reaction_role='REACTANT')
        component.identifiers.add(type='NAME',value='Fixture input')
        component.amount.mass.value=1;component.amount.mass.units=1
        product=reaction.outcomes.add().products.add(reaction_role='PRODUCT')
        product.identifiers.add(type='NAME',value='Fixture output')
        self.dataset.reactions[0].provenance.reaction_metadata['logical audit'].url='extraction-audit.json.gz'
        self.attachments={f'audit.v2.part-{i:05d}.json.gz':gzip.compress(
            json.dumps({'fixture_part':i,'source_text':'Preserve exact fixture attachment bytes'}).encode(),mtime=0)
            for i in range(12)}
        for key in ['TEMPORARY_DIR','BACKUP_DIR']:
            patcher=patch.object(backups,key,str(self.root/key));patcher.start();self.addCleanup(patcher.stop)
        auth=patch.object(edit.authentication,'gh_get_cache_user_info',return_value={'username':'fixture','member':True})
        auth.start();self.addCleanup(auth.stop)
        insert=patch.object(edit.manage,'add_dataset');self.insert=insert.start();self.addCleanup(insert.stop)
        git=patch.object(backups,'git_backup');self.git=git.start();self.addCleanup(git.stop)
        environment=patch.dict(os.environ,{'CMCCDB_DISABLE_GITHUB_BACKUPS':'true','CMCCDB_DEV_BACKEND':'false',
                                          'CMCCDB_DEV_FRONTEND':'false','CMCCDB_DEV_FRONTEND_PROXY':'false'})
        environment.start();self.addCleanup(environment.stop)
        self.app=flask.Flask(__name__);self.app.config['MAX_CONTENT_LENGTH']=upload_limits.MAX_REQUEST_BYTES
        self.app.register_blueprint(edit.bp);self.client=self.app.test_client()

    def assert_preserved(self,dataset,attachments):
        restored=dataset_pb2.Dataset.FromString(dataset.SerializeToString(deterministic=True))
        self.assertEqual(restored,dataset)
        metadata=restored.reactions[0].provenance.reaction_metadata
        self.assertEqual({key.removeprefix('attachment:') for key in metadata if key.startswith('attachment:')},set(attachments))
        for name,body in attachments.items():
            self.assertEqual(metadata['attachment:'+name].bytes_value,body)
            self.assertEqual(hashlib.sha256(metadata['attachment:'+name].bytes_value).digest(),hashlib.sha256(body).digest())

    def post(self,attachments):
        parts=[('uploadFile',(io.BytesIO(text_format.MessageToBytes(self.dataset)),'format-fixture.pbtxt'))]
        parts += [(f'auxFile{i}',(io.BytesIO(body),name)) for i,(name,body) in enumerate(attachments.items())]
        return self.client.post('/client/api/upload?database=staging&perform_backup=false',data=MultiDict(parts))

    def test_http_multipart_retains_all_twelve_complete_attachments(self):
        response=self.post(self.attachments)
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.json['dataset_id'],self.dataset.dataset_id)
        self.insert.assert_called_once();submitted=self.insert.call_args.args[0]
        self.assert_preserved(submitted,self.attachments)
        self.assertEqual(submitted.reactions[0].provenance.reaction_metadata['logical audit'].url,'extraction-audit.json.gz')
        # Inspect the actual restorable protobuf preparation output, not just a mock argument.
        compiled=list((self.root/'TEMPORARY_DIR').rglob('*.pbtxt'))
        self.assertTrue(compiled)
        restored=dataset_pb2.Dataset();text_format.Parse(compiled[-1].read_text(),restored)
        self.assertEqual(restored,submitted);self.git.assert_not_called()

    def test_http_and_direct_boundary_accept_64_and_reject_65_atomically(self):
        attachments={f'part-{i}.json.gz':b'fixture bytes' for i in range(64)}
        self.assertEqual(auxiliary.MAX_AUXILIARY_FILES,datasets.MAX_AUXILIARY_FILES)
        self.assertEqual(datasets.MAX_AUXILIARY_FILES,64)
        response=self.post(attachments)
        self.assertEqual(response.status_code,200,response.data)
        self.assert_preserved(self.insert.call_args.args[0],attachments)
        self.insert.reset_mock();attachments['part-64.json.gz']=b'last fixture'
        response=self.post(attachments)
        self.assertEqual(response.status_code,406)
        self.assertIn('64',response.json['message']);self.insert.assert_not_called()
        original=self.dataset.SerializeToString()
        with self.assertRaisesRegex(ValueError,'64'):datasets.attach_auxiliary_files(self.dataset,attachments)
        self.assertEqual(self.dataset.SerializeToString(),original)

    def test_count_limit_rejects_collection_before_reading_streams(self):
        storages=[]
        for i in range(65):
            storage=FileStorage(stream=io.BytesIO(b'fixture'),filename=f'part-{i}.json.gz')
            storages.append(storage)
        with self.assertRaisesRegex(ValueError,'64'):auxiliary.collect_uploads(storages)
        self.assertTrue(all(storage.stream.tell()==0 for storage in storages))

    def test_five_mib_and_31_mib_bounds_still_apply(self):
        original=self.dataset.SerializeToString()
        with self.assertRaisesRegex(ValueError,'5 MB'):
            datasets.attach_auxiliary_files(self.dataset,{'large.json.gz':b'x'*(upload_limits.MAX_FILE_BYTES+1)})
        block=b'x'*upload_limits.MAX_FILE_BYTES
        with self.assertRaisesRegex(ValueError,'31 MiB'):
            datasets.attach_auxiliary_files(self.dataset,{f'part-{i}.json.gz':block for i in range(7)})
        self.assertEqual(self.dataset.SerializeToString(),original)
        with self.assertRaisesRegex(ValueError,'31 MiB'):
            datasets.prep_and_create_pb_dataset('fixture.pbtxt',block,perform_backup=False,
                auxiliary_files={f'part-{i}.json.gz':block for i in range(6)})
        self.assertFalse((self.root/'TEMPORARY_DIR').exists())
        self.assertEqual(self.app.config['MAX_CONTENT_LENGTH'],31*1024*1024)
        storage=FileStorage(stream=io.BytesIO(block),filename='boundary.gz')
        self.assertEqual(len(auxiliary.read_upload(storage)),upload_limits.MAX_FILE_BYTES)

    def test_colliding_existing_attachment_does_not_partially_mutate_other_fields(self):
        metadata=self.dataset.reactions[0].provenance.reaction_metadata
        metadata['reference'].url='part-first.json.gz'
        metadata['attachment:part-last.json.gz'].bytes_value=b'previous immutable attachment'
        original=self.dataset.SerializeToString()
        with self.assertRaisesRegex(ValueError,'already exists'):
            datasets.attach_auxiliary_files(self.dataset,{'part-first.json.gz':b'first','part-last.json.gz':b'last'})
        self.assertEqual(self.dataset.SerializeToString(),original)

    def test_http_bad_names_and_duplicate_files_are_rejected(self):
        response=self.post({'../escape.json.gz':b'fixture'})
        self.assertEqual(response.status_code,406)
        parts=[('uploadFile',(io.BytesIO(text_format.MessageToBytes(self.dataset)),'fixture.pbtxt')),
               ('auxFile0',(io.BytesIO(b'a'),'same.json.gz')),('auxFile1',(io.BytesIO(b'b'),'same.json.gz'))]
        response=self.client.post('/client/api/upload?database=staging',data=MultiDict(parts))
        self.assertEqual(response.status_code,406);self.assertIn('Duplicate',response.json['message'])
        self.insert.assert_not_called()

    def batch(self,attachments):
        data_root=Path(os.environ.get('CMCCDB_DATA_ROOT',Path(__file__).resolve().parents[2]/'cmccdb-data'))
        source=data_root/'incomplete/base_template.xlsx'
        if not source.is_file():self.skipTest('Requires the real CMCCDB base_template.xlsx format fixture')
        incoming=self.root/'incoming';incoming.mkdir();shutil.copy2(source,incoming/'format.xlsx')
        sidecar=incoming/'format.files';sidecar.mkdir()
        for name,body in attachments.items():(sidecar/name).write_bytes(body)
        report=self.root/'report.json'
        result=batch_resubmit.prepare(incoming,report,'Attachment format fixture','fixture@example.invalid','preview')
        return result,report

    def test_actual_xlsx_batch_compilation_retains_all_twelve_attachments(self):
        result,report=self.batch(self.attachments)
        self.assertTrue(result['ok'],result['files'])
        entry=result['files']['format.xlsx'];self.assertEqual(entry['status'],'validated')
        artifact=report.parent/(report.stem+'.protos')/entry['artifact']
        dataset=dataset_pb2.Dataset.FromString(artifact.read_bytes())
        self.assert_preserved(dataset,self.attachments)
        self.assertEqual(entry['fingerprint']['auxiliary_sha256'],
            {name:hashlib.sha256(body).hexdigest() for name,body in self.attachments.items()})
        self.insert.assert_not_called();self.git.assert_not_called()

    def test_actual_batch_over_count_fails_validation_without_database_or_git(self):
        result,_=self.batch({f'part-{i}.json.gz':b'fixture' for i in range(65)})
        self.assertFalse(result['ok']);self.assertEqual(result['files']['format.xlsx']['status'],'invalid')
        self.assertIn('64',result['files']['format.xlsx']['error'])
        self.insert.assert_not_called();self.git.assert_not_called()


if __name__=='__main__':unittest.main()
