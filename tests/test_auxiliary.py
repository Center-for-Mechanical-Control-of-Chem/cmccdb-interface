"""Attachment serving tests; no live database is required."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import flask
from cmccdb_schema.proto import reaction_pb2
from cmccdb_interface.client import auxiliary


class AuxiliaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=os.environ.get("CMCCDB_TEST_TMP", Path(__file__).resolve().parent))
        self.root = Path(self.directory.name)
        (self.root / "aux").mkdir()
        (self.root / "aux" / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (self.root / "aux" / "raw.csv").write_text("time,value\n0,18\n")
        self.reaction = reaction_pb2.Reaction(reaction_id="cmcc-test")
        analysis = self.reaction.outcomes.add().analyses["XAS"]
        analysis.data["Plot"].url = "datasetid_plot.png"
        analysis.data["Raw"].url = "raw.csv"
        self.record = SimpleNamespace(reaction=self.reaction, dataset_id="cmcc_dataset-datasetid")
        self.app = flask.Flask(__name__)
        self.app.register_blueprint(auxiliary.bp)
        self.client = self.app.test_client()
        for name, value in [("BACKUP_DIR", str(self.root)), ("TEMPORARY_DIR", str(self.root / "tmp"))]:
            patcher = patch.object(auxiliary.backups, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.dict(os.environ, {"CMCCDB_AUXILIARY_DIR": str(self.root / "aux")})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(auxiliary, "_fetch_reaction", return_value=self.record)
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.directory.cleanup)

    def get(self, url, database="staging"):
        return self.client.get("/client/api/auxiliary/cmcc-test", query_string={"url": url, "database": database})

    def test_linked_image_and_legacy_dataset_prefix(self):
        response = self.get("datasetid_plot.png")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        self.assertTrue(response.data.startswith(b"\x89PNG"))
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.fetch.assert_called_once_with("cmcc-test", "staging")

    def test_non_image_download(self):
        response = self.get("raw.csv")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])

    def test_extensionless_image_with_declared_format(self):
        (self.root / "aux" / "plot").write_bytes(b"\x89PNG\r\n\x1a\n")
        self.reaction.observations.add().image.CopyFrom(reaction_pb2.Data(url="plot", format="image/png"))
        response = self.get("plot")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        self.assertIn("inline", response.headers["Content-Disposition"])

    def test_missing_or_unreferenced_file(self):
        self.assertEqual(self.get("plot.png").status_code, 404)
        self.reaction.observations.add().image.url = "missing.png"
        self.assertEqual(self.get("missing.png").status_code, 404)

    def test_no_record(self):
        self.fetch.return_value = None
        self.assertEqual(self.get("raw.csv").status_code, 404)

    def test_path_traversal_and_external_urls(self):
        for url in ["../plot.png", "%2e%2e/plot.png", "/etc/passwd", "aux/../plot.png",
                    "https://example.org/plot.png", "//example.org/plot.png", "http://[invalid", "aux\\plot.png", ".git/config"]:
            with self.subTest(url=url):
                self.reaction.observations.add().image.url = url
                self.assertEqual(self.get(url).status_code, 404)

    def test_symlink_escape(self):
        outside = self.root.parent / (self.root.name + "-outside.png")
        outside.write_bytes(b"outside")
        self.addCleanup(outside.unlink)
        (self.root / "aux" / "escape.png").symlink_to(outside)
        self.reaction.observations.add().image.url = "escape.png"
        self.assertEqual(self.get("escape.png").status_code, 404)

    def test_ambiguous_names(self):
        (self.root / "uploader").mkdir()
        (self.root / "uploader" / "raw.csv").write_text("another upload")
        self.assertEqual(self.get("raw.csv").status_code, 404)

    def test_all_nested_data_urls(self):
        self.reaction.inputs["input"].components.add().features["image"].url = "input.png"
        self.reaction.outcomes[0].products.add().features["image"].url = "product.png"
        self.reaction.setup.automation_code["program"].url = "run.py"
        self.reaction.provenance.reaction_metadata["metadata"].url = "meta.json"
        self.reaction.observations.add().image.url = "observation.png"
        self.assertEqual(set(auxiliary._data_urls(self.reaction)), {
            "datasetid_plot.png", "raw.csv", "input.png", "product.png", "run.py", "meta.json", "observation.png"})


if __name__ == "__main__":
    unittest.main()
