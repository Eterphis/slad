import json
import random
import tempfile
import unittest
from pathlib import Path

try:
    import reportlab  # noqa: F401  (dev-only dependency of eval.make_synth)
    from eval import make_synth as ms
except ImportError:  # pragma: no cover
    ms = None

ROOT = Path(__file__).resolve().parents[1]


def _keys(d):
    """Key skeleton of a JSON value: dict keys recursively, list -> skeleton of its first item."""
    if isinstance(d, dict):
        return {k: _keys(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_keys(d[0])] if d else []
    return None


@unittest.skipIf(ms is None, "reportlab not installed")
class MakeSynthTest(unittest.TestCase):
    def test_checksums(self):
        r = random.Random(1)
        for _ in range(50):
            n = ms.nip(r)
            self.assertEqual(sum(int(a) * b for a, b in zip(n, (6, 5, 7, 2, 3, 4, 5, 6, 7))) % 11, int(n[9]))
            p = ms.pesel(r, female=True)
            self.assertEqual(int(p[9]) % 2, 0)
            acct = ms.nrb(r)
            self.assertEqual(len(acct), 26)
            self.assertEqual(int(acct[2:] + "2521" + acct[:2]) % 97, 1)  # IBAN mod-97 check

    def test_declension(self):
        self.assertEqual(ms.surname_forms("Kowalski", False), ("Kowalski", "Kowalskiego", "Kowalskiemu"))
        self.assertEqual(ms.surname_forms("Kowalski", True), ("Kowalska", "Kowalską", "Kowalskiej"))
        self.assertEqual(ms.surname_forms("Wróbel", False)[1], "Wróbla")
        self.assertEqual(ms.surname_forms("Nowak", True), ("Nowak", "Nowak", "Nowak"))

    def test_generate_small_set(self):
        try:
            ms.register_fonts()
        except SystemExit:
            self.skipTest("no TTF fonts on this machine")
        templates = {t: _keys(json.loads((ROOT / "schemas" / f"{t}.json").read_text(encoding="utf-8")))
                     for t in ("odwolanie", "pelnomocnictwo", "przelew")}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "s"
            m = ms.generate(out, 3, seed=5, scan_share=0.5)
            self.assertEqual(len(m["cases"]), 3)
            for case, c in m["cases"].items():
                classes = [d["class"] for d in c["docs"]]
                self.assertEqual(classes.count("odwolanie"), 1)
                for d in c["docs"]:
                    pdf = out / "input" / case / d["file"]
                    self.assertTrue(pdf.is_file() and pdf.read_bytes().startswith(b"%PDF"))
                    gold = out / "gold" / case / (Path(d["file"]).stem + ".json")
                    if d["class"] == "negatywny":
                        self.assertFalse(gold.exists())
                        continue
                    g = json.loads(gold.read_text(encoding="utf-8"))
                    self.assertEqual(_keys(g), templates[d["class"]], f"{case}/{d['file']}")
            # same seed -> same gold
            m2 = ms.generate(Path(tmp) / "s2", 3, seed=5, scan_share=0.5)
            self.assertEqual([d["file"] for d in m["cases"]["synth_01"]["docs"]],
                             [d["file"] for d in m2["cases"]["synth_01"]["docs"]])


if __name__ == "__main__":
    unittest.main()
