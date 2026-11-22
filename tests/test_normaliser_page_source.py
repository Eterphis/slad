"""Page-source-aware normalisers: `iban_pl_as_printed` keeps a printed PL prefix on OCR pages only."""
import unittest

from odw2json.engine.normalise import NORMALISERS, PAGE_AWARE, VALIDATORS

IBAN = "PL62 2170 0008 9152 5017 5661 7062"
DIGITS = "62217000089152501756617062"


class PageAwareNormaliserTests(unittest.TestCase):
    def setUp(self):
        self.f = NORMALISERS["iban_pl_as_printed"]

    def test_registered_as_page_aware(self):
        self.assertIn("iban_pl_as_printed", PAGE_AWARE)
        self.assertNotIn("iban_pl", PAGE_AWARE)

    def test_text_page_gives_digits(self):
        self.assertEqual(self.f(IBAN, "text"), DIGITS)
        self.assertEqual(self.f(IBAN, None), DIGITS)

    def test_ocr_page_with_prefix_keeps_it(self):
        self.assertEqual(self.f(IBAN, "ocr"), "PL" + DIGITS)
        self.assertEqual(self.f(IBAN.lower(), "ocr"), "PL" + DIGITS)

    def test_ocr_page_without_prefix_gives_digits(self):
        self.assertEqual(self.f(IBAN[2:], "ocr"), DIGITS)

    def test_wrong_length_rejected(self):
        self.assertIsNone(self.f("PL62 2170", "ocr"))

    def test_iban_validator_accepts_prefixed_value(self):
        self.assertTrue(VALIDATORS["iban"]("PL" + DIGITS))


if __name__ == "__main__":
    unittest.main()
