"""Search downloads preserve values in protobuf and native CSV formats."""
import csv
import gzip
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch

import flask
from google.protobuf import text_format
from cmccdb_schema.proto import dataset_pb2, reaction_pb2
from cmccdb_schema import dataset_constructor, spreadsheet
from cmccdb_interface.client import search
from cmccdb_interface.client import auxiliary
from cmccdb_interface.database import query
from cmccdb_interface.database import backups, datasets


class DownloadResultsTests(unittest.TestCase):
    def setUp(self):
        self.reaction = reaction_pb2.Reaction(reaction_id="cmcc-" + "a" * 32)
        self.reaction.notes.procedure_details = "Milling at 25 °C; μL quantities"
        self.reaction.observations.add().image.bytes_value = b"\x00\xffattachment"
        self.reaction.outcomes.add().analyses["NMR"].data["spectrum"].url = "https://example.invalid/raw.csv"
        self.results = [SimpleNamespace(reaction=self.reaction)]
        app = flask.Flask(__name__)
        app.register_blueprint(search.bp)
        self.client = app.test_client()
        patcher = patch.object(search.query, "QueryHandler")
        self.handler = patcher.start()
        self.addCleanup(patcher.stop)
        self.handler.return_value.run_query.return_value = self.results

    def download(self, query_string=""):
        response = self.client.post("/client/api/download_results" + query_string,
                                    json=[{"Reaction ID": self.reaction.reaction_id}])
        self.addCleanup(response.close)
        return response

    def test_default_binary_download_remains_compatible(self):
        response = self.download()
        self.assertEqual(response.status_code, 200)
        restored = dataset_pb2.Dataset.FromString(gzip.decompress(response.data))
        self.assertEqual(restored.name, "cmccdb_search_results")
        self.assertEqual(list(restored.reactions), [self.reaction])
        self.assertIn("cmccdb_search_results.pb.gz", response.headers["Content-Disposition"])

    def test_pbtxt_is_readable_utf8_and_preserves_all_fields(self):
        response = self.download("?format=pbtxt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/plain")
        self.assertIn("charset=utf-8", response.content_type.lower())
        self.assertIn("cmccdb_search_results.pbtxt", response.headers["Content-Disposition"])
        self.assertIn("25 °C", response.data.decode("utf-8"))
        restored = text_format.Parse(response.data.decode("utf-8"), dataset_pb2.Dataset())
        binary = dataset_pb2.Dataset.FromString(gzip.decompress(query.serialize_query_results(
            "cmccdb_search_results", self.results).getvalue()))
        expected = dataset_pb2.Dataset(name="cmccdb_search_results", reactions=[self.reaction])
        self.assertEqual(restored, binary)
        self.assertEqual(restored, expected)

    def test_download_uses_the_requested_database(self):
        self.assertEqual(self.download("?format=pbtxt&database=staging").status_code, 200)
        self.handler.assert_called_once_with("staging")

    def test_filename_matches_selected_format(self):
        response = self.download("?format=pbtxt&filename=selected_reactions")
        restored = text_format.Parse(response.data.decode(), dataset_pb2.Dataset())
        self.assertEqual(restored.name, "selected_reactions")
        self.assertIn("selected_reactions.pbtxt", response.headers["Content-Disposition"])

    def test_unsupported_formats_fail_before_querying(self):
        for file_format in ("xlsx", "json", "../pbtxt"):
            with self.subTest(file_format=file_format):
                self.assertEqual(self.download("?format=" + file_format).status_code, 400)
        self.handler.assert_not_called()

    def test_serializer_rejects_unsupported_format(self):
        with self.assertRaisesRegex(ValueError, "Unsupported download format"):
            query.serialize_query_results("results", self.results, file_format="xlsx")

    def test_csv_reimports_full_values_without_node_or_xlsx(self):
        with patch.object(spreadsheet.subprocess, "run", side_effect=AssertionError("No Node")):
            response = self.download("?format=csv&database=staging")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.mimetype, "application/zip")
        self.assertIn("cmccdb_search_results.zip", response.headers["Content-Disposition"])
        actual = spreadsheet.load_csv_bundle(response.data)
        self.assertEqual(actual.reactions[0], self.reaction)
        self.assertEqual(actual.name, "cmccdb_search_results")
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            text = archive.read("reactions.csv").decode()
            self.assertIn("25 °C", text)
            self.assertNotIn("bytes_value", text)
            self.assertFalse(any(row[0] == "DATASET ID" for row in csv.reader(io.StringIO(text))))
        self.handler.assert_called_once_with("staging")

    def test_csv_loss_is_explained_without_returning_a_partial_file(self):
        self.reaction.notes.procedure_details = " boundary text "
        response = self.download("?format=csv")
        self.assertEqual(response.status_code, 422)
        self.assertIn("Download pbtxt or pb.gz", response.get_json()["message"])
        self.assertNotIn("Content-Disposition", response.headers)

    def test_large_csv_attachment_is_not_rejected_by_the_old_reader_limit(self):
        attachment = bytes(range(256)) * 1500
        self.reaction.provenance.reaction_metadata["attachment:audit.gz"].bytes_value = attachment
        response = self.download("?format=csv")
        self.assertEqual(response.status_code, 200)
        actual = spreadsheet.load_csv_bundle(response.data)
        self.assertEqual(actual.reactions[0], self.reaction)

    def test_local_attachments_use_the_original_dataset_resolver(self):
        self.reaction.outcomes[0].analyses["NMR"].data["spectrum"].url = "raw.csv"
        self.results[0].dataset_id = "cmcc_dataset-" + "b" * 32
        with tempfile.TemporaryDirectory() as temp:
            attachment = Path(temp) / "raw.csv"; attachment.write_bytes(b"x,y\n1,2\n")
            with patch.object(auxiliary, "_attachment_file", return_value=attachment) as resolver:
                response = self.download("?format=csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resolver.call_args.args, (Path("raw.csv"), self.results[0].dataset_id))
        actual = spreadsheet.load_csv_bundle(response.data)
        self.assertEqual(actual.reactions[0].outcomes[0].analyses["NMR"].data["spectrum"].bytes_value, b"x,y\n1,2\n")

    def test_missing_local_attachment_withholds_zip_and_explains_which_file(self):
        self.reaction.outcomes[0].analyses["NMR"].data["spectrum"].url = "missing.csv"
        with patch.object(auxiliary, "_attachment_file", return_value=None), self.assertLogs(level="ERROR"):
            response = self.download("?format=csv")
        self.assertEqual(response.status_code, 422)
        self.assertIn("Missing or ambiguous local attachment: missing.csv", response.get_json()["message"])
        self.assertNotIn("Content-Disposition", response.headers)

    def test_csv_reader_errors_have_json_details_and_a_logged_reference(self):
        with patch.object(query, "serialize_query_results", side_effect=csv.Error("field larger than field limit (131072)")):
            with self.assertLogs(level="ERROR") as logs:
                response = self.download("?format=csv&database=staging")
        self.assertEqual(response.status_code, 422)
        error = response.get_json()
        self.assertIn("field larger than field limit (131072)", error["message"])
        self.assertEqual(error["error_type"], "Error")
        self.assertEqual(error["format"], "csv")
        self.assertEqual(error["request_id"], response.headers["X-Request-ID"])
        self.assertIn(error["request_id"], "\n".join(logs.output))
        self.assertIn("database='staging'", "\n".join(logs.output))
        self.assertNotIn("traceback", error)

    def test_unexpected_server_errors_are_json_and_do_not_expose_private_paths(self):
        with patch.object(query, "serialize_query_results", side_effect=RuntimeError("private /var/tmp/operator/path")):
            with self.assertLogs(level="ERROR") as logs:
                response = self.download("?format=csv")
        self.assertEqual(response.status_code, 500)
        error = response.get_json()
        self.assertEqual(error["error_type"], "RuntimeError")
        self.assertIn("RuntimeError", error["message"])
        self.assertNotIn("/var/tmp", error["message"])
        self.assertIn("private /var/tmp/operator/path", "\n".join(logs.output))
        self.assertIn(error["request_id"], "\n".join(logs.output))

    def test_query_errors_keep_their_status_and_gain_a_reference(self):
        self.handler.return_value.run_query.side_effect = query.QueryException("Selected reactions unavailable")
        with self.assertLogs(level="ERROR"):
            response = self.download("?format=csv")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Selected reactions unavailable", response.get_json()["message"])
        self.assertEqual(response.get_json()["request_id"], response.headers["X-Request-ID"])

    def test_native_csv_upload_retains_declared_dataset_and_reaction_ids(self):
        self.reaction.ClearField("observations")
        self.reaction.outcomes[0].analyses["NMR"].type = reaction_pb2.Analysis.NMR_1H
        compound = self.reaction.inputs["reactants"].components.add()
        compound.identifiers.add(type=reaction_pb2.CompoundIdentifier.NAME, value="Substrate")
        compound.reaction_role = reaction_pb2.ReactionRole.REACTANT
        compound.amount.moles.value = 1
        compound.amount.moles.units = reaction_pb2.Moles.MILLIMOLE
        source = dataset_pb2.Dataset(dataset_id="cmcc_dataset-" + "b" * 32,
            name="Identity-bearing CSV", reactions=[self.reaction])
        payload = spreadsheet.serialize_csv(source)
        with tempfile.TemporaryDirectory() as temp, patch.object(backups, "TEMPORARY_DIR", temp):
            actual = datasets.prep_and_create_pb_dataset("different filename.csv", payload,
                perform_backup=False, uploader_name="Export fixture", uploader_email="fixture@example.invalid")
        self.assertEqual(actual.dataset_id, source.dataset_id)
        self.assertEqual(actual.reactions[0].reaction_id, self.reaction.reaction_id)
        self.assertEqual(actual.name, source.name)

    def test_empty_search_has_a_valid_text_dataset(self):
        self.handler.return_value.run_query.return_value = []
        response = self.download("?format=pbtxt")
        self.assertEqual(response.status_code, 200)
        restored = text_format.Parse(response.data.decode(), dataset_pb2.Dataset())
        self.assertEqual(restored.name, "cmccdb_search_results")
        self.assertEqual(len(restored.reactions), 0)

    def test_existing_download_limit_is_preserved(self):
        response = self.client.post("/client/api/download_results?format=pbtxt", json=[
            {"Reaction ID": "cmcc-" + format(index, "032x")}
            for index in range(search.MAX_RESULTS + 1)])
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        command = self.handler.return_value.run_query.call_args.args[0]
        self.assertEqual(len(command._reaction_ids), search.MAX_RESULTS)


if __name__ == "__main__":
    unittest.main()
