"""Generic engine additions of T014: strategy-level `section`, regex `nth`, normalisers `restore_diacritics`,
`ocr_text`, `flag`, date_pl "dd mm yyyy".

A fake class (a parcel slip) defined only in YAML; no document class of the product appears in the engine.
"""
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from odw2json.engine import RecipeEngine
from odw2json.engine.normalise import NORMALISERS
from odw2json.ingest.layout import build_text
from odw2json.model import Document, Page

from tests.test_engine import line_words

RECIPE = textwrap.dedent(
    r"""
    class: paczka
    output_schema: paczka.json
    classify:
      signals: [{pattern: "list przewozowy", weight: 2}]
    sections:
      - {name: nadawca, start: '^nadawca', end: '^odbiorca'}
      - {name: odbiorca, start: '^odbiorca'}
    fields:
      - path: paczka.nadawca_konto
        strategies:
          - {use: regex, pattern: '(?P<v>\d{2}(?:\s?\d{4}){6})', nth: 0}
      - path: paczka.odbiorca_konto
        strategies:
          - {use: regex, pattern: '(?P<v>\d{2}(?:\s?\d{4}){6})', nth: 1}
      - path: paczka.ostatnie_konto
        strategies:
          - {use: regex, pattern: '(?P<v>\d{2}(?:\s?\d{4}){6})', nth: -1}
      - path: paczka.trzecie_konto
        strategies:
          - {use: regex, pattern: '(?P<v>\d{2}(?:\s?\d{4}){6})', nth: 5}
      # the same pattern in two sections: each strategy searches only its own section
      - path: paczka.kod_nadawcy
        strategies:
          - {use: regex, section: nadawca, pattern: 'kod:?\s*(?P<v>\d+)'}
      - path: paczka.kod_odbiorcy
        strategies:
          - {use: regex, section: odbiorca, pattern: 'kod:?\s*(?P<v>\d+)'}
      # a strategy whose section does not exist is skipped; the next one runs
      - path: paczka.kod_awaryjny
        strategies:
          - {use: regex, section: nie_ma_takiej, pattern: 'kod:?\s*(?P<v>\d+)'}
          - {use: regex, pattern: 'kod:?\s*(?P<v>\d+)'}
      - path: paczka.tytul
        strategies:
          - {use: between, start: '^opis\s*:?\s*', end: '\n\s*\n'}
        normalize: [unquote, ocr_text, restore_diacritics]
      - path: paczka.priorytet
        strategies:
          - {use: regex, pattern: '(?P<v>ekspres)'}
        normalize: flag
    """
)
SCHEMA = '{"paczka": {"nadawca_konto": null, "odbiorca_konto": null, "ostatnie_konto": null, "trzecie_konto": null, "kod_nadawcy": null, "kod_odbiorcy": null, "kod_awaryjny": null, "tytul": null, "priorytet": null}}'

ACC_A = "61 1090 1014 0000 0712 1981 2874"
ACC_B = "27 1140 2004 0000 3002 0135 5387"


def doc(lines):
    words = [w for i, t in enumerate(lines) for w in line_words(10 + 14 * i, (10, t))]
    return Document("d.pdf", [Page(1, 600, 800, words, build_text(words), "text")])


SLIP = doc([
    "LIST PRZEWOZOWY",
    "Nadawca kod 11",
    ACC_A,
    "Odbiorca kod 22",
    ACC_B,
    "Opis: przesylka oplata skarbowa dla Zosia",
    "",
    "ekspres",
])


class ScanRecipeEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        (base / "recipes").mkdir()
        (base / "recipes" / "paczka.yaml").write_text(RECIPE, encoding="utf-8")
        (base / "recipes" / "paczka.json").write_text(SCHEMA, encoding="utf-8")
        (base / "dictionaries").mkdir()
        (base / "dictionaries" / "polish_words.txt").write_text("przesyłka\nopłata\nzosia\nzośka\nzoska\n", encoding="utf-8")
        cls.old_env = os.environ.get("ODW2JSON_DICTIONARIES")
        os.environ["ODW2JSON_DICTIONARIES"] = str(base / "dictionaries")
        cls.data = RecipeEngine(base / "recipes").extract(SLIP, "paczka").data["paczka"]

    @classmethod
    def tearDownClass(cls):
        if cls.old_env is None:
            os.environ.pop("ODW2JSON_DICTIONARIES", None)
        else:
            os.environ["ODW2JSON_DICTIONARIES"] = cls.old_env
        cls.tmp.cleanup()

    def test_regex_nth_picks_the_nth_distinct_match(self):
        self.assertEqual(self.data["nadawca_konto"], ACC_A)
        self.assertEqual(self.data["odbiorca_konto"], ACC_B)
        self.assertEqual(self.data["ostatnie_konto"], ACC_B)

    def test_regex_nth_out_of_range_finds_nothing(self):
        self.assertIsNone(self.data["trzecie_konto"])

    def test_strategy_section_limits_the_search(self):
        self.assertEqual((self.data["kod_nadawcy"], self.data["kod_odbiorcy"]), ("11", "22"))

    def test_strategy_with_a_missing_section_is_skipped(self):
        self.assertEqual(self.data["kod_awaryjny"], "11")

    def test_normaliser_chain_restores_diacritics_from_the_word_list(self):
        self.assertEqual(self.data["tytul"], "przesyłka opłata skarbowa dla Zosia")  # "skarbowa", "dla" unknown: kept

    def test_flag_normaliser_gives_one_for_a_marker(self):
        self.assertEqual(self.data["priorytet"], 1)


class NormaliserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        (Path(self.tmp.name) / "polish_words.txt").write_text("odwołania\nłódź\nusługa\nusługą\nżaneta\n", encoding="utf-8")
        self.old = os.environ.get("ODW2JSON_DICTIONARIES")
        os.environ["ODW2JSON_DICTIONARIES"] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop("ODW2JSON_DICTIONARIES", None)
        else:
            os.environ["ODW2JSON_DICTIONARIES"] = self.old
        self.tmp.cleanup()

    def test_restore_keeps_the_case_style(self):
        f = NORMALISERS["restore_diacritics"]
        self.assertEqual(f("wpis od odwolania"), "wpis od odwołania")
        self.assertEqual(f("WPIS OD ODWOLANIA"), "WPIS OD ODWOŁANIA")
        self.assertEqual(f("Odwolania Zaneta"), "Odwołania Żaneta")

    def test_restore_repairs_wrong_accents_but_not_ambiguous_words(self):
        f = NORMALISERS["restore_diacritics"]
        self.assertEqual(f("Lódź"), "Łódź")
        self.assertEqual(f("usluga"), "usluga")  # usługa / usługą: cannot tell, left alone
        self.assertEqual(f("usługa"), "usługa")

    def test_restore_without_a_word_list_changes_nothing(self):
        os.environ["ODW2JSON_DICTIONARIES"] = str(Path(self.tmp.name) / "nope")
        self.assertEqual(NORMALISERS["restore_diacritics"]("odwolania"), "odwolania")

    def test_ocr_text_maps_tilde_letters_and_case_number_colons(self):
        f = NORMALISERS["ocr_text"]
        self.assertEqual(f("PAÑSTWOWEJ  STRAŻY"), "PAŃSTWOWEJ STRAŻY")
        self.assertEqual(f("DA.ZP:242.13.2026"), "DA.ZP.242.13.2026")
        self.assertEqual(f("ZAM: KOMENDA"), "ZAM: KOMENDA")

    def test_date_pl_reads_day_month_year_separated_by_spaces(self):
        self.assertEqual(NORMALISERS["date_pl"]("20 04 2026"), "2026-04-20")
        self.assertEqual(NORMALISERS["date_pl"]("20.04.2026"), "2026-04-20")


if __name__ == "__main__":
    unittest.main()
