import os
import tempfile
import unittest
from pathlib import Path

from odw2json.ingest import PdfIngestor, get_backend, register_backend
from odw2json.ingest.pdf import lines_to_words
from tests.uzp_data import UZP

DATA = UZP
DIGITAL = DATA / "dane" / "przyklad_07" / "odwolanie.pdf"
SCAN = DATA / "szablon-aplikacja" / "input" / "case1" / "przyklad odwolanie.pdf"


class FakeBackend:
    def __init__(self):
        self.calls = 0

    def ocr(self, image):
        self.calls += 1
        w, h = image.size
        return [("Odwołujący Zamawiający", (w * 0.1, h * 0.1, w * 0.5, h * 0.12), 0.9)]


class LinesToWordsTests(unittest.TestCase):
    def test_split_and_scale(self):
        ws = lines_to_words([("ab cd", (0, 10, 100, 30), 0.8)], 2.0)
        self.assertEqual([w.text for w in ws], ["ab", "cd"])
        self.assertAlmostEqual(ws[0].x0, 0.0)
        self.assertAlmostEqual(ws[1].x1, 50.0)
        self.assertAlmostEqual(ws[0].y0, 5.0)
        self.assertAlmostEqual(ws[0].y1, 15.0)
        self.assertEqual(ws[0].conf, 0.8)
        self.assertLess(ws[0].x1, ws[1].x0)

    def test_low_confidence_dropped(self):
        self.assertEqual(lines_to_words([("n on nn", (0, 0, 10, 5), 0.5)], 1.0, min_conf=0.6), [])
        self.assertEqual(len(lines_to_words([("ok", (0, 0, 10, 5), 0.9)], 1.0, min_conf=0.6)), 1)

    def test_blank_line_skipped(self):
        self.assertEqual(lines_to_words([("  ", (0, 0, 1, 1), 1.0)], 1.0), [])


class BackendRegistryTests(unittest.TestCase):
    def test_register_and_select(self):
        register_backend("fake-test", lambda cfg: FakeBackend())
        self.assertIsInstance(get_backend({"ocr": {"backend": "fake-test"}}), FakeBackend)

    def test_env_overrides_config(self):
        register_backend("fake-test", lambda cfg: FakeBackend())
        os.environ["ODW2JSON_OCR"] = "fake-test"
        try:
            self.assertIsInstance(get_backend({"ocr": {"backend": "tesseract"}}), FakeBackend)
        finally:
            del os.environ["ODW2JSON_OCR"]

    def test_unknown(self):
        with self.assertRaises(ValueError):
            get_backend({"ocr": {"backend": "nope"}})


@unittest.skipUnless(DIGITAL.exists(), "UZP data not available")
class TextLayerTests(unittest.TestCase):
    def test_digital_pdf_uses_text_layer_without_ocr(self):
        fb = FakeBackend()
        doc = PdfIngestor(backend=fb, config={"ingest": {"cache": False}}).ingest(str(DIGITAL))
        self.assertEqual(fb.calls, 0)
        self.assertTrue(all(p.source == "text" for p in doc.pages))
        self.assertIn("Zamawiający", doc.text)
        for p in doc.pages:
            self.assertTrue(p.words)
            for w in p.words:
                self.assertTrue(0 <= w.x0 <= w.x1 <= p.width + 1 and 0 <= w.y0 <= w.y1 <= p.height + 1)


@unittest.skipUnless(SCAN.exists(), "UZP data not available")
class OcrFallbackTests(unittest.TestCase):
    def test_scan_pages_go_to_ocr_and_boxes_are_in_points(self):
        fb = FakeBackend()
        with tempfile.TemporaryDirectory() as d:
            ing = PdfIngestor(backend=fb, config={"ingest": {"cache_dir": d}})
            doc = ing.ingest(str(SCAN))
            self.assertEqual(len(doc.pages), 7)
            self.assertEqual(fb.calls, 7)
            for p in doc.pages:
                self.assertEqual(p.source, "ocr")
                self.assertIn("Odwołujący", p.text)
                self.assertTrue(all(0 <= w.x0 <= w.x1 <= p.width and 0 <= w.y0 <= w.y1 <= p.height for w in p.words))
            # second run is served from the cache
            ing.ingest(str(SCAN))
            self.assertEqual(fb.calls, 7)


if __name__ == "__main__":
    unittest.main()


class OcrSwitchTests(unittest.TestCase):
    @unittest.skipUnless(SCAN.exists(), "needs UZP template scan")
    def test_ocr_disabled_leaves_scan_empty(self):
        b = FakeBackend()
        doc = PdfIngestor(backend=b, config={"ocr": {"enabled": False}}).ingest(str(SCAN))
        self.assertEqual(b.calls, 0)
        self.assertTrue(all(p.words == [] and p.text == "" for p in doc.pages))

    def test_cache_env_overrides(self):
        old = dict(os.environ)
        try:
            os.environ["ODW2JSON_OCR_CACHE"] = "0"
            self.assertIsNone(PdfIngestor(backend=FakeBackend()).cache_dir)
            del os.environ["ODW2JSON_OCR_CACHE"]
            os.environ["ODW2JSON_OCR_CACHE_DIR"] = "somewhere"
            self.assertEqual(PdfIngestor(backend=FakeBackend()).cache_dir, Path("somewhere"))
        finally:
            os.environ.clear()
            os.environ.update(old)
