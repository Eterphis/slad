import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from eval import make_noisy as mn


def _make_pdf(path: Path, pages: int = 2) -> None:
    imgs = []
    for i in range(pages):
        im = Image.new("L", (400, 560), 255)
        ImageDraw.Draw(im).rectangle([40, 40, 360, 80], fill=0)
        imgs.append(im)
    imgs[0].save(path, format="PDF", save_all=True, append_images=imgs[1:])


class MakeNoisyTest(unittest.TestCase):
    def test_parse_cases(self):
        self.assertEqual(mn.parse_cases("41-43"), [41, 42, 43])
        self.assertEqual(mn.parse_cases("1,7,41-42"), [1, 7, 41, 42])

    def test_degrade_deterministic_and_changes_image(self):
        base = Image.new("L", (300, 400), 255)
        a = mn.degrade_image(base, mn._rng(1, "x"))
        b = mn.degrade_image(base, mn._rng(1, "x"))
        c = mn.degrade_image(base, mn._rng(2, "x"))
        self.assertEqual(a.size, base.size)
        self.assertTrue(np.array_equal(np.asarray(a), np.asarray(b)))
        self.assertFalse(np.array_equal(np.asarray(a), np.asarray(c)))
        self.assertFalse(np.array_equal(np.asarray(a), np.asarray(base)))

    def test_build_image_only_pdf_and_gold(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            case = t / "src" / "przyklad_41"
            case.mkdir(parents=True)
            _make_pdf(case / "odwolanie.pdf")
            (case / "odwolanie.json").write_text('{"a": 1}', encoding="utf8")
            out = t / "out"
            self.assertEqual(mn.build(t / "src", out, [41], dpi=72), (1, 1))
            pdf = out / "input" / "przyklad_41" / "odwolanie.pdf"
            import pdfplumber, pypdfium2

            with pdfplumber.open(pdf) as d:
                self.assertEqual(len(d.pages), 2)
                self.assertFalse(any((p.extract_text() or "").strip() for p in d.pages))
            self.assertTrue(pypdfium2.PdfDocument(str(pdf)))
            self.assertEqual((out / "gold" / "przyklad_41" / "odwolanie.json").read_text(encoding="utf8"), '{"a": 1}')
            # reproducible
            out2 = t / "out2"
            mn.build(t / "src", out2, [41], dpi=72)
            self.assertEqual(pdf.read_bytes(), (out2 / "input" / "przyklad_41" / "odwolanie.pdf").read_bytes())

    def test_missing_case_raises(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(FileNotFoundError):
                mn.build(Path(t), Path(t) / "o", [99])


if __name__ == "__main__":
    unittest.main()


class DefaultSrcTest(unittest.TestCase):
    def test_finds_uzp_data_in_a_parent_folder_without_env(self):
        import os
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "uzp-data" / "dane").mkdir(parents=True)
            nested = root / ".worktrees" / "T010"
            nested.mkdir(parents=True)
            env = {k: v for k, v in os.environ.items() if k != "UZP_DATA"}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(Path(mn.default_src(nested)), (root / "uzp-data" / "dane").resolve())
            with mock.patch.dict(os.environ, {"UZP_DATA": str(root / "x")}):
                self.assertEqual(Path(mn.default_src(nested)), root / "x" / "dane")
