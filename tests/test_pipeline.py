import json
import tempfile
import unittest
from pathlib import Path

from odw2json import pipeline
from odw2json.model import Classification, Document, Extraction, Page


class FakeIngestor:
    def ingest(self, pdf_path):
        return Document(pdf_path, [Page(1, 1, 1, [], Path(pdf_path).stem, "text")])


class FakeClassifier:
    def classify(self, doc):
        name = Path(doc.path).stem
        if name.startswith("bad"):
            return Classification(None, 0.0, reason="no")
        return Classification("przelew", 1.0)


class BoomIngestor:
    def ingest(self, pdf_path):
        raise RuntimeError("boom")


class FakeExtractor:
    def extract(self, doc, doc_class):
        return Extraction({"przelew_bankowy": {"kwota": 1.5, "tytul": "Zażółć"}})


def make(tmp, files):
    for rel in files:
        p = Path(tmp) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4")


class PipelineTests(unittest.TestCase):
    def test_process_input(self):
        with tempfile.TemporaryDirectory() as t:
            inp, out = Path(t) / "in", Path(t) / "out"
            make(inp, ["c1/a.pdf", "c1/bad.pdf", "c2/b.PDF", "c2/readme.txt"])
            res = pipeline.process_input(inp, out, FakeIngestor(), FakeClassifier(), FakeExtractor())
            self.assertEqual([r.case for r in res], ["c1", "c2"])
            self.assertTrue((out / "c1" / "a.json").exists())
            self.assertEqual((out / "c1" / "bad.json").read_text(encoding="utf-8").strip(), "{}")  # UZP: rejected -> empty JSON
            self.assertTrue((out / "c2" / "b.json").exists())
            data = json.loads((out / "c1" / "a.json").read_text(encoding="utf-8"))
            self.assertEqual(data["przelew_bankowy"]["kwota"], 1.5)
            self.assertIsNone(data["przelew_bankowy"]["z_rachunku"])
            docs = {Path(d.input_path).name: d for d in res[0].documents}
            self.assertEqual(docs["a.pdf"].output_name, "a.json")
            self.assertIsNone(docs["bad.pdf"].output_name)

    def test_ingest_failure_is_warning_not_crash(self):
        with tempfile.TemporaryDirectory() as t:
            inp, out = Path(t) / "in", Path(t) / "out"
            make(inp, ["c1/a.pdf"])
            res = pipeline.process_input(inp, out, BoomIngestor(), FakeClassifier(), FakeExtractor())
            d = res[0].documents[0]
            self.assertIsNone(d.output_name)
            self.assertTrue(d.warnings)
            self.assertEqual(json.loads((out / "c1" / "a.json").read_text(encoding="utf-8")), {})

    def test_rejected_json_modes(self):
        for mode, expect in (("empty", ""), ("none", None)):
            with tempfile.TemporaryDirectory() as t:
                inp, out = Path(t) / "in", Path(t) / "out"
                make(inp, ["c1/bad.pdf"])
                pipeline.process_input(inp, out, FakeIngestor(), FakeClassifier(), FakeExtractor(), rejected_json=mode)
                f = out / "c1" / "bad.json"
                self.assertEqual(f.read_text(encoding="utf-8") if f.exists() else None, expect)

    def test_missing_input_dir(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(pipeline.process_input(Path(t) / "nope", Path(t) / "o"), [])

    def test_process_case_writes_nothing(self):
        with tempfile.TemporaryDirectory() as t:
            make(t, ["c1/a.pdf"])
            r = pipeline.process_case(Path(t) / "c1", FakeIngestor(), FakeClassifier(), FakeExtractor())
            self.assertEqual(r.case, "c1")
            self.assertEqual(r.documents[0].extraction.data["przelew_bankowy"]["kwota"], 1.5)
            self.assertFalse((Path(t) / "output").exists())


class CliTests(unittest.TestCase):
    def test_main_runs(self):
        from odw2json import cli
        with tempfile.TemporaryDirectory() as t:
            inp, out = Path(t) / "in", Path(t) / "out"
            (inp / "c1").mkdir(parents=True)
            rc = cli.main(["--input", str(inp), "--output", str(out)])
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())


class FailureTests(unittest.TestCase):
    def test_import_error_propagates(self):
        class Missing:
            def ingest(self, p):
                raise ImportError("no pdfplumber")

        with tempfile.TemporaryDirectory() as t:
            make(Path(t) / "in", ["c1/a.pdf"])
            with self.assertRaises(ImportError):
                pipeline.process_input(Path(t) / "in", Path(t) / "out", Missing(), FakeClassifier(), FakeExtractor())

    def test_exit_code_1_when_all_fail(self):
        from unittest import mock

        from odw2json import cli
        with tempfile.TemporaryDirectory() as t:
            make(Path(t) / "in", ["c1/a.pdf"])
            with mock.patch("odw2json.factory.default_ingestor", return_value=BoomIngestor()):
                rc = cli.main(["--input", str(Path(t) / "in"), "--output", str(Path(t) / "out")])
            self.assertEqual(rc, 1)
