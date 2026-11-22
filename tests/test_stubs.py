import unittest
from pathlib import Path

from odw2json import stubs
from odw2json.model import Document, Page
from tests.uzp_data import UZP


def doc(text):
    return Document("x.pdf", [Page(1, 595, 842, [], text, "text")])


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        self.c = stubs.KeywordClassifier()

    def test_przelew(self):
        r = self.c.classify(doc("Potwierdzenie przelewu\nKwota 100 PLN"))
        self.assertEqual(r.doc_class, "przelew")

    def test_pelnomocnictwo(self):
        r = self.c.classify(doc("PEŁNOMOCNICTWO\nUdzielam pełnomocnictwa"))
        self.assertEqual(r.doc_class, "pelnomocnictwo")

    def test_odwolanie(self):
        r = self.c.classify(doc("Prezes Krajowej Izby Odwoławczej\nOdwołanie wobec czynności"))
        self.assertEqual(r.doc_class, "odwolanie")

    def test_reject(self):
        r = self.c.classify(doc("Przepis na szarlotkę"))
        self.assertIsNone(r.doc_class)


class ExtractorTests(unittest.TestCase):
    def test_skeleton(self):
        e = stubs.SkeletonExtractor().extract(doc(""), "przelew")
        self.assertIsNone(e.data["przelew_bankowy"]["kwota"])


class LetterSpacedTests(unittest.TestCase):
    def test_letter_spaced_heading(self):
        r = stubs.KeywordClassifier().classify(doc("P E Ł N O M O C N I C T W O\nMocodawca X"))
        self.assertEqual(r.doc_class, "pelnomocnictwo")


class TieAndPriorityTests(unittest.TestCase):
    def test_odwolanie_mentioning_pelnomocnictwo(self):
        text = "Lublin, dnia 9 listopada\nPrezes Krajowej Izby Odwoławczej\nOdwołujący: X\nZałączniki: pełnomocnictwo"
        self.assertEqual(stubs.KeywordClassifier().classify(doc(text)).doc_class, "odwolanie")

    def test_przelew_without_potwierdzenie_word(self):
        text = "Bank Przykładowy S.A., oddział w Warszawie\nul. Bankowa 1, 00-001 Warszawa\nwykonano przelew krajowy\nopłata od pełnomocnictwa"
        self.assertEqual(stubs.KeywordClassifier().classify(doc(text)).doc_class, "przelew")


DATA = UZP / "dane"


@unittest.skipUnless(DATA.is_dir(), "UZP training data not available")
class TrainingDataTests(unittest.TestCase):
    def test_class_matches_file_name(self):
        ing, clf = stubs.PdfplumberIngestor(), stubs.KeywordClassifier()
        want = {"odwolanie": "odwolanie", "pelnomocnictwo": "pelnomocnictwo", "potwierdzenie_przelewu": "przelew", "przelew": "przelew"}
        bad = []
        pdfs = sorted(DATA.glob("przyklad_*/*.pdf"))
        self.assertGreaterEqual(len(pdfs), 150)
        for pdf in pdfs:
            got = clf.classify(ing.ingest(str(pdf))).doc_class
            if got != want.get(pdf.stem):
                bad.append(f"{pdf.parent.name}/{pdf.name}: {got}")
        self.assertEqual(bad, [])
