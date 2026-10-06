"""Multipart upload tests with real protobuf parsing and an isolated filesystem."""
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

import flask
from google.protobuf import text_format
from werkzeug.datastructures import MultiDict, FileStorage
from cmccdb_schema.proto import dataset_pb2
from cmccdb_interface.client import edit
from cmccdb_interface.database import auxiliary, datasets


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.backup = self.root / "backup"
        self.temporary = self.root / "temporary"
        for key, value in [("BACKUP_DIR", str(self.backup)), ("TEMPORARY_DIR", str(self.temporary))]:
            patcher = patch.object(edit.backups, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, value in [("authentication.gh_get_cache_user_info", {"username": "tester", "member": True}),
                              ("manage.add_dataset", None), ("backups.git_backup", None)]:
            patcher = patch("cmccdb_interface.client.edit." + target, return_value=value)
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            if target.startswith("authentication"):
                self.auth = mock
            elif target.startswith("manage"):
                self.insert = mock
            else:
                self.git_backup = mock
        self.app = flask.Flask(__name__)
        self.app.register_blueprint(edit.bp)
        self.client = self.app.test_client()
        self.dataset = dataset_pb2.Dataset(dataset_id="cmcc_dataset-abc123", name="Upload fixture")
        self.reaction = self.dataset.reactions.add(reaction_id="cmcc-reaction-upload")
        self.reaction.outcomes.add().analyses["spectrum"].data["image"].url = "abc123_plot.png"

    def post(self, attachments=(), dataset=None, serialized=False, query=None):
        dataset = dataset if dataset is not None else self.dataset
        body = dataset.SerializeToString() if serialized else text_format.MessageToString(dataset).encode()
        parts = [("uploadFile", (io.BytesIO(body), "fixture.pb" if serialized else "fixture.pbtxt"))]
        parts += [(key, (io.BytesIO(body), name)) for key, name, body in attachments]
        return self.client.post("/client/api/upload", data=MultiDict(parts),
                                query_string=query or {"database": "staging", "perform_backup": "false"})

    def test_spreadsheet_style_link_is_rewritten_before_database_insert(self):
        response = self.post([("auxFile0", "plot.png", b"PNG contents")])
        self.assertEqual(response.status_code, 200)
        submitted = self.insert.call_args.args[0]
        url = submitted.reactions[0].outcomes[0].analyses["spectrum"].data["image"].url
        self.assertEqual(url, "aux/cmcc_dataset-abc123/plot.png")
        self.assertEqual((self.temporary / url).read_bytes(), b"PNG contents")
        self.assertEqual(self.insert.call_args.kwargs, {"database_name": "staging"})
        restored = dataset_pb2.Dataset()
        text_format.Parse((self.temporary / "aux/cmcc_dataset-abc123/.dataset.pbtxt").read_text(), restored)
        self.assertEqual(restored, submitted)
        self.git_backup.assert_not_called()

    def test_binary_protobuf_upload_and_no_attachments(self):
        response = self.post(serialized=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.insert.call_args.args[0], self.dataset)
        self.assertFalse((self.temporary / "aux").exists())

    def test_all_nested_data_fields_and_encoded_filenames(self):
        self.reaction.inputs["input"].components.add().features["plot"].url = "plot.png"
        self.reaction.outcomes[0].products.add().features["plot"].url = "images/plot.png"
        self.reaction.setup.automation_code["script"].url = "abc123_script.py"
        self.reaction.observations.add().image.url = "abc123_plot.png"
        self.reaction.provenance.reaction_metadata["raw"].url = "raw%20%23%3F.csv"
        self.reaction.provenance.reaction_metadata["external"].url = "https://example.org/plot.png"
        response = self.post([("auxFile0", "plot.png", b"png"), ("auxFile1", "script.py", b"code"),
                              ("auxFile2", "raw #?.csv", b"csv")])
        self.assertEqual(response.status_code, 200)
        submitted = self.insert.call_args.args[0]
        urls = [data.url for data in auxiliary._data_messages(submitted) if data.WhichOneof("kind") == "url"]
        self.assertEqual(urls.count("aux/cmcc_dataset-abc123/plot.png"), 4)
        self.assertIn("aux/cmcc_dataset-abc123/" + quote("raw #?.csv", safe=""), urls)
        self.assertIn("https://example.org/plot.png", urls)

    def test_backup_flag_selects_persistent_or_temporary_storage(self):
        response = self.post([("auxFile0", "plot.png", b"png")], query={"perform_backup": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue((self.backup / "aux/cmcc_dataset-abc123/plot.png").is_file())
        self.git_backup.assert_called_once()
        self.assertFalse(self.temporary.exists())

    def test_no_files_remain_after_failed_database_insert(self):
        self.insert.side_effect = RuntimeError("Database unavailable")
        response = self.post([("auxFile0", "plot.png", b"png")])
        self.assertEqual(response.status_code, 406)
        self.assertFalse((self.temporary / "aux/cmcc_dataset-abc123").exists())

    def test_existing_submission_is_never_overwritten(self):
        self.assertEqual(self.post([("auxFile0", "plot.png", b"first")]).status_code, 200)
        self.assertEqual(self.post([("auxFile0", "plot.png", b"second")]).status_code, 406)
        self.assertEqual((self.temporary / "aux/cmcc_dataset-abc123/plot.png").read_bytes(), b"first")
        self.insert.assert_called_once()

    def test_unreferenced_attachment_is_rejected(self):
        response = self.post([("auxFile0", "unlinked.png", b"png")])
        self.assertEqual(response.status_code, 406)
        self.assertIn("url(filename)", response.json["message"])
        self.insert.assert_not_called()
        self.assertFalse((self.temporary / "aux").exists())

    def test_authentication_and_primary_membership_are_preserved(self):
        self.auth.return_value = None
        self.assertEqual(self.post().status_code, 406)
        self.auth.return_value = {"username": "tester", "member": False}
        self.assertEqual(self.post(query={"database": "cmcc"}).status_code, 406)
        self.insert.assert_not_called()
        self.assertEqual(self.post(query={"database": "staging"}).status_code, 200)

    def test_count_and_size_limits_are_enforced_before_processing(self):
        response = self.post([("auxFiles", f"file{i}.png", b"png") for i in range(6)])
        self.assertEqual(response.status_code, 406)
        self.assertIn("at most 5", response.json["message"])
        response = self.post([("auxFile0", "plot.png", b"p" * (auxiliary.MAX_FILE_BYTES + 1))])
        self.assertEqual(response.status_code, 406)
        self.assertIn("5 MB", response.json["message"])
        response = self.client.post("/client/api/upload", data={
            "uploadFile": (io.BytesIO(b"p" * (auxiliary.MAX_FILE_BYTES + 1)), "dataset.pbtxt")})
        self.assertEqual(response.status_code, 406)
        self.insert.assert_not_called()
        self.assertFalse(self.temporary.exists())

    def test_exact_file_size_limit_is_allowed(self):
        storage = FileStorage(stream=io.BytesIO(b"p" * auxiliary.MAX_FILE_BYTES), filename="plot.png")
        self.assertEqual(len(auxiliary.read_upload(storage)), auxiliary.MAX_FILE_BYTES)

    def test_bad_filenames_and_duplicates_are_rejected(self):
        for name in ["../plot.png", "folder/plot.png", "folder\\plot.png", ".hidden", "C:plot.png"]:
            with self.subTest(name=name):
                self.assertEqual(self.post([("auxFile0", name, b"png")]).status_code, 406)
        response = self.post([("auxFile0", "plot.png", b"one"), ("auxFile1", "plot.png", b"two")])
        self.assertEqual(response.status_code, 406)
        self.assertIn("Duplicate", response.json["message"])
        self.insert.assert_not_called()

    def test_missing_dataset_and_unsupported_dataset_format(self):
        self.assertEqual(self.client.post("/client/api/upload").status_code, 406)
        self.assertEqual(self.client.post("/client/api/upload", data={
            "uploadFile": (io.BytesIO(b"not a dataset"), "data.exe")}).status_code, 406)
        self.insert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
