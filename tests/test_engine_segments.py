"""Generic engine additions for T005: `segments` strategy, list_of_blocks `min_blocks` and `merge`.

A fake class (a club membership form) defined only in YAML: members are listed as blocks, signatures sit in two
columns under dotted lines and are grouped per member by "W imieniu X:" captions.
"""
import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from odw2json.engine import RecipeEngine
from odw2json.ingest.layout import build_text
from odw2json.model import Document, Page

from tests.test_engine import line_words

RECIPE = textwrap.dedent(
    r"""
    class: deklaracja_klubu
    output_schema: deklaracja_klubu.json
    classify:
      signals: [{pattern: "deklaracja klubowa", weight: 2}]
    sections:
      - {name: podpisy, start: '^(?:[ \t]*w imieniu\b[^\n]*\n(?:[ \t]*\n)?)?[^\n]*\.{6,}'}
    fields:
      - path: czlonek
        list_of_blocks: {start: '(?<=[:;] )\d\)', end: 'deklaruj', min_blocks: 2}
        fields:
          - path: nazwa
            strategies:
              - {use: regex, pattern: '\d\)\s+(?P<v>[^,]+),'}
              - {use: regex, pattern: 'klub\s+(?P<v>[^,]+),'}
      - path: czlonek
        section: podpisy
        list_of_blocks: {start: '^w imieniu', min_blocks: 2, merge: true}
        fields:
          - path: podpisy[].osoba
            strategies:
              - use: segments
                all: true
                raw: true
                value: '[A-ZŁŚ][a-ząęłńóśźż]+ [A-ZŁŚ][a-ząęłńóśźż]+'
                exclude: ['prezes|skarbnik|w imieniu']
                not_after: ['trener']
    """
)
SCHEMA = {"czlonek": [{"nazwa": None, "podpisy": [{"osoba": None}]}]}


def doc(rows):
    words = [w for y, cells in rows for w in line_words(y, *cells)]
    return Document("d.pdf", [Page(1, 600, 800, words, build_text(words), "text")])


TWO_MEMBERS = doc([
    (10, [(10, "DEKLARACJA KLUBOWA")]),
    (24, [(10, "Członkowie: 1) Orlik Wola, ul. Polna 1; 2) Sokół Ursus, ul. Leśna 2, deklarują udział.")]),
    (60, [(10, "W imieniu Orlik Wola:")]),
    (74, [(10, "............"), (300, "............")]),
    (88, [(10, "Jan Kowal"), (300, "trener Piotr Lis")]),
    (102, [(10, "Prezes Klubu")]),
    (130, [(10, "W imieniu Sokół Ursus:")]),
    (144, [(10, "............")]),
    (158, [(10, "Anna Łąk")]),
    (172, [(10, "Skarbnik Klubu")]),
])

ONE_MEMBER = doc([
    (10, [(10, "DEKLARACJA KLUBOWA")]),
    (24, [(10, "Klub Orlik Wola, ul. Polna 1, deklaruje udział.")]),
    (60, [(10, "............"), (300, "............")]),
    (74, [(10, "Jan Kowal"), (300, "Ewa Sowa")]),  # two signature columns, one line
    (88, [(10, "Prezes Klubu"), (300, "Skarbnik Klubu")]),
])


class SegmentsAndBlocksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "deklaracja_klubu.yaml").write_text(RECIPE, encoding="utf-8")
        (d / "deklaracja_klubu.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        self.engine = RecipeEngine(d, dictionaries_dir=d)

    def tearDown(self):
        self.tmp.cleanup()

    def test_blocks_and_merged_signature_groups(self):
        data = self.engine.extract(TWO_MEMBERS, "deklaracja_klubu").data
        self.assertEqual([m["nazwa"] for m in data["czlonek"]], ["Orlik Wola", "Sokół Ursus"])
        self.assertEqual([[p["osoba"] for p in m["podpisy"]] for m in data["czlonek"]],
                         [["Jan Kowal"], ["Anna Łąk"]])  # role lines excluded, "trener Piotr Lis" skipped

    def test_min_blocks_falls_back_to_one_item_over_the_whole_scope(self):
        data = self.engine.extract(ONE_MEMBER, "deklaracja_klubu").data
        self.assertEqual(len(data["czlonek"]), 1)
        self.assertEqual(data["czlonek"][0]["nazwa"], "Orlik Wola")
        # segments split the line at the column gap: both signatories, not "Jan Kowal Ewa Sowa"
        self.assertEqual([p["osoba"] for p in data["czlonek"][0]["podpisy"]], ["Jan Kowal", "Ewa Sowa"])

    def test_segments_without_word_boxes(self):
        text = "DEKLARACJA KLUBOWA\nKlub Orlik Wola, ul. Polna 1, deklaruje.\n............   ............\nJan Kowal    Ewa Sowa\n"
        d = Document("t.pdf", [Page(1, 600, 800, [], text, "text")])
        data = self.engine.extract(d, "deklaracja_klubu").data
        self.assertEqual([p["osoba"] for p in data["czlonek"][0]["podpisy"]], ["Jan Kowal", "Ewa Sowa"])

    def test_evidence_paths_for_merged_blocks(self):
        ev = self.engine.extract(TWO_MEMBERS, "deklaracja_klubu").evidence
        paths = {e.path for e in ev}
        self.assertIn("czlonek[1].nazwa", paths)
        self.assertTrue(any(p.startswith("czlonek[1].podpisy[0]") for p in paths), paths)


class ShippedPelnomocnictwoTests(unittest.TestCase):
    def test_nip_stops_at_ten_digits_and_consortium_members(self):
        text = (
            "PEŁNOMOCNICTWO\nWykonawcy wspólnie ubiegający się (Konsorcjum): 1) Alfa Bud sp. z o.o., ul. Polna 1, "
            "KRS 0000123456, NIP 1234567890 00-950 Warszawa; 2) Beta S.A., ul. Leśna 2, KRS 0000654321, "
            "NIP 987-654-32-10 (dalej łącznie: „Mocodawca”), udzielają pełnomocnictwa adw. Jan Nowak.\n"
            "W imieniu Alfa Bud sp. z o.o.:\n............\nEwa Lis\nPrezes Zarządu\n"
            "W imieniu Beta S.A.:\n............\nOla Kot\nProkurent\n"
        )
        d = Document("p.pdf", [Page(1, 600, 800, [], text, "text")])
        data = RecipeEngine("recipes").extract(d, "pelnomocnictwo").data
        self.assertEqual([m["data"]["nip"] for m in data["mocodawca"]], ["1234567890", "9876543210"])
        self.assertEqual([m["data"]["nazwa"] for m in data["mocodawca"]], ["Alfa Bud sp. z o.o.", "Beta S.A."])
        self.assertEqual([[p["imie_nazwisko"] for p in m["podpisujacy"]] for m in data["mocodawca"]],
                         [["Ewa Lis"], ["Ola Kot"]])
        self.assertEqual([p["imie_nazwisko"] for p in data["pelnomocnicy"]], ["Jan Nowak"])


if __name__ == "__main__":
    unittest.main()
