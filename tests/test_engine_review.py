"""Review fixes for the recipe engine (T004): recipe-only classes end to end, loud load errors, evidence paths,
load-time regex validation, label boundaries, Roman-numeral dates, list-preserving _set."""
import contextlib
import io
import json
import os
import re
import tempfile
import textwrap
import unittest
from pathlib import Path

from odw2json import factory, pipeline
from odw2json.cli import main
from odw2json.engine import RecipeEngine, RecipeError
from odw2json.engine.engine import _set, squash_pattern
from odw2json.engine.normalise import NORMALISERS
from odw2json.model import Document, Page
from odw2json.write import complete, fill

RECIPE = textwrap.dedent(
    r"""
    class: notatka
    output_schema: notatka.json
    classify:
      min_score: 1
      signals: [{pattern: "notatka sluzbowa", weight: 1}]
    fields:
      - path: Notatka.tytul
        strategies: [{use: regex, pattern: "temat: (?P<v>.+)"}]
      - path: Strony.nazwa
        strategies: [{use: regex, pattern: "strona: (?P<v>\\w+)"}]
      - path: Lista
        list_of_blocks: {start: "^pozycja"}
        fields:
          - path: kod
            strategies: [{use: regex, pattern: "kod (?P<v>\\d+)"}]
    """
)
SCHEMA = {"Notatka": {"tytul": None}, "Strony": [{"nazwa": None}], "Lista": [{"kod": None}]}
TEXT = "NOTATKA SŁUŻBOWA\ntemat: Pilne\nstrona: Alfa\npozycja 1 kod 11\npozycja 2 kod 22\n"


BAD_RECIPE = "class: zly\nclassify: {signals: [{pattern: 3}]}\n"


def write_recipes(d: Path, recipe=RECIPE, schema=SCHEMA):
    d.mkdir(parents=True, exist_ok=True)
    (d / "notatka.yaml").write_text(recipe, encoding="utf-8")
    if schema is not None:
        (d / "notatka.json").write_text(json.dumps(schema), encoding="utf-8")


def doc(text, source="text"):
    return Document("n.pdf", [Page(1, 1, 1, [], text, source)])


class FakeIngestor:
    def ingest(self, pdf_path):
        return doc(TEXT)


