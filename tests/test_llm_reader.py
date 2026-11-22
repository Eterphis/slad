"""Local-LLM reader (T016): grounding, merge policy, plan from recipe, extractor wiring. A fake runtime stands in for
the model, so no weights are needed; class names appear here only as test data."""
import json
import tempfile
import unittest
from pathlib import Path

from odw2json.engine import RecipeEngine
from odw2json.llm import LlmExtractor, LlmReader, RuntimeUnavailable
from odw2json.llm.grounding import PageText, contains_value, skeleton
from odw2json.llm.plan import build_plan
from odw2json.llm.prompt import group_key
from odw2json.llm.reader import get_path, set_path
from odw2json.model import Document, Evidence, Extraction, Page

RECIPE = """
class: letter
classify: {min_score: 1, signals: [{pattern: "letter"}]}
fields:
  - path: sender
    strategies: [{use: regex, pattern: "^from: (?P<v>.+)$"}]
    llm: {question: "Who sends the letter?", hint: "A company or a person.", override: true}
  - path: reference
    strategies: [{use: regex, pattern: "^ref: (?P<v>\\\\S+)$"}]
llm:
  fields:
    - {path: tax_id, question: "Tax number as printed", normalize: digits, validate: nip}
    - {path: kind, type: integer, question: "Kind of letter", choices: {dictionary: kinds}}
  groups:
    - path: people
      question: "People named in the letter."
      key: name
      when: "pesel"
      fields:
        - {path: name, question: "Full name"}
        - {path: pesel, question: "PESEL", validate: pesel}
"""
KINDS = "entries:\n  - {id: 1, label: Complaint, triggers: ['complaint']}\n  - {id: 2, label: Thanks, triggers: ['thanks']}\n"


class Fake:
    name = "fake-1b"

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def complete(self, system, user, schema, max_tokens=700):
        self.calls.append((user, schema))
        a = self.answer(user) if callable(self.answer) else self.answer
        return a if isinstance(a, str) else json.dumps(a)


def doc(*pages):
    return Document("x.pdf", [Page(i + 1, 600, 800, [], t, "ocr") for i, t in enumerate(pages)])


def v(value, quote):
    return {"value": value, "quote": quote}


class Grounding(unittest.TestCase):
    def test_skeleton_folds_letters_and_digits(self):
        self.assertEqual(skeleton("Łódź, ul. Ząb 5/2"), "lodzulzab52")

    def test_quote_found_across_line_breaks_and_diacritics(self):
        pt = PageText([(1, "Odwołujący:\nMedicor IT\nSolutions S.A.")])
        f = pt.find("odwolujacy: medicor it solutions")
        self.assertEqual(f.page, 1)
        self.assertIn("Medicor IT\nSolutions", f.snippet)

    def test_invented_or_short_quote_is_not_found(self):
        pt = PageText([(1, "abc def ghi")])
        self.assertIsNone(pt.find("something else entirely"))
        self.assertIsNone(pt.find("ab"))
        self.assertIsNone(pt.find(None))

    def test_value_must_be_inside_its_quote(self):
        self.assertTrue(contains_value("NIP: 999-232-67-54", "9992326754"))
        self.assertFalse(contains_value("NIP: 999-232-67-54", "1234567890"))


class Paths(unittest.TestCase):
    def test_get_set_with_indexes(self):
        d = {"a": [{"b": None}]}
        set_path(d, "a[0].b", 5)
        set_path(d, "c[1].d", "x")
        self.assertEqual(d, {"a": [{"b": 5}], "c": [None, {"d": "x"}]})
        self.assertEqual(get_path(d, "a[0].b"), 5)
        self.assertIsNone(get_path(d, "a[3].b"))


