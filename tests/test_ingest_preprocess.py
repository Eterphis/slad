import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from odw2json.ingest import PdfIngestor
from odw2json.ingest.preprocess import PREPROCESSORS, merge_lines, needs_retry, preprocess_image, shaky_bands
from tests.uzp_data import UZP

SCAN = UZP / "dane" / "skany" / "odwolania" / "0005" / "0005.pdf"


class PreprocessImageTests(unittest.TestCase):
    def _img(self):
        a = np.full((40, 60, 3), 250, np.uint8)
        a[5:10, :] = 20      # dark print
        a[20:25, :] = 190    # light show-through
        a[30:35, :] = 100    # mid grey
        return Image.fromarray(a)

    def test_none_returns_same_image(self):
        im = self._img()
        self.assertIs(preprocess_image(im, "none"), im)

    def test_levels_whitens_showthrough_keeps_print(self):
        out = np.asarray(preprocess_image(self._img(), "levels"))
        self.assertEqual(out.shape, (40, 60, 3))
        self.assertLess(out[7, 10, 0], 15)
        self.assertEqual(out[22, 10, 0], 255)
        self.assertEqual(out[2, 10, 0], 255)
        self.assertTrue(0 < out[32, 10, 0] < 255)

    def test_levels_adapts_to_faint_print(self):
        a = np.full((30, 30, 3), 250, np.uint8)
        a[10:15, :] = 120  # faint print, nothing darker
        out = np.asarray(preprocess_image(Image.fromarray(a), "levels"))
        self.assertLess(out[12, 5, 0], 30)  # still read as ink

    def test_unknown_name(self):
        with self.assertRaises(ValueError):
            preprocess_image(self._img(), "nope")

    def test_registry(self):
        self.assertIn("levels", PREPROCESSORS)


class MergeTests(unittest.TestCase):
    def test_needs_retry(self):
        shaky = [("x", (0, i * 10, 50, i * 10 + 8), 0.6) for i in range(5)]
        self.assertTrue(needs_retry(shaky))
        self.assertFalse(needs_retry(shaky[:4]))
        self.assertFalse(needs_retry([("x", (0, 0, 5, 5), 0.99)] * 50))

    def test_better_cleaned_line_replaces_shaky_one(self):
        base = [("ok line", (0, 0, 100, 20), 0.99), ("Z e ien", (0, 30, 100, 50), 0.7)]
        cleaned = [("ok line!", (0, 1, 100, 21), 0.99), ("ZP/12/2026", (0, 31, 100, 51), 0.98)]
        out = merge_lines(base, cleaned)
        self.assertEqual(sorted(t for t, _, _ in out), ["ZP/12/2026", "ok line"])

    def test_cleaned_line_not_better_is_ignored(self):
        base = [("so so", (0, 0, 100, 20), 0.7)]
        self.assertEqual(merge_lines(base, [("worse", (0, 0, 100, 20), 0.6)]), base)

    def test_lost_line_is_added_but_neighbour_overlap_is_not_a_match(self):
        base = [("a", (0, 0, 100, 40), 0.99)]
        out = merge_lines(base, [("b", (0, 60, 100, 90), 0.9), ("c", (0, 30, 100, 70), 0.9)])
        self.assertEqual({t for t, _, _ in out}, {"a", "b", "c"})


class BandTests(unittest.TestCase):
    def test_bands_merge_and_clip(self):
        lines = [("a", (0, 100, 50, 120), 0.5), ("b", (0, 130, 50, 150), 0.5), ("c", (0, 500, 50, 520), 0.5),
                 ("ok", (0, 300, 50, 320), 0.99)]
        self.assertEqual(shaky_bands(lines, 515), [(90, 160), (490, 515)])


class AutoModeTests(unittest.TestCase):
    def test_auto_retries_only_shaky_pages(self):
        import types
        calls = []

        class B:
            def __init__(self, conf):
                self.conf = conf

            def ocr(self, image):
                calls.append(1)
                return [("x", (0, i * 10, 50, i * 10 + 8), self.conf) for i in range(6)]

        ing = PdfIngestor(backend=B(0.99), config={"ingest": {"cache": False}})
        ing._read(Image.new("RGB", (50, 80), "white"))
        self.assertEqual(len(calls), 1)
        calls.clear()
        ing = PdfIngestor(backend=B(0.6), config={"ingest": {"cache": False}})
        ing._read(Image.new("RGB", (50, 80), "white"))
        self.assertEqual(len(calls), 2)


class FakeBackend:
    def __init__(self):
        self.sizes = []

    def ocr(self, image):
        self.sizes.append(np.asarray(image).min())
        return [("x", (1, 1, 20, 10), 0.9)]


@unittest.skipUnless(SCAN.exists(), "UZP data not available")
class WiringTests(unittest.TestCase):
    def test_config_and_cache_key(self):
        with tempfile.TemporaryDirectory() as d:
            a = PdfIngestor(backend=FakeBackend(), config={"ingest": {"cache_dir": d, "preprocess": "none"}})
            b = PdfIngestor(backend=FakeBackend(), config={"ingest": {"cache_dir": d, "preprocess": "levels"}})
            self.assertEqual(a.preprocess, "none")
            self.assertEqual(b.preprocess, "levels")
            self.assertNotEqual(a._cache_key(SCAN, 0), b._cache_key(SCAN, 0))
            a.ingest(str(SCAN))
            fb = FakeBackend()
            b2 = PdfIngestor(backend=fb, config={"ingest": {"cache_dir": d, "preprocess": "levels"}})
            b2.ingest(str(SCAN))
            self.assertTrue(fb.sizes)  # not served from the 'none' cache

    def test_default_is_auto(self):
        self.assertEqual(PdfIngestor(backend=FakeBackend()).preprocess, "auto")

    def test_env_overrides_config(self):
        import os
        os.environ["ODW2JSON_PREPROCESS"] = "none"
        try:
            self.assertEqual(PdfIngestor(backend=FakeBackend(), config={"ingest": {"preprocess": "levels"}}).preprocess, "none")
        finally:
            del os.environ["ODW2JSON_PREPROCESS"]

    def test_bad_name_rejected(self):
        with self.assertRaises(ValueError):
            PdfIngestor(backend=FakeBackend(), config={"ingest": {"preprocess": "nope"}})


if __name__ == "__main__":
    unittest.main()