class RecipeOnlyClassTests(unittest.TestCase):
    def test_fill_public_and_alias(self):
        from odw2json import write

        self.assertIs(write._fill, fill)

    def test_complete_without_schema_file_keeps_data(self):
        self.assertEqual(complete({"a": 1}, "no_such_class_xyz"), {"a": 1})

    def test_end_to_end_json_written(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            write_recipes(t / "rec")
            case = t / "in" / "c1"
            case.mkdir(parents=True)
            (case / "a.pdf").write_bytes(b"%PDF-1.4")
            eng = RecipeEngine(t / "rec")
            res = pipeline.process_input(t / "in", t / "out", FakeIngestor(), eng, eng)
            self.assertEqual(res[0].documents[0].warnings, [])
            out = json.loads((t / "out" / "c1" / "a.json").read_text(encoding="utf-8"))
            self.assertEqual(out["Notatka"]["tytul"], "Pilne")
            self.assertEqual(out["Strony"], [{"nazwa": "Alfa"}])


class EvidencePathTests(unittest.TestCase):
    def test_paths_match_output(self):
        with tempfile.TemporaryDirectory() as t:
            write_recipes(Path(t))
            ext = RecipeEngine(t).extract(doc(TEXT), "notatka")
            paths = {e.path for e in ext.evidence}
            self.assertIn("Strony[0].nazwa", paths)
            self.assertIn("Lista[0].kod", paths)
            self.assertIn("Lista[1].kod", paths)
            self.assertIn("Notatka.tytul", paths)
            self.assertEqual(ext.data["Strony"][0]["nazwa"], "Alfa")


class LoudRecipeErrorTests(unittest.TestCase):
    def test_cli_exits_nonzero_with_message(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            write_recipes(t / "rec", recipe="class: zly\nclassify: {signals: [{pattern: 3}]}\n", schema=None)
            (t / "in" / "c").mkdir(parents=True)
            (t / "in" / "c" / "a.pdf").write_bytes(b"%PDF-1.4")
            old = os.environ.get("ODW2JSON_RECIPES")
            factory.recipe_engine.cache_clear()
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err):
                    rc = main(["--input", str(t / "in"), "--output", str(t / "out"), "--recipes", str(t / "rec")])
            finally:
                factory.recipe_engine.cache_clear()
                if old is None:
                    os.environ.pop("ODW2JSON_RECIPES", None)
                else:
                    os.environ["ODW2JSON_RECIPES"] = old
            self.assertNotEqual(rc, 0)
            self.assertIn("notatka.yaml", err.getvalue())
            self.assertFalse((t / "out" / "c").exists())

    def test_runtime_break_is_per_document_error(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            write_recipes(t / "rec")
            case = t / "in" / "c"
            case.mkdir(parents=True)
            (case / "a.pdf").write_bytes(b"%PDF-1.4")
            eng = RecipeEngine(t / "rec")
            eng.recipes  # loaded fine
            (t / "rec" / "notatka.yaml").write_text("class: [broken", encoding="utf-8")
            res = pipeline.process_case(case, FakeIngestor(), eng, eng)
            self.assertIn("notatka.yaml", res.documents[0].warnings[0])


class WebBrokenRecipeTests(unittest.TestCase):
    def test_web_returns_recipe_message(self):
        from fastapi.testclient import TestClient

        from web import app as webapp

        with tempfile.TemporaryDirectory() as t:
            write_recipes(Path(t), recipe=BAD_RECIPE, schema=None)
            old = os.environ.get("ODW2JSON_RECIPES")
            os.environ["ODW2JSON_RECIPES"] = t
            factory.recipe_engine.cache_clear()
            try:
                r = TestClient(webapp.app).post("/api/process", files=[("files", ("a.pdf", b"%PDF-1.4 x", "application/pdf"))])
            finally:
                factory.recipe_engine.cache_clear()
                if old is None:
                    os.environ.pop("ODW2JSON_RECIPES", None)
                else:
                    os.environ["ODW2JSON_RECIPES"] = old
        self.assertEqual(r.status_code, 500)
        self.assertIn("notatka.yaml", r.json()["detail"])


class LoadTimeValidationTests(unittest.TestCase):
    def _load(self, strategy, dictionary=None):
        recipe = "class: x\nclassify: {signals: [{pattern: a}]}\nfields:\n  - path: a\n    strategies: [%s]\n" % strategy
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "x.yaml").write_text(recipe, encoding="utf-8")
            (t / "dicts").mkdir()
            if dictionary:
                (t / "dicts" / "d.yaml").write_text(dictionary, encoding="utf-8")
            return RecipeEngine(t, dictionaries_dir=t / "dicts").recipes

    def test_bad_after_label_value(self):
        with self.assertRaises(RecipeError) as cm:
            self._load("{use: after_label, labels: [a], value: '(['}")
        self.assertIn("value", str(cm.exception))

    def test_bad_squash_signal(self):
        with tempfile.TemporaryDirectory() as t:
            Path(t, "x.yaml").write_text("class: x\nclassify: {signals: [{pattern: '(a', squash: true}]}\n", encoding="utf-8")
            with self.assertRaises(RecipeError):
                RecipeEngine(t).recipes

    def test_bad_dictionary_trigger(self):
        with self.assertRaises(RecipeError) as cm:
            self._load("{use: lookup, dictionary: d}", "entries:\n  - {id: 1, label: a, triggers: ['(oops']}\n")
        self.assertIn("trigger", str(cm.exception))

    def test_missing_dictionary_fails_at_load(self):
        with self.assertRaises(RecipeError):
            self._load("{use: lookup, dictionary: nie_ma}")

    def test_squash_pattern_keeps_classes_and_quantifier_sense(self):
        for pat in [r"[^\s]+ abc", r"a\s{1,3}b", r"a\s+b c", r"x[ ]y\s*?z", r"odwo[lł]anie\s+od"]:
            re.compile(squash_pattern(pat))
        self.assertEqual(squash_pattern(r"a\s+b c"), "abc")
        self.assertEqual(squash_pattern(r"a\s{1,3}b"), "ab")
        self.assertEqual(squash_pattern(r"[^\s]x y"), r"[^\s]xy")
        self.assertEqual(squash_pattern(r"x[ ]y"), "x[ ]y")


class LabelBoundaryTests(unittest.TestCase):
    def test_no_mid_word_label_without_boxes(self):
        recipe = textwrap.dedent(
            r"""
            class: x
            classify: {signals: [{pattern: a}]}
            fields:
              - path: nr
                strategies: [{use: after_label, labels: ['nr ref\.?'], value: '[a-z0-9]{4,}'}]
            """
        )
        with tempfile.TemporaryDirectory() as t:
            Path(t, "x.yaml").write_text(recipe, encoding="utf-8")
            e = RecipeEngine(t)
            ext = e.extract(doc("a\nNr referencyjny: ABC123\n"), "x")
            self.assertNotEqual(ext.data.get("nr"), "erencyjny")
            ext = e.extract(doc("a\nNr ref.: ABC123\n"), "x")
            self.assertEqual(ext.data["nr"], "ABC123")


class DateRomanTests(unittest.TestCase):
    def test_roman_months(self):
        f = NORMALISERS["date_pl"]
        self.assertEqual(f("12.III.2024"), "2024-03-12")
        self.assertEqual(f("12 III 2024"), "2024-03-12")
        self.assertEqual(f("5. xii. 2023"), "2023-12-05")


class SetTests(unittest.TestCase):
    def test_empty_list_stays_list(self):
        obj = {"L": []}
        _set(obj, "L.x", 1)
        self.assertIsInstance(obj["L"], list)
        self.assertEqual(obj["L"], [{"x": 1}])


if __name__ == "__main__":
    unittest.main()