class Reader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = Path(self.tmp.name)
        (r / "recipes").mkdir()
        (r / "dict").mkdir()
        (r / "recipes" / "letter.yaml").write_text(RECIPE, encoding="utf-8")
        (r / "dict" / "kinds.yaml").write_text(KINDS, encoding="utf-8")
        self.engine = RecipeEngine(r / "recipes", r / "dict")
        self.plan = build_plan(self.engine.recipes["letter"].spec, self.engine.dictionary)

    def tearDown(self):
        self.tmp.cleanup()

    def ext(self, **data):
        base = {"sender": None, "reference": None, "tax_id": None, "kind": None, "people": [{"name": None, "pesel": None}]}
        base.update(data)
        return Extraction(base, [Evidence(k, x, 1, None, "regex", c) for k, (x, c) in {"sender": (data.get("sender"), 0.9)}.items() if x])

    def test_plan_collects_field_class_level_fields_groups_and_choices(self):
        paths = [f.path for f in self.plan.fields]
        self.assertEqual(paths, ["sender", "tax_id", "kind"])
        self.assertTrue(self.plan.fields[0].override)
        self.assertEqual([c["id"] for c in self.plan.fields[2].choices], [1, 2])
        self.assertEqual(self.plan.groups[0].key, "name")

    def test_fills_null_with_grounded_normalised_value(self):
        d = doc("letter\nTax: 999-232-67-54\nfrom Acme")
        rt = Fake({"sender": v("Acme", "from Acme"), "tax_id": v("999-232-67-54", "Tax: 999-232-67-54"), "kind": v(None, None), "people": []})
        ext = self.ext()
        LlmReader(rt).read(d, ext, self.plan)
        self.assertEqual(ext.data["sender"], "Acme")
        self.assertEqual(ext.data["tax_id"], "9992326754")
        ev = {e.path: e for e in ext.evidence}
        self.assertEqual(ev["tax_id"].rule, "llm:fake-1b")
        self.assertIn("999-232-67-54", ev["tax_id"].snippet)
        self.assertLess(ev["tax_id"].confidence, 1.0)

    def test_ungrounded_quote_is_dropped(self):
        d = doc("letter\nfrom Acme")
        rt = Fake({"sender": v("Globex", "sent by Globex Corporation"), "tax_id": v(None, None), "kind": v(None, None), "people": []})
        ext = self.ext()
        dec = LlmReader(rt).read(d, ext, self.plan)
        self.assertIsNone(ext.data["sender"])
        self.assertEqual({x.path: x.status for x in dec}["sender"], "ungrounded")

    def test_value_missing_from_its_own_quote_is_dropped(self):
        d = doc("letter\nfrom Acme")
        rt = Fake({"sender": v("Globex", "from Acme"), "tax_id": v(None, None), "kind": v(None, None), "people": []})
        ext = self.ext()
        LlmReader(rt).read(d, ext, self.plan)
        self.assertIsNone(ext.data["sender"])

    def test_never_overrides_full_confidence_value(self):
        d = doc("letter\nfrom Acme\nkind complaint")
        rt = Fake(lambda u: {"tax_id": v(None, None), "kind": v(1, "kind complaint")})
        ext = Extraction({"sender": "Real Ltd", "reference": None, "tax_id": None, "kind": 2, "people": [{"name": None, "pesel": None}]},
                         [Evidence("kind", 2, 1, None, "lookup", 1.0), Evidence("sender", "Real Ltd", 1, None, "regex", 1.0)])
        dec = LlmReader(rt).read(d, ext, self.plan)
        self.assertEqual(ext.data["kind"], 2)  # confident recipe value stays
        self.assertEqual(ext.data["sender"], "Real Ltd")
        self.assertEqual(len(rt.calls), 1)
        self.assertNotIn("kind", [x.path for x in dec])  # not even asked

    def test_override_field_replaces_ocr_confidence_value_only(self):
        d = doc("letter\nfrom Acme Ltd")
        rt = Fake({"sender": v("Acme Ltd", "from Acme Ltd")})
        ext = Extraction({"sender": "Acm", "reference": None, "tax_id": "9992326754", "kind": 1, "people": [{"name": None, "pesel": None}]},
                         [Evidence("sender", "Acm", 1, None, "regex", 0.9)])
        dec = LlmReader(rt).read(d, ext, self.plan)
        self.assertEqual(ext.data["sender"], "Acme Ltd")
        self.assertEqual(dec[0].status, "replaced")
        self.assertEqual(ext.data["tax_id"], "9992326754")

    def test_invalid_checksum_is_kept_only_as_low_confidence_proposal(self):
        d = doc("letter\nTax 123-456-78-90")
        rt = Fake({"sender": v(None, None), "tax_id": v("123-456-78-90", "Tax 123-456-78-90"), "kind": v(None, None), "people": []})
        ext = self.ext()
        LlmReader(rt).read(d, ext, self.plan)
        e = {e.path: e for e in ext.evidence}["tax_id"]
        self.assertEqual(ext.data["tax_id"], "1234567890")
        self.assertLess(e.confidence, 0.5)

    def test_choice_needs_a_known_id_and_a_grounded_quote(self):
        d = doc("letter\nthis is a complaint")
        ok = self.ext()
        LlmReader(Fake({"sender": v(None, None), "tax_id": v(None, None), "kind": v(1, "this is a complaint"), "people": []})).read(d, ok, self.plan)
        self.assertEqual(ok.data["kind"], 1)
        bad = self.ext()
        LlmReader(Fake({"sender": v(None, None), "tax_id": v(None, None), "kind": v(7, "this is a complaint"), "people": []})).read(d, bad, self.plan)
        self.assertIsNone(bad.data["kind"])

    def test_group_when_pattern_skips_the_call(self):
        d = doc("letter\nfrom Acme")
        rt = Fake({"sender": v(None, None), "tax_id": v(None, None), "kind": v(None, None)})
        LlmReader(rt).read(d, self.ext(), self.plan)
        self.assertNotIn(group_key(self.plan.groups[0]), rt.calls[0][1]["properties"])

    def test_group_fills_free_slot_and_aligns_by_key(self):
        d = doc("letter PESEL\nAnna Nowak, PESEL 44051401359\nJan Kos")
        answer = {"sender": v(None, None), "tax_id": v(None, None), "kind": v(None, None),
                  "people": [{"name": v("Anna Nowak", "Anna Nowak, PESEL"), "pesel": v("44051401359", "PESEL 44051401359")}]}
        ext = self.ext()
        LlmReader(Fake(answer)).read(d, ext, self.plan)
        self.assertEqual(ext.data["people"][0], {"name": "Anna Nowak", "pesel": "44051401359"})
        # recipe already found Anna: the pesel joins her item, an extra person is not added
        answer["people"].append({"name": v("Jan Kos", "Jan Kos"), "pesel": v(None, None)})
        ext2 = self.ext(people=[{"name": "Anna Nowak", "pesel": None}])
        dec = LlmReader(Fake(answer)).read(d, ext2, self.plan)
        self.assertEqual(ext2.data["people"], [{"name": "Anna Nowak", "pesel": "44051401359"}])
        self.assertTrue(any(x.status == "kept" for x in dec))

    def test_unreadable_answer_changes_nothing(self):
        ext = self.ext()
        dec = LlmReader(Fake("not json")).read(doc("letter"), ext, self.plan)
        self.assertEqual(ext.data["sender"], None)
        self.assertTrue(all(x.status == "no_answer" for x in dec))

    def test_nothing_to_ask_means_no_model_call(self):
        rt = Fake({})
        ext = Extraction({"sender": "A", "reference": None, "tax_id": "9992326754", "kind": 1, "people": [{"name": "A", "pesel": "44051401359"}]},
                        [Evidence("sender", "A", 1, None, "regex", 1.0)])
        LlmReader(rt).read(doc("letter pesel"), ext, self.plan)
        self.assertEqual(rt.calls, [])


