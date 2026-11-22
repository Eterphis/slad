import copy
import unittest

from odw2json.case import apply_case, run_case
from odw2json.case.paths import assign, expand
from odw2json.model import CaseResult, Classification, DocumentResult, Evidence, Extraction

CFG = {
    "low_confidence": 0.6,
    "max_substitutions": 2,
    "confusable": ["0O", "1lI", "5S", "8B", "08"],
    "relations": [
        {"name": "id", "a": {"class": "left", "path": "who[*].nip"}, "b": {"class": "right", "path": "people[*].nip"},
         "compare": "digits", "validator": "nip", "repair": True},
        {"name": "name", "a": {"class": "left", "path": "who[*].name"}, "b": {"class": "right", "path": "people[*].name"},
         "compare": "text"},
        {"name": "title", "a": {"class": "left", "path": "who[*].name"}, "b": {"class": "third", "path": "t.title"},
         "compare": "contains"},
    ],
}
GOOD = "5260250274"  # a valid NIP


def doc(cls, data, evidence=()):
    return DocumentResult("x.pdf", "x.json", Classification(cls, 1.0), Extraction(data, list(evidence)))


class PathTests(unittest.TestCase):
    def test_expand_and_assign(self):
        d = {"a": [{"b": 1}, {"b": 2}], "c": {"d": 3}}
        self.assertEqual(expand(d, "a[*].b"), [("a[0].b", 1), ("a[1].b", 2)])
        self.assertEqual(expand(d, "c.d"), [("c.d", 3)])
        self.assertTrue(assign(d, "a[1].b", 9))
        self.assertEqual(d["a"][1]["b"], 9)
        self.assertFalse(assign(d, "a[5].b", 9))


class CaseTests(unittest.TestCase):
    def test_agreeing_documents(self):
        docs = [doc("left", {"who": [{"nip": GOOD, "name": "Acme sp. z o.o."}]}),
                doc("right", {"people": [{"nip": GOOD, "name": "ACME Sp. z o.o."}]})]
        checks = run_case(docs, CFG)
        self.assertEqual([(c.name, c.ok) for c in checks], [("id", True), ("name", True)])

    def test_disagreement_reported_not_dropped(self):
        docs = [doc("left", {"who": [{"nip": "1111111111", "name": "A"}]}),
                doc("right", {"people": [{"nip": GOOD, "name": "B"}]})]
        before = copy.deepcopy([d.extraction.data for d in docs])
        checks = run_case(docs, CFG)
        self.assertEqual([c.ok for c in checks], [False, False])
        self.assertEqual(before, [d.extraction.data for d in docs])

    def test_single_document_is_a_noop(self):
        docs = [doc("left", {"who": [{"nip": "1234567890", "name": "A"}]})]
        data = copy.deepcopy(docs[0].extraction.data)
        self.assertEqual(run_case(docs, CFG), [])
        self.assertEqual(docs[0].extraction.data, data)

    def test_contains(self):
        docs = [doc("left", {"who": [{"nip": None, "name": "Jan Kowalski"}]}),
                doc("third", {"t": {"title": "oplata od Jan Kowalski dla KIO"}})]
        self.assertEqual([c.ok for c in run_case(docs, CFG)], [True])
        docs[1].extraction.data["t"]["title"] = "oplata dla KIO"
        self.assertEqual([c.ok for c in run_case(docs, CFG)], [False])

    def test_ocr_repair_of_failing_checksum_recorded(self):
        # "8" misread for "0" inside a valid NIP: 5260250274 -> 5268250274? make a 0/8 substitution
        broken = GOOD.replace("0", "8", 1)
        self.assertNotEqual(broken, GOOD)
        docs = [doc("left", {"who": [{"nip": broken, "name": "A"}]}, [Evidence("who[0].nip", broken)]),
                doc("right", {"people": [{"nip": GOOD, "name": "A"}]})]
        checks = run_case(docs, CFG)
        self.assertEqual(docs[0].extraction.data["who"][0]["nip"], GOOD)
        rep = [e for e in docs[0].extraction.evidence if e.rule == "case.repair"]
        self.assertEqual(len(rep), 1)
        self.assertIn(broken, rep[0].snippet)
        self.assertTrue(all(c.ok for c in checks))

    def test_no_repair_when_not_confusable(self):
        other = GOOD[:-1] + "9"  # 4 -> 9 is no OCR confusion
        docs = [doc("left", {"who": [{"nip": other, "name": "A"}]}),
                doc("right", {"people": [{"nip": GOOD, "name": "A"}]})]
        run_case(docs, CFG)
        self.assertEqual(docs[0].extraction.data["who"][0]["nip"], other)

    def test_no_repair_when_both_fail_checksum(self):
        a, b = "1234567890", "1234567898"
        docs = [doc("left", {"who": [{"nip": a, "name": "A"}]}), doc("right", {"people": [{"nip": b, "name": "A"}]})]
        run_case(docs, CFG)
        self.assertEqual(docs[0].extraction.data["who"][0]["nip"], a)
        self.assertEqual(docs[1].extraction.data["people"][0]["nip"], b)

    def test_valid_value_is_never_replaced(self):
        a = GOOD
        b = GOOD.replace("0", "8", 1)
        docs = [doc("left", {"who": [{"nip": a, "name": "A"}]}), doc("right", {"people": [{"nip": b, "name": "A"}]})]
        run_case(docs, CFG)
        self.assertEqual(docs[0].extraction.data["who"][0]["nip"], a)

    def test_apply_case_sets_checks_with_real_config(self):
        res = apply_case(CaseResult("c", [doc("odwolanie", {"Odwolujacy": [{"nip": GOOD}]})]))
        self.assertEqual(res.checks, [])


if __name__ == "__main__":
    unittest.main()


class FuzzyTests(unittest.TestCase):
    def test_contains_fuzzy_and_soft(self):
        from odw2json.case.step import _contains
        self.assertTrue(_contains("Acme Budowa sp. z o.o.", "oplata ACME BUDOWA"))
        self.assertTrue(_contains("2026-03-05", "odwolanie z dnia 05.03.2026"))
        self.assertFalse(_contains("2026-03-05", "odwolanie z dnia 06.03.2026"))
        cfg = {"relations": [{"name": "s", "a": {"class": "left", "path": "x"}, "b": {"class": "third", "path": "y"},
                              "compare": "contains", "soft": True}]}
        docs = [doc("left", {"x": "Foo Bar"}), doc("third", {"y": "nothing"})]
        self.assertIsNone(run_case(docs, cfg)[0].ok)

    def test_rejected_documents_ignored(self):
        rej = DocumentResult("r.pdf", None, Classification(None, 0.0), None)
        self.assertEqual(run_case([rej], CFG), [])
