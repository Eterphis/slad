"""T013: rules from the updated UZP data (negatives, code 12, scan-set layout)."""
import json
import tempfile
import unittest
from pathlib import Path

from eval.prep_skany import prepare
from odw2json.engine import RecipeEngine
from odw2json.model import Document, Page


def doc(text):
    return Document("x.pdf", [Page(1, 600, 800, [], text, "text")])


KIO_RULING = """Sygn. akt: KIO 1234/26
POSTANOWIENIE
z dnia 2 marca 2026 r.
Krajowa Izba Odwoławcza - w składzie:
Przewodniczący: Jan Kowalski
po rozpoznaniu odwołania wniesionego do Prezesa Krajowej Izby Odwoławczej przez wykonawcę Alfa sp. z o.o.
Odwołujący: Alfa sp. z o.o. Zamawiający: Gmina Beta. Odwołujący zarzuca Zamawiającemu naruszenie art. 16.
"""

APPEAL_PPU = """Warszawa, 10.03.2026
Do Prezesa Krajowej Izby Odwoławczej
Odwołujący:
Alfa sp. z o.o.
Zamawiający:
Gmina Beta
ODWOŁANIE
Zamawiający w dniu 02.03.2026 r. opublikował projektowane postanowienia umowy stanowiące załącznik do SWZ.
Zarzuty
"""


class NewUzpDataTests(unittest.TestCase):
    def setUp(self):
        self.engine = RecipeEngine("recipes")

    def test_kio_ruling_is_rejected(self):
        c = self.engine.classify(doc(KIO_RULING))
        self.assertIsNone(c.doc_class, c.scores)

    def test_code_12_projected_contract_terms(self):
        d = doc(APPEAL_PPU)
        self.assertEqual(self.engine.classify(d).doc_class, "odwolanie")
        k = self.engine.extract(d, "odwolanie").data["OdwolanieKIO"]
        self.assertEqual((k["czynnosc_powod_id"], k["czynnosc_opis"]), (12, "Projektowane postanowienia umowy"))

    def test_prep_skany_layout(self):
        with tempfile.TemporaryDirectory() as t:
            src, dest = Path(t) / "dane", Path(t) / "out"
            for typ in ("odwolania", "pelnomocnictwa", "potwierdzenia"):
                c = src / "skany" / typ / "0001"
                c.mkdir(parents=True)
                (c / "0001.pdf").write_bytes(b"%PDF-1.4")
                (c / "0001.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
            (src / "negatywne").mkdir()
            (src / "negatywne" / "x.pdf").write_bytes(b"%PDF-1.4")
            self.assertEqual(prepare(dest, src), (3, 1))
            self.assertTrue((dest / "input" / "odw_0001" / "0001.pdf").exists())
            self.assertTrue((dest / "gold" / "prz_0001" / "0001.json").exists())
            self.assertTrue((dest / "input" / "negatywne" / "x.pdf").exists())


if __name__ == "__main__":
    unittest.main()
