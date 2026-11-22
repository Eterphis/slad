"""Generic engine features for lists of people: `dedupe`, `attach_to` (a value printed next to each list item)
and the `person` normaliser's glued-name split. Classes are defined by YAML in a temp dir, as in test_engine."""
import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from odw2json.engine import RecipeEngine
from odw2json.engine.dedupe import dedupe_names, same_name
from odw2json.engine.normalise import NORMALISERS
from odw2json.model import Document, Page

RECIPE = textwrap.dedent(
    r"""
    class: lista
    output_schema: lista.json
    classify:
      min_score: 1
      signals: [{pattern: "lista"}]
    fields:
      - path: osoby[].imie_nazwisko
        strategies:
          - {use: regex, all: true, raw: true, pattern: '(?P<v>[A-ZŁ][\w-]+ [A-ZŁ][\w-]+)\s*\('}
        normalize: person
        dedupe: {}
      - path: osoby[].pesel
        attach_to: osoby[].imie_nazwisko
        window: 60
        strategies:
          - {use: regex, pattern: 'pesel\W{0,3}(?P<v>\d{11})'}
        normalize: digits
        validate: pesel
    """
)
SCHEMA = {"osoby": [{"imie_nazwisko": None, "pesel": None}]}


def run(text):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "lista.yaml").write_text(RECIPE, encoding="utf-8")
        (d / "lista.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        engine = RecipeEngine(d, dictionaries_dir=d)
        return engine.extract(Document("x.pdf", [Page(1, 1, 1, [], text, "text")]), "lista").data


class SameNameTests(unittest.TestCase):
    def test_folding_and_one_character(self):
        self.assertTrue(same_name("Mateusz Wierzbicki", "MATEUSZ WIERZBICKI", 0))
        self.assertTrue(same_name("Szymon Zawadżki", "Szymon Zawadzki", 0))  # diacritics fold away
        self.assertTrue(same_name("Szymon Zawadzski", "Szymon Zawadzki", 1))
        self.assertFalse(same_name("Szymon Zawadzski", "Szymon Zawadzki", 0))
        self.assertFalse(same_name("Anna Nowak", "Jan Nowak", 1))
        self.assertFalse(same_name("Anna Nowak", "Anna Kowalska", 1))

    def test_kowalski_and_kowalska_stay_two_people(self):
        self.assertFalse(same_name("Jan Kowalski", "Jan Kowalska"))
        self.assertEqual(dedupe_names(["Jan Kowalski", "Jan Kowalska"]), ["Jan Kowalski", "Jan Kowalska"])
        out = run("lista\nJan Kowalski (adw.)\nJan Kowalska (r. pr.)")
        self.assertEqual(len(out["osoby"]), 2)

    def test_dedupe_prefers_mixed_case_then_later(self):
        self.assertEqual(dedupe_names(["MATEUSZ WIERZBICKI", "Mateusz Wierzbicki"], 1), ["Mateusz Wierzbicki"])
        self.assertEqual(dedupe_names(["Mateusz Wierzbicki", "MATEUSZ WIERZBICKI"], 1), ["Mateusz Wierzbicki"])
        self.assertEqual(dedupe_names(["Jan Zawadżki", "Ewa Lis", "Jan Zawadzki"]), ["Jan Zawadzki", "Ewa Lis"])
        self.assertEqual(dedupe_names(["Ewa Lis", "Jan Lis"], 1), ["Ewa Lis", "Jan Lis"])


class EngineListTests(unittest.TestCase):
    def test_dedupe_option_merges_duplicates_in_a_list_field(self):
        out = run("lista\nJan Kowalski (adw.)\nJAN KOWALSKI (adw.)\nEwa Lis (r. pr.)")
        self.assertEqual([o["imie_nazwisko"] for o in out["osoby"]], ["Jan Kowalski", "Ewa Lis"])

    def test_empty_dedupe_option_still_folds_diacritics(self):
        out = run("lista\nSzymon Zawadżki (adw.)\nSzymon Zawadzki (adw.)")
        self.assertEqual([o["imie_nazwisko"] for o in out["osoby"]], ["Szymon Zawadzki"])

    def test_attach_reads_a_value_after_each_item_only(self):
        out = run("lista\nJan Kowalski (adw., nr wpisu W-1, PESEL: 44051401359)\nEwa Lis (r. pr.) bez numeru")
        self.assertEqual(out["osoby"][0]["pesel"], "44051401359")
        self.assertIsNone(out["osoby"][1]["pesel"])  # the first person's PESEL is not borrowed

    def test_attach_without_a_colon_and_after_titles(self):
        out = run("lista\nKatarzyna Michalak (r. pr. PESEL 85071204278)")
        self.assertEqual(out["osoby"][0]["pesel"], "85071204278")

    def test_attach_survives_dedupe_and_all_caps(self):
        out = run("lista\nJAN KOWALSKI (adw.) PESEL 44051401359\nJan Kowalski (adw.)")
        self.assertEqual(len(out["osoby"]), 1)
        self.assertEqual(out["osoby"][0]["pesel"], "44051401359")


class GluedNameTests(unittest.TestCase):
    person = staticmethod(NORMALISERS["person"])

    def test_split_when_both_parts_look_like_names(self):
        self.assertEqual(self.person("HalinaBaran"), "Halina Baran")
        self.assertEqual(self.person("Jan KowalskiNowak"), "Jan Kowalski Nowak")

    def test_normal_names_stay(self):
        for name in ["Jan Kowalski", "Anna Kowalska-Nowak", "ŁUKASZ SOSNOWSKI", "Maria Łabędź"]:
            self.assertEqual(self.person(name), name if name != "ŁUKASZ SOSNOWSKI" else "Łukasz Sosnowski")

    def test_company_and_identifier_normalisers_do_not_split(self):
        self.assertEqual(NORMALISERS["company"]("BudMax ePUAP Sp. z o.o."), "BudMax ePUAP Sp. z o.o.")
        self.assertEqual(NORMALISERS["strip"]("eKRS"), "eKRS")


if __name__ == "__main__":
    unittest.main()
