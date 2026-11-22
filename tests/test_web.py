import io
import json
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from odw2json.model import CaseResult, Check, Classification, DocumentResult, Evidence, Extraction
from web import app as webapp
from tests.uzp_data import UZP

DATA = UZP / "dane" / "przyklad_07"


def fake_case(case_dir):
    cls = Classification("odwolanie", 7.5, {"odwolanie": 7.5, "przelew": 1.0}, "naglowek: Krajowa Izba")
    ev = Evidence("Odwolujacy[0].nip", "123", page=1, snippet="NIP 123", rule="regex:nip", confidence=0.9)
    docs = [
        DocumentResult("a/odwolanie.pdf", "odwolanie.json", cls, Extraction({"x": 1}, [ev])),
        DocumentResult("a/ted.pdf", None, Classification(None, 0.5, {}, "ogloszenie TED"), None),
        DocumentResult("a/bad.pdf", None, Classification(None, 0.0, reason="error"), None, ["ValueError: x"]),
    ]
    return CaseResult("c", docs, [Check("a == b", True, "ok")])


class WebTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(webapp.app)

    def post(self, names=("a.pdf",)):
        files = [("files", (n, b"%PDF-1.4 x", "application/pdf")) for n in names]
        return self.client.post("/api/process", files=files)

    def test_index_and_recipes(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        rec = self.client.get("/api/recipes").json()
        self.assertIn("odwolanie", rec["classes"])

    def test_cold_trace_kit_is_served_offline(self):
        h = self.client.get("/").text
        self.assertIn('class="ct"', h)
        self.assertIn("<svg", h.split('class="eph-lockup')[1])  # Eterphis lockup inlined
        self.assertNotIn("ETERPHIS_", h)
        css = self.client.get("/static/coldtrace/bundle.css").text
        self.assertNotIn("/_blob/", css)
        self.assertNotIn("fonts.googleapis.com", css)
        for path in ("bundle.js", "grit-dark.png", "grit-light.png", "fonts.css", "eterphis-mark.css",
                     "fonts/anybody-latin-ext.woff2", "fonts/martian-mono-latin-ext.woff2"):
            self.assertEqual(self.client.get("/static/coldtrace/" + path).status_code, 200, path)

    def test_process_shape(self):
        orig = webapp.process_case
        webapp.process_case = fake_case
        try:
            j = self.post(["odwolanie.pdf", "ted.pdf", "bad.pdf"]).json()
        finally:
            webapp.process_case = orig
        d = j["documents"]
        self.assertEqual(d[0]["input_name"], "odwolanie.pdf")
        self.assertEqual(d[0]["evidence"][0]["snippet"], "NIP 123")
        self.assertIsNone(d[1]["output_name"])
        self.assertEqual(j["checks"][0]["ok"], True)

    def test_rejects_non_pdf_and_empty(self):
        self.assertEqual(self.client.post("/api/process").status_code, 422)
        r = self.client.post("/api/process", files=[("files", ("a.txt", b"hi", "text/plain"))])
        self.assertEqual(r.status_code, 400)

    def test_unsafe_names_are_flattened(self):
        seen = {}

        def spy(case_dir):
            seen["names"] = sorted(p.name for p in Path(case_dir).iterdir())
            return CaseResult("c", [])

        orig = webapp.process_case
        webapp.process_case = spy
        try:
            self.post(["../../evil.pdf", "x.pdf", "x.pdf"])
        finally:
            webapp.process_case = orig
        self.assertEqual(seen["names"], ["evil.pdf", "x.pdf", "x_2.pdf"])

    def test_zip_layout(self):
        payload = {"case": "przyklad_07", "files": {"odwolanie.json": {"a": "ż"}}}
        r = self.client.post("/api/zip", json=payload)
        self.assertEqual(r.status_code, 200)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        self.assertEqual(z.namelist(), ["output/przyklad_07/odwolanie.json"])
        self.assertEqual(json.loads(z.read(z.namelist()[0]).decode("utf-8")), {"a": "ż"})

    def test_zip_rejects_path_tricks(self):
        r = self.client.post("/api/zip", json={"case": "../x", "files": {"../a.json": {}}})
        self.assertEqual(r.status_code, 400)

    @unittest.skipUnless(DATA.exists(), "uzp-data missing")
    def test_real_case(self):
        files = [("files", (n, open(DATA / n, "rb"), "application/pdf")) for n in ("odwolanie.pdf", "pelnomocnictwo.pdf")]
        r = self.client.post("/api/process", files=files)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["documents"]), 2)
