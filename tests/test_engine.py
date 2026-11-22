"""Generic recipe engine: a class defined only by YAML in a temp dir is classified and extracted (no code)."""
import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from odw2json.engine import RecipeEngine, RecipeError, load_recipes
from odw2json.engine.normalise import NORMALISERS, VALIDATORS
from odw2json.engine.text import fold, squash
from odw2json.model import Document, Page, Word

FAKE_RECIPE = textwrap.dedent(
    r"""
    class: zamowienie_pizzy
    output_schema: zamowienie_pizzy.json
    classify:
      min_score: 3
      signals:
        - {pattern: "zamowienie pizzy", weight: 3, head: 200, squash: true}
        - {pattern: "pizzeria", weight: 1}
      forbidden: ["to nie jest zamowienie"]
    sections:
      - {name: klient, start: "^klient:", end: "^dostawa:"}
    fields:
      - path: zamowienie.data
        strategies:
          - {use: regex, pattern: "z dnia (?P<v>\\d{1,2} \\w+ \\d{4})"}
        normalize: date_pl
      - path: zamowienie.kwota
        strategies:
          - {use: after_label, labels: ["do zaplaty"], value: "\\d[\\d ]*,\\d{2}"}
        normalize: amount_pl
      - path: zamowienie.rachunek
        strategies:
          - {use: after_label, labels: ["rachunek odbiorcy"]}
        normalize: iban_pl
        validate: iban
      - path: zamowienie.uwagi
        strategies:
          - {use: between, start: "^uwagi$", end: "^koniec$"}
      - path: zamowienie.rodzaj
        strategies:
          - {use: lookup, dictionary: rodzaje, return: id}
      - path: zamowienie.opis_rodzaju
        strategies:
          - {use: lookup, dictionary: rodzaje, return: label}
      - path: zamowienie.ma_uwagi
        strategies:
          - {use: derived, if_set: zamowienie.uwagi, value: 1, else: 0}
      - path: zamowienie.waluta
        strategies:
          - {use: const, value: PLN}
      - path: klient
        section: klient
        list_of_blocks: {start: "^\\d\\)"}
        fields:
          - path: nazwa
            strategies:
              - {use: regex, pattern: "^\\d\\)\\s*(?P<v>.+)$"}
          - path: nip
            strategies:
              - {use: regex, pattern: "nip:?\\s*(?P<v>[\\d-]{10,13})"}
            normalize: digits
            validate: nip
    """
)

SCHEMA = {
    "zamowienie": {"data": None, "kwota": None, "rachunek": None, "uwagi": None, "rodzaj": None,
                   "opis_rodzaju": None, "ma_uwagi": None, "waluta": None, "brak": None},
    "klient": [{"nazwa": None, "nip": None}],
}

DICTIONARY = textwrap.dedent(
    """
    entries:
      - {id: 1, label: "Pizza na cienkim cieście", triggers: ["cienkie ciasto", "cienkim cieście"]}
      - {id: 2, label: "Pizza na grubym cieście", triggers: ["grube ciasto"]}
    """
)


def line_words(y, *cells):
    """cells: (x0, text) -> words, each word 6 pt per character."""
    words = []
    for x0, text in cells:
        x = x0
        for tok in text.split():
            words.append(Word(tok, x, y, x + 6 * len(tok), y + 10))
            x += 6 * len(tok) + 4
    return words


def fake_doc():
    lines = [
        line_words(10, (10, "ZAMÓWIENIE PIZZY")),
        line_words(30, (10, "Pizzeria Pod Wezuwiuszem z dnia 15 lipca 2026")),
        line_words(50, (10, "Klient:")),
        line_words(64, (10, "1) Jan Kowalski NIP: 526-000-12-46")),
        line_words(78, (10, "2) Anna Nowak NIP: 1234567890")),
        line_words(92, (10, "Dostawa:")),
        line_words(106, (10, "ul. Długa 1")),
        line_words(130, (10, "Do zapłaty"), (300, "Rachunek odbiorcy")),  # two-row grid: values below
        line_words(144, (10, "1 234,56 zł"), (300, "PL61 1090 1014 0000 0712 1981 2874")),
        line_words(170, (10, "Uwagi")),
        line_words(184, (10, "na cienkim cieście, bez cebuli")),
        line_words(198, (10, "Koniec")),
    ]
    words = [w for ln in lines for w in ln]
    from odw2json.ingest.layout import build_text

    return Document("fake.pdf", [Page(1, 600, 800, words, build_text(words), "text")])


class EngineFakeClassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "zamowienie_pizzy.yaml").write_text(FAKE_RECIPE, encoding="utf-8")
        (d / "zamowienie_pizzy.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        (d / "dictionaries").mkdir()
        (d / "dictionaries" / "rodzaje.yaml").write_text(DICTIONARY, encoding="utf-8")
        self.engine = RecipeEngine(d, dictionaries_dir=d / "dictionaries")

    def tearDown(self):
        self.tmp.cleanup()

    def test_classify_fake_class(self):
        c = self.engine.classify(fake_doc())
        self.assertEqual(c.doc_class, "zamowienie_pizzy")
        self.assertGreaterEqual(c.score, 3)

    def test_reject_unrelated_and_forbidden(self):
        other = Document("x.pdf", [Page(1, 1, 1, [], "Ogłoszenie o zamówieniu\nTED", "text")])
        self.assertIsNone(self.engine.classify(other).doc_class)
        forb = Document("y.pdf", [Page(1, 1, 1, [], "Zamówienie pizzy\nTo nie jest zamówienie", "text")])
        c = self.engine.classify(forb)
        self.assertIsNone(c.doc_class)
        self.assertTrue(c.reason)

    def test_letter_spaced_heading(self):
        doc = Document("z.pdf", [Page(1, 1, 1, [], "Z A M Ó W I E N I E   P I Z Z Y\nPizzeria", "text")])
        self.assertEqual(self.engine.classify(doc).doc_class, "zamowienie_pizzy")

    def test_extract_fake_class(self):
        ext = self.engine.extract(fake_doc(), "zamowienie_pizzy")
        z = ext.data["zamowienie"]
        self.assertEqual(z["data"], "2026-07-15")
        self.assertEqual(z["kwota"], 1234.56)
        self.assertEqual(z["rachunek"], "61109010140000071219812874")
        self.assertEqual(z["uwagi"], "na cienkim cieście, bez cebuli")
        self.assertEqual(z["rodzaj"], 1)
        self.assertEqual(z["opis_rodzaju"], "Pizza na cienkim cieście")
        self.assertEqual(z["ma_uwagi"], 1)
        self.assertEqual(z["waluta"], "PLN")
        self.assertIsNone(z["brak"])  # schema-complete: unknown key present as null
        self.assertEqual([k["nazwa"] for k in ext.data["klient"]], ["Jan Kowalski NIP: 526-000-12-46", "Anna Nowak NIP: 1234567890"])
        self.assertEqual([k["nip"] for k in ext.data["klient"]], ["5260001246", "1234567890"])

    def test_evidence_for_every_value(self):
        ext = self.engine.extract(fake_doc(), "zamowienie_pizzy")
        paths = {e.path: e for e in ext.evidence}
        self.assertIn("zamowienie.kwota", paths)
        self.assertIn("klient[1].nip", paths)
        e = paths["zamowienie.rachunek"]
        self.assertEqual(e.page, 1)
        self.assertEqual(e.rule, "after_label")
        self.assertIsNotNone(e.bbox)
        self.assertGreaterEqual(e.bbox[0], 299)  # the value came from the right column, below the label
        # invalid checksum -> value kept, confidence lowered
        self.assertLess(paths["klient[1].nip"].confidence, 1.0)
        self.assertEqual(paths["klient[0].nip"].confidence, 1.0)

    def test_doc_without_word_boxes(self):
        doc = Document("t.pdf", [Page(1, 1, 1, [], "Zamówienie pizzy\nDo zapłaty: 12,50 zł\nUwagi\nnic\nKoniec", "ocr")])
        ext = self.engine.extract(doc, "zamowienie_pizzy")
        self.assertEqual(ext.data["zamowienie"]["kwota"], 12.5)
        self.assertEqual(ext.data["zamowienie"]["uwagi"], "nic")

    def test_new_yaml_is_picked_up_without_restart(self):
        d = Path(self.tmp.name)
        (d / "inna.yaml").write_text("class: inna\nclassify: {min_score: 1, signals: [{pattern: 'bardzo inna'}]}\nfields: []\n", encoding="utf-8")
        doc = Document("i.pdf", [Page(1, 1, 1, [], "Bardzo inna rzecz", "text")])
        self.assertEqual(self.engine.classify(doc).doc_class, "inna")


class RecipeLoadingTests(unittest.TestCase):
    def test_invalid_recipe_clear_error(self):
        with tempfile.TemporaryDirectory() as t:
            Path(t, "zly.yaml").write_text("class: zly\nclassify: {signals: [{pattern: 3}]}\n", encoding="utf-8")
            with self.assertRaises(RecipeError) as cm:
                load_recipes(t)
            self.assertIn("zly.yaml", str(cm.exception))

    def test_unknown_strategy_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            Path(t, "x.yaml").write_text(
                "class: x\nclassify: {signals: [{pattern: a}]}\nfields: [{path: a, strategies: [{use: magic}]}]\n",
                encoding="utf-8")
            with self.assertRaises(RecipeError):
                load_recipes(t)

    def test_shipped_recipes_load(self):
        recipes = load_recipes(Path(__file__).resolve().parent.parent / "recipes")
        self.assertGreaterEqual(len(recipes), 3)

    def test_factory_defaults_to_engine(self):
        from odw2json import factory

        self.assertIsInstance(factory.default_classifier(), RecipeEngine)
        self.assertIs(factory.default_classifier(), factory.default_extractor())

    def test_shipped_recipes_on_synthetic_docs(self):
        eng = RecipeEngine()
        ted = "364525-2025 - Procedura konkurencyjna See the notice on TED website\nOgłoszenie o zamówieniu\nKrajowa Izba Odwoławcza"
        self.assertIsNone(eng.classify(Document("t.pdf", [Page(1, 1, 1, [], ted, "text")])).doc_class)
        appeal = "Warszawa, dnia 16 czerwca 2025 r.\nPrezes Krajowej Izby Odwoławczej\nOdwołujący: X\nZamawiający: Y\nODWOLANIE"
        c = eng.classify(Document("a.pdf", [Page(1, 1, 1, [], appeal, "ocr")]))
        self.assertEqual(c.doc_class, "odwolanie")
        ext = eng.extract(Document("a.pdf", [Page(1, 1, 1, [], appeal, "ocr")]), "odwolanie")
        self.assertEqual(ext.data["OdwolanieKIO"]["data"], "2025-06-16")
        self.assertEqual(ext.data["OdwolanieKIO"]["miejscowosc"], "Warszawa")
        self.assertLess(ext.evidence[0].confidence, 1.0)  # OCR page


class NormaliserTests(unittest.TestCase):
    def test_date_pl(self):
        f = NORMALISERS["date_pl"]
        self.assertEqual(f("15 lipca 2026"), "2026-07-15")
        self.assertEqual(f("15.07.2026 r."), "2026-07-15")
        self.assertEqual(f("07-07-2026"), "2026-07-07")
        self.assertEqual(f("2026-03-21"), "2026-03-21")
        self.assertEqual(f("1 kwietnia 2026"), "2026-04-01")
        self.assertIsNone(f("32.13.2026"))

    def test_amount_iban_ted_bzp(self):
        self.assertEqual(NORMALISERS["amount_pl"]("1 234,56 zł"), 1234.56)
        self.assertEqual(NORMALISERS["amount_pl"]("200,00 PLN"), 200.0)
        self.assertEqual(NORMALISERS["iban_pl"]("PL47 2692 7374 9064 1859 9264 1235"), "47269273749064185992641235")
        self.assertIsNone(NORMALISERS["iban_pl"]("PL47 2692"))
        self.assertEqual(NORMALISERS["ted"]("2026/S 142-999327"), "999327-2026")
        self.assertEqual(NORMALISERS["ted"]("999137-2026"), "999137-2026")
        self.assertEqual(NORMALISERS["bzp"]("2026/BZP 00999827"), "2026/BZP00999827")

    def test_validators(self):
        self.assertTrue(VALIDATORS["nip"]("5260001246"))
        self.assertFalse(VALIDATORS["nip"]("1234567890"))
        self.assertTrue(VALIDATORS["iban"]("61109010140000071219812874"))
        self.assertFalse(VALIDATORS["iban"]("61109010140000071219812875"))
        self.assertTrue(VALIDATORS["pesel"]("44051401458"))
        self.assertTrue(VALIDATORS["regon"]("123456785"))

    def test_fold(self):
        self.assertEqual(fold("Pełnomocnictwo ŁÓDŹ"), "pelnomocnictwo lodz")
        self.assertEqual(len(fold("Zażółć gęślą")), len("Zażółć gęślą"))
        self.assertEqual(squash(fold("P E Ł N O M O C N I C T W O")), "pelnomocnictwo")


if __name__ == "__main__":
    unittest.main()
