import unittest

from odw2json.ingest.layout import build_text, is_garbage_text
from odw2json.model import Word


def w(text, x0, y0, x1=None, y1=None):
    return Word(text, x0, y0, x1 if x1 is not None else x0 + 5 * len(text), y1 if y1 is not None else y0 + 10)


class BuildTextTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(build_text([]), "")

    def test_lines_sorted_by_x_and_y(self):
        words = [w("world", 50, 10), w("hello", 0, 10), w("next", 0, 25)]
        self.assertEqual(build_text(words), "hello world\nnext")

    def test_slightly_misaligned_words_share_a_line(self):
        words = [w("a", 0, 10), w("b", 20, 12), w("c", 40, 9)]
        self.assertEqual(build_text(words), "a b c")

    def test_blank_line_between_blocks(self):
        words = [w("one", 0, 10), w("two", 0, 22), w("three", 0, 80)]
        self.assertEqual(build_text(words), "one\ntwo\n\nthree")

    def test_hyphen_join_only_in_text(self):
        words = [w("zamó-", 0, 10), w("wienie", 0, 22)]
        before = list(words)
        self.assertEqual(build_text(words), "zamówienie")
        self.assertEqual(words, before)

    def test_hyphen_not_joined_before_uppercase_or_digit(self):
        words = [w("Kowalski-", 0, 10), w("Nowak", 0, 22), w("A-", 0, 34), w("1", 0, 46)]
        self.assertEqual(build_text(words), "Kowalski-\nNowak\nA-\n1")

    def test_tall_words_do_not_chain_lines(self):
        words = [w("a", 0, 0, 5, 10), w("b", 0, 10.5, 5, 20.5)]
        self.assertEqual(build_text(words), "a\nb")


class GarbageTests(unittest.TestCase):
    def test_empty_and_short(self):
        self.assertTrue(is_garbage_text(""))
        self.assertTrue(is_garbage_text("ab 1"))

    def test_good_text(self):
        self.assertFalse(is_garbage_text("Zamawiający wnosi odwołanie od czynności " * 3))

    def test_rules_and_dotted_lines_are_not_garbage(self):
        txt = "CREDIT MERIDIAN\nPOTWIERDZENIE PRZELEWU\n" + "-" * 80 + "\nKwota: 1 200,00 PLN\n" + "." * 60
        self.assertFalse(is_garbage_text(txt))
        self.assertFalse(is_garbage_text("adw. Leszek Jabłoński\n" + "." * 50))

    def test_replacement_chars(self):
        self.assertTrue(is_garbage_text("\ufffd\ufffd\ufffd\ufffd abc \ufffd\ufffd\ufffd\ufffd " * 10))

    def test_cid_markup(self):
        self.assertTrue(is_garbage_text("(cid:12)(cid:7)(cid:44) " * 20))

    def test_mostly_symbols(self):
        self.assertTrue(is_garbage_text(r"#$%^&*()_+=-[]{}|;:<>/\~ 12 " * 5))


if __name__ == "__main__":
    unittest.main()
