"""Worker pool: output equals serial output, order is deterministic, a failing document never kills the run.

Components are fakes defined at module level (picklable, importable by spawned workers); no data or OCR needed."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from odw2json import pipeline
from odw2json.model import Classification, Document, Extraction, Page


class Ing:
    def ingest(self, pdf_path):
        stem = Path(pdf_path).stem
        if stem.startswith("boom"):
            raise RuntimeError("boom")
        if stem.startswith("die"):
            os._exit(3)  # hard worker death
        return Document(pdf_path, [Page(1, 1, 1, [], stem, "text")])


class Cls:
    def classify(self, doc):
        if Path(doc.path).stem.startswith("bad"):
            return Classification(None, 0.0, reason="no")
        return Classification("przelew", 1.0)


class Ext:
    def extract(self, doc, doc_class):
        return Extraction({"przelew_bankowy": {"tytul": Path(doc.path).stem, "kwota": 1.5}})


def build():
    return Ing(), Cls(), Ext()


def make(tmp, files):
    for rel in files:
        p = Path(tmp) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4")


def tree(out):
    return {str(p.relative_to(out)): p.read_text(encoding="utf-8") for p in sorted(Path(out).rglob("*.json"))}


FILES = [f"c{c}/d{d}.pdf" for c in range(3) for d in range(4)] + ["c1/bad.pdf", "c2/boom.pdf"]


class WorkerTests(unittest.TestCase):
    def run_it(self, workers, files=FILES, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        make(Path(tmp.name) / "in", files)
        stats = {}
        res = pipeline.process_input(Path(tmp.name) / "in", Path(tmp.name) / "out", workers=workers, builder=build, stats=stats, **kw)
        return res, tree(Path(tmp.name) / "out"), stats

    def test_parallel_equals_serial(self):
        r1, t1, _ = self.run_it(1)
        r3, t3, _ = self.run_it(3)
        self.assertEqual(t1, t3)
        self.assertEqual([(r.case, [Path(d.input_path).name for d in r.documents]) for r in r1],
                         [(r.case, [Path(d.input_path).name for d in r.documents]) for r in r3])
        self.assertEqual(len(t3), len(FILES))

    def test_failed_doc_is_empty_object_not_crash(self):
        _, t, _ = self.run_it(2)
        self.assertEqual(json.loads(t[str(Path("c2/boom.json"))]), {})
        self.assertEqual(json.loads(t[str(Path("c1/bad.json"))]), {})
        self.assertIn("przelew_bankowy", json.loads(t[str(Path("c0/d0.json"))]))

    def test_dead_worker_does_not_crash_run(self):
        files = ["c0/d0.pdf", "c0/die.pdf", "c1/d1.pdf", "c1/d2.pdf"]
        _, t, _ = self.run_it(2, files)
        self.assertEqual(set(t), {str(Path(f).with_suffix(".json")) for f in files})
        self.assertEqual(json.loads(t[str(Path("c0/die.json"))]), {})
        self.assertIn("przelew_bankowy", json.loads(t[str(Path("c1/d2.json"))]))

    def test_stats_has_seconds_per_document(self):
        _, _, stats = self.run_it(2)
        self.assertEqual(len(stats["docs"]), len(FILES))
        self.assertTrue(all(x["seconds"] >= 0 for x in stats["docs"]))
        self.assertEqual(stats["workers"], 2)

    def test_workers_capped_by_documents(self):
        _, _, stats = self.run_it(8, ["c0/a.pdf", "c0/b.pdf"])
        self.assertEqual(stats["workers"], 2)

    def test_injected_components_force_serial(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        make(Path(tmp.name) / "in", ["c/a.pdf", "c/b.pdf"])
        stats = {}
        pipeline.process_input(Path(tmp.name) / "in", Path(tmp.name) / "out", Ing(), Cls(), Ext(), workers=4, stats=stats)
        self.assertEqual(stats["workers"], 1)


class DefaultWorkersTests(unittest.TestCase):
    def test_default(self):
        old = os.environ.pop("ODW2JSON_WORKERS", None)
        try:
            n = pipeline.default_workers()
            self.assertTrue(1 <= n <= 4)
            os.environ["ODW2JSON_WORKERS"] = "3"
            self.assertEqual(pipeline.default_workers(), 3)
            os.environ["ODW2JSON_WORKERS"] = "0"
            self.assertEqual(pipeline.default_workers(), 1)
            os.environ["ODW2JSON_WORKERS"] = "junk"
            self.assertTrue(1 <= pipeline.default_workers() <= 4)
        finally:
            os.environ.pop("ODW2JSON_WORKERS", None)
            if old is not None:
                os.environ["ODW2JSON_WORKERS"] = old


if __name__ == "__main__":
    unittest.main()
