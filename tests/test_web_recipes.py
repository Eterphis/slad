"""Document classes from the web UI: validate, try, save (.bak), delete, read-only switch, hot reload."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from odw2json import factory
from odw2json.engine.recipes import check_recipe_text
from odw2json.pipeline import process_case
from web import app as webapp
from web import recipes_api
from tests.uzp_data import UZP

ROOT = Path(__file__).resolve().parents[1]
DATA = UZP / "dane" / "przyklad_07"

WEZWANIE = """class: wezwanie
description: Wezwanie do zapłaty
output_schema: wezwanie.output.json
classify:
  min_score: 3
  margin: 1
  signals:
    - {pattern: "wezwanie do zaplaty", weight: 3, head: 400, squash: true}
fields:
  - path: wezwanie.kwota
    strategies:
      - {use: after_label, labels: ["kwota( do zaplaty)?"], value: "\\\\d[\\\\d .]*,\\\\d{2}"}
    normalize: amount_pl
  - path: wezwanie.termin
    strategies:
      - {use: after_label, labels: ["termin platnosci"]}
    normalize: date_pl
"""
SKELETON = '{"wezwanie": {"kwota": null, "termin": null}}'


def make_pdf(lines: list[str]) -> bytes:
    """A one-page text-layer PDF without any library (Helvetica, ASCII only)."""
    content = "BT /F1 12 Tf 14 TL 50 780 Td " + " T* ".join(f"({ln}) Tj" for ln in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


WEZWANIE_PDF = make_pdf(["WEZWANIE DO ZAPLATY", "Kwota do zaplaty: 1 234,50 zl", "Termin platnosci: 2026-12-01"])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="recipes_test_"))
        self.rdir = self.tmp / "recipes"
        shutil.copytree(ROOT / "recipes", self.rdir, ignore=shutil.ignore_patterns("*.bak", "_template*"))
        self._env = {k: os.environ.get(k) for k in ("ODW2JSON_RECIPES", "ODW2JSON_READONLY_RECIPES")}
        os.environ["ODW2JSON_RECIPES"] = str(self.rdir)
        os.environ.pop("ODW2JSON_READONLY_RECIPES", None)
        factory.recipe_engine.cache_clear()
        self.client = TestClient(webapp.app)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        factory.recipe_engine.cache_clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, name="wezwanie", text=WEZWANIE, schema=SKELETON):
        return self.client.put(f"/api/recipes/{name}", json={"text": text, "output_schema": schema})


class ValidateTextTests(unittest.TestCase):
    def test_template_is_valid(self):
        spec, errors = check_recipe_text((ROOT / "recipes" / "_template.yaml.example").read_text(encoding="utf-8"))
        self.assertEqual(errors, [])
        self.assertEqual(spec["class"], "nowa_klasa")

    def test_bad_regex_has_path_and_line(self):
        _, errors = check_recipe_text(WEZWANIE.replace("kwota( do zaplaty)?", "kwota(( do zaplaty"))
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["path"], "fields/0/strategies/0/labels")
        self.assertEqual(errors[0]["line"], 12)
        self.assertIn("bad regex", errors[0]["message"])

    def test_yaml_error_has_line(self):
        _, errors = check_recipe_text("class: x\nclassify: [\n")
        self.assertEqual(errors[0]["path"], "(yaml)")
        self.assertIsNotNone(errors[0]["line"])

    def test_schema_errors_unknown_names(self):
        _, errors = check_recipe_text(WEZWANIE.replace("normalize: amount_pl", "normalize: nope"))
        self.assertEqual(errors[0]["path"], "fields/0/normalize")
        _, errors = check_recipe_text(WEZWANIE.replace("signals:", "sygnaly:"))
        self.assertTrue(errors)
        _, errors = check_recipe_text("class: a b\nclassify: {signals: [{pattern: x}]}\n")
        self.assertEqual(errors[0]["path"], "class")

    def test_missing_dictionary_is_an_error(self):
        t = WEZWANIE.replace("{use: after_label, labels: [\"termin platnosci\"]}", "{use: lookup, dictionary: brak_takiego}")
        _, errors = check_recipe_text(t)
        self.assertEqual(errors[0]["path"], "fields/1/strategies/0/dictionary")


class ApiTests(Base):
    def test_list_has_field_counts_and_flags(self):
        j = self.client.get("/api/recipes").json()
        self.assertIn("odwolanie", j["classes"])
        by = {r["name"]: r for r in j["recipes"]}
        self.assertGreater(by["przelew"]["fields"], 3)
        self.assertTrue(by["przelew"]["protected"])
        self.assertFalse(j["readonly"])

    def test_template_endpoint(self):
        j = self.client.get("/api/recipe-template").json()
        self.assertIn("class: nowa_klasa", j["text"])
        self.assertEqual(json.loads(j["output_schema"]), {"wezwanie": {"kwota": None, "termin": None}})
        self.assertTrue(self.client.post("/api/recipes/validate", json=j).json()["ok"])

    def test_read_returns_text_schema_dictionaries(self):
        j = self.client.get("/api/recipes/odwolanie").json()
        self.assertIn("class: odwolanie", j["text"])
        self.assertIsInstance(j["dictionaries"], list)
        self.assertIn("czynnosc_powod", j["dictionaries"])
        self.assertTrue(j["protected"])
        self.assertEqual(self.client.get("/api/recipes/nie_ma").status_code, 404)

    def test_validate_ok_and_errors(self):
        ok = self.client.post("/api/recipes/validate", json={"text": WEZWANIE, "output_schema": SKELETON}).json()
        self.assertTrue(ok["ok"])
        self.assertEqual((ok["class"], ok["fields"]), ("wezwanie", 2))
        bad = self.client.post("/api/recipes/validate", json={"text": WEZWANIE.replace("( do zaplaty)?", "( do zaplaty"), "output_schema": SKELETON}).json()
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["errors"][0]["line"], 12)

    def test_validate_needs_schema_file_or_text(self):
        j = self.client.post("/api/recipes/validate", json={"text": WEZWANIE}).json()
        self.assertFalse(j["ok"])
        self.assertEqual(j["errors"][0]["path"], "output_schema")
        j = self.client.post("/api/recipes/validate", json={"text": WEZWANIE, "output_schema": "{nope"}).json()
        self.assertFalse(j["ok"])

    def test_skeleton_from_fields(self):
        j = self.client.post("/api/recipes/skeleton", json={"text": WEZWANIE}).json()
        self.assertEqual(json.loads(j["output_schema"]), json.loads(SKELETON))

    def test_name_validation(self):
        for bad in ("A", "1abc", "a-b", "x", "a" * 42, "ab.c", "%2e%2e"):
            r = self.put(bad)
            self.assertIn(r.status_code, (404, 405, 422), bad)
        self.assertEqual(self.put("Wezwanie").status_code, 422)
        self.assertFalse(list(self.rdir.glob("wezwanie*")))

    def test_put_name_must_match_class(self):
        r = self.put("inna")
        self.assertEqual(r.status_code, 422)
        self.assertIn("musi być taka jak nazwa pliku", json.dumps(r.json(), ensure_ascii=False))

    def test_put_invalid_writes_nothing(self):
        r = self.put(text=WEZWANIE.replace("( do zaplaty)?", "( do zaplaty"))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["errors"][0]["line"], 12)
        self.assertFalse((self.rdir / "wezwanie.yaml").exists())

    def test_put_creates_then_bak_on_overwrite(self):
        r = self.put()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["created"])
        self.assertTrue((self.rdir / "wezwanie.yaml").is_file())
        self.assertEqual(json.loads((self.rdir / "wezwanie.output.json").read_text(encoding="utf-8")), json.loads(SKELETON))
        self.assertFalse((self.rdir / "wezwanie.yaml.bak").exists())
        newer = WEZWANIE.replace("min_score: 3", "min_score: 2")
        r = self.put(text=newer)
        self.assertFalse(r.json()["created"])
        self.assertEqual((self.rdir / "wezwanie.yaml.bak").read_text(encoding="utf-8"), WEZWANIE)
        self.assertIn("min_score: 2", (self.rdir / "wezwanie.yaml").read_text(encoding="utf-8"))
        self.assertEqual(list(self.rdir.glob("*.tmp")), [])
        self.assertEqual(self.client.get("/api/recipes/wezwanie").json()["output_schema"]["file"], "wezwanie.output.json")

    def test_delete_refuses_uzp_classes_unless_force(self):
        for n in ("odwolanie", "pelnomocnictwo", "przelew"):
            r = self.client.delete(f"/api/recipes/{n}")
            self.assertEqual(r.status_code, 409, n)
            self.assertTrue((self.rdir / f"{n}.yaml").exists())
        self.assertEqual(self.client.delete("/api/recipes/przelew", params={"force": "true"}).status_code, 200)
        self.assertFalse((self.rdir / "przelew.yaml").exists())
        self.assertTrue((self.rdir / "przelew.yaml.bak").exists())

    def test_delete_custom_class_and_404(self):
        self.put()
        r = self.client.delete("/api/recipes/wezwanie")
        self.assertEqual(r.status_code, 200)
        self.assertFalse((self.rdir / "wezwanie.yaml").exists())
        self.assertEqual(self.client.delete("/api/recipes/wezwanie").status_code, 404)
        self.assertNotIn("wezwanie", [x["name"] for x in self.client.get("/api/recipes").json()["recipes"]])

    def test_readonly_switch_blocks_writes_not_reads(self):
        os.environ["ODW2JSON_READONLY_RECIPES"] = "1"
        r = self.put()
        self.assertEqual(r.status_code, 403)
        self.assertIn("tylko do odczytu", r.json()["detail"])
        self.assertEqual(self.client.delete("/api/recipes/przelew", params={"force": "true"}).status_code, 403)
        self.assertTrue((self.rdir / "przelew.yaml").exists())
        self.assertFalse((self.rdir / "wezwanie.yaml").exists())
        self.assertTrue(self.client.get("/api/recipes").json()["readonly"])
        self.assertEqual(self.client.get("/api/recipes/odwolanie").status_code, 200)
        self.assertEqual(self.client.post("/api/recipes/validate", json={"text": WEZWANIE, "output_schema": SKELETON}).status_code, 200)

    def test_try_does_not_save_and_shows_scores_and_evidence(self):
        before = sorted(p.name for p in self.rdir.iterdir())
        r = self.client.post("/api/recipes/try", data={"text": WEZWANIE, "output_schema": SKELETON},
                             files=[("files", ("wezwanie.pdf", WEZWANIE_PDF, "application/pdf"))])
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()["documents"][0]
        self.assertTrue(d["matched"])
        self.assertEqual(d["classification"]["doc_class"], "wezwanie")
        self.assertIn("wezwanie", d["classification"]["scores"])
        self.assertIn("odwolanie", d["classification"]["scores"])
        self.assertEqual(d["data"], {"wezwanie": {"kwota": 1234.5, "termin": "2026-12-01"}})
        self.assertEqual({e["path"] for e in d["evidence"]}, {"wezwanie.kwota", "wezwanie.termin"})
        self.assertEqual(sorted(p.name for p in self.rdir.iterdir()), before)

    def test_try_invalid_recipe_is_422_with_errors(self):
        r = self.client.post("/api/recipes/try", data={"text": WEZWANIE.replace("( do zaplaty)?", "( do zaplaty"), "output_schema": SKELETON},
                             files=[("files", ("a.pdf", WEZWANIE_PDF, "application/pdf"))])
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["errors"][0]["line"], 12)

    def test_try_edited_saved_class_replaces_it(self):
        self.put()
        edited = WEZWANIE.replace("min_score: 3", "min_score: 99")
        r = self.client.post("/api/recipes/try", data={"text": edited, "output_schema": SKELETON},
                             files=[("files", ("a.pdf", WEZWANIE_PDF, "application/pdf"))])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["documents"][0]["matched"])  # the draft (min_score 99), not the saved version, was used

    @unittest.skipUnless(DATA.exists(), "uzp-data missing")
    def test_try_real_pdf_shows_all_classes(self):
        r = self.client.post("/api/recipes/try", data={"text": WEZWANIE, "output_schema": SKELETON},
                             files=[("files", ("odwolanie.pdf", (DATA / "odwolanie.pdf").read_bytes(), "application/pdf"))])
        d = r.json()["documents"][0]
        self.assertEqual(d["classification"]["doc_class"], "odwolanie")
        self.assertFalse(d["matched"])
        self.assertEqual(set(d["classification"]["scores"]), {"odwolanie", "pelnomocnictwo", "przelew", "wezwanie"})


class HotReloadTests(Base):
    def case_dir(self, name="sprawa"):
        d = self.tmp / "input" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "wezwanie.pdf").write_bytes(WEZWANIE_PDF)
        return d

    def test_class_created_via_put_is_used_without_restart(self):
        case = self.case_dir()
        self.assertEqual(self.client.get("/api/recipes").status_code, 200)
        before = process_case(case).documents[0]  # engine already loaded
        self.assertIsNone(before.classification.doc_class)
        self.assertEqual(self.put().status_code, 200)
        after = process_case(case).documents[0]
        self.assertEqual(after.classification.doc_class, "wezwanie")
        self.assertEqual(after.extraction.data, {"wezwanie": {"kwota": 1234.5, "termin": "2026-12-01"}})
        # the web upload route sees it too
        r = self.client.post("/api/process", files=[("files", ("wezwanie.pdf", WEZWANIE_PDF, "application/pdf"))])
        self.assertEqual(r.json()["documents"][0]["classification"]["doc_class"], "wezwanie")
        # and deleting removes it again
        self.assertEqual(self.client.delete("/api/recipes/wezwanie").status_code, 200)
        self.assertIsNone(process_case(case).documents[0].classification.doc_class)

    def test_cli_uses_class_saved_through_the_api(self):
        self.case_dir()
        self.put()
        out = self.tmp / "output"
        env = {**os.environ, "ODW2JSON_RECIPES": str(self.rdir)}
        p = subprocess.run([sys.executable, "-m", "odw2json", "--input", str(self.tmp / "input"), "--output", str(out)],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads((out / "sprawa" / "wezwanie.json").read_text(encoding="utf-8"))
        self.assertEqual(data, {"wezwanie": {"kwota": 1234.5, "termin": "2026-12-01"}})


if __name__ == "__main__":
    unittest.main()