class Extractor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = Path(self.tmp.name)
        (r / "recipes").mkdir()
        (r / "dict").mkdir()
        (r / "recipes" / "letter.yaml").write_text(RECIPE, encoding="utf-8")
        (r / "dict" / "kinds.yaml").write_text(KINDS, encoding="utf-8")
        self.engine = RecipeEngine(r / "recipes", r / "dict")

    def tearDown(self):
        self.tmp.cleanup()

    def test_extract_adds_llm_value_and_classify_is_the_engines(self):
        d = doc("letter\nfrom: Acme\nthis is a complaint")
        x = LlmExtractor(self.engine, Fake({"tax_id": v(None, None), "kind": v(1, "this is a complaint")}))
        self.assertEqual(x.classify(d).doc_class, "letter")
        out = x.extract(d, "letter")
        self.assertEqual(out.data["sender"], "Acme")
        self.assertEqual(out.data["kind"], 1)

    def test_missing_model_keeps_recipe_output(self):
        class Gone:
            name = "gone"

            def complete(self, *a, **k):
                raise RuntimeUnavailable("no weights")

        x = LlmExtractor(self.engine, Gone())
        out = x.extract(doc("letter\nfrom: Acme"), "letter")
        self.assertEqual(out.data["sender"], "Acme")
        self.assertIsNone(out.data.get("kind"))
        x.extract(doc("letter\nfrom: Acme"), "letter")  # disabled after the first failure, no exception


class Profile(unittest.TestCase):
    def test_shipped_llm_profile_loads_and_names_a_known_model(self):
        from odw2json import profiles
        from odw2json.llm.fetch import MODELS

        prof = profiles.load_profile("llm")
        self.assertEqual(prof.reader["kind"], "llm")
        self.assertIn(Path(prof.reader["model"]).name, [m[1] for m in MODELS.values()])

    def test_every_listed_model_has_a_permissive_licence(self):
        from odw2json.llm.fetch import MODELS

        self.assertTrue(all(m[4] in ("Apache-2.0", "MIT") for m in MODELS.values()))

    def test_ensure_model_never_raises_and_respects_fetch_false(self):
        from odw2json.llm.fetch import ensure_model

        ensure_model({"kind": "llm", "model": "models/not-a-known-model.gguf"})
        ensure_model({"kind": "llm", "model": "models/Qwen3-1.7B-Q8_0.gguf", "fetch": False})


if __name__ == "__main__":
    unittest.main()
