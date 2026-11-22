import json
import tempfile
import unittest
from pathlib import Path

from eval import score as S


def write(root, case, name, obj):
    d = Path(root) / case
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


ODW = {"OdwolanieKIO": {"data": None, "czynnosc_dzien": "2026-03-20", "czynnosc_powod_id": 9},
       "Odwolujacy": [{"nazwa": "A", "nip": "123"}, {"nazwa": "B", "nip": "456"}]}
PEL = {"mocodawca": [{"data": {"nazwa": "A", "krs": "1"}, "podpisujacy": [{"imie_nazwisko": "X Y"}]}],
       "pelnomocnicy": [{"imie_nazwisko": "P Q", "pesel": None}]}
PRZ = {"przelew_bankowy": {"kwota": 200.0, "tytul": "t", "na_rachunek": "11"}}


class TestLeaves(unittest.TestCase):
    def test_doc_type(self):
        self.assertEqual(S.doc_type(ODW), "odwolanie")
        self.assertEqual(S.doc_type(PEL), "pelnomocnictwo")
        self.assertEqual(S.doc_type(PRZ), "przelew")
        self.assertIsNone(S.doc_type({"x": 1}))

    def test_numbers_by_value(self):
        self.assertTrue(S.eq_exact(50, 50.0))
        self.assertFalse(S.eq_exact(True, 1))
        self.assertFalse(S.eq_exact("50", 50))
        self.assertFalse(S.eq_exact("a ", "a"))

    def test_normalized(self):
        self.assertTrue(S.eq_norm("  Ala   MA  ", "ala ma"))
        self.assertTrue(S.eq_norm('"Ala"', "Ala"))
        self.assertTrue(S.eq_norm("12-34 56", "123456"))
        self.assertFalse(S.eq_norm("abc", "abd"))


class TestCompare(unittest.TestCase):
    def test_identical(self):
        c = S.compare_docs(ODW, ODW, S.eq_exact)
        self.assertEqual(c.fp, 0)
        self.assertEqual(c.fn, 0)
        self.assertEqual(c.tp, 6)  # null data ignored

    def test_wrong_value_is_fp_and_fn(self):
        p = json.loads(json.dumps(PRZ))
        p["przelew_bankowy"]["tytul"] = "zly"
        c = S.compare_docs(p, PRZ, S.eq_exact)
        self.assertEqual((c.tp, c.fp, c.fn), (2, 1, 1))

    def test_pred_value_gold_null_is_fp(self):
        p = json.loads(json.dumps(PEL))
        p["pelnomocnicy"][0]["pesel"] = "123"
        c = S.compare_docs(p, PEL, S.eq_exact)
        self.assertEqual((c.fp, c.fn), (1, 0))

    def test_missing_is_fn(self):
        p = {"przelew_bankowy": {"kwota": 200.0}}
        c = S.compare_docs(p, PRZ, S.eq_exact)
        self.assertEqual((c.tp, c.fp, c.fn), (1, 0, 2))

    def test_list_alignment_order_independent(self):
        p = json.loads(json.dumps(ODW))
        p["Odwolujacy"].reverse()
        c = S.compare_docs(p, ODW, S.eq_exact)
        self.assertEqual((c.fp, c.fn), (0, 0))

    def test_unmatched_list_items(self):
        p = json.loads(json.dumps(ODW))
        p["Odwolujacy"].pop()
        c = S.compare_docs(p, ODW, S.eq_exact)
        self.assertEqual((c.fp, c.fn), (0, 2))
        p = json.loads(json.dumps(ODW))
        p["Odwolujacy"].append({"nazwa": "Z", "nip": "9"})
        c = S.compare_docs(p, ODW, S.eq_exact)
        self.assertEqual((c.fp, c.fn), (2, 0))

    def test_normalized_more_lenient(self):
        p = json.loads(json.dumps(PRZ))
        p["przelew_bankowy"]["tytul"] = " T "
        self.assertEqual(S.compare_docs(p, PRZ, S.eq_exact).fp, 1)
        self.assertEqual(S.compare_docs(p, PRZ, S.eq_norm).fp, 0)


class TestRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gold = Path(self.tmp.name) / "gold"
        self.pred = Path(self.tmp.name) / "pred"
        self.pred.mkdir()
        write(self.gold, "przyklad_01", "odwolanie.json", ODW)
        write(self.gold, "przyklad_01", "przelew.json", PRZ)
        write(self.gold, "przyklad_02", "pelnomocnictwo.json", PEL)

    def test_perfect_with_renamed_files(self):
        write(self.pred, "przyklad_01", "x.json", ODW)
        write(self.pred, "przyklad_01", "potwierdzenie_przelewu.json", PRZ)
        write(self.pred, "przyklad_02", "y.json", PEL)
        r = S.score_dirs(self.pred, self.gold)
        self.assertEqual(r["exact"].f1, 1.0)
        self.assertEqual(r["normalized"].f1, 1.0)

    def test_missing_case_all_fn(self):
        write(self.pred, "przyklad_01", "a.json", ODW)
        write(self.pred, "przyklad_01", "b.json", PRZ)
        r = S.score_dirs(self.pred, self.gold)
        self.assertEqual(r["exact"].fp, 0)
        self.assertGreater(r["exact"].fn, 0)
        self.assertLess(r["exact"].f1, 1.0)

    def test_extra_document_all_fp(self):
        write(self.pred, "przyklad_01", "a.json", ODW)
        write(self.pred, "przyklad_01", "b.json", PRZ)
        write(self.pred, "przyklad_02", "c.json", PEL)
        write(self.pred, "przyklad_02", "d.json", PRZ)
        r = S.score_dirs(self.pred, self.gold, cases="02")
        self.assertEqual(r["exact"].fn, 0)
        self.assertEqual(r["exact"].fp, 3)

    def test_two_docs_same_type_paired_by_agreement(self):
        other = json.loads(json.dumps(PRZ))
        other["przelew_bankowy"]["kwota"] = 5.0
        other["przelew_bankowy"]["tytul"] = "inny"
        write(self.gold, "przyklad_03", "p1.json", PRZ)
        write(self.gold, "przyklad_03", "p2.json", other)
        write(self.pred, "przyklad_03", "a.json", other)
        write(self.pred, "przyklad_03", "b.json", PRZ)
        r = S.score_dirs(self.pred, self.gold, cases="03")
        self.assertEqual(r["exact"].f1, 1.0)

    def test_cases_and_types_filter(self):
        self.assertEqual(min(S.parse_cases("41-60")), 41)
        self.assertEqual(sorted(S.parse_cases("01,07")), [1, 7])
        r = S.score_dirs(self.pred, self.gold, cases="02", types=["pelnomocnictwo"])
        self.assertEqual(r["exact"].tp, 0)
        self.assertEqual(r["exact"].fn, 4)

    def test_empty_everything_is_zero(self):
        r = S.score_dirs(self.pred, self.gold, cases="99")
        self.assertEqual(r["exact"].f1, 0.0)

    def test_cli_last_line_and_report(self):
        import subprocess, sys
        write(self.pred, "przyklad_01", "a.json", ODW)
        rep = Path(self.tmp.name) / "r.md"
        out = subprocess.run([sys.executable, "-X", "utf8", "-m", "eval.score", "--pred", str(self.pred),
                              "--gold", str(self.gold), "--report", str(rep)],
                             capture_output=True, text=True, encoding="utf-8",
                             cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(out.returncode, 0, out.stderr)
        last = out.stdout.strip().splitlines()[-1]
        self.assertRegex(last, r"^score: \d\.\d{4}$")
        self.assertIn("normalized:", out.stdout)
        self.assertIn("worst", rep.read_text(encoding="utf-8").lower())


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gold = Path(self.tmp.name) / "gold"
        self.pred = Path(self.tmp.name) / "pred"
        self.pred.mkdir()

    def test_field_paths_same_for_matched_and_unmatched(self):
        matched = S.compare_docs(PRZ, PRZ, S.eq_exact)
        write(self.gold, "przyklad_01", "przelew.json", PRZ)
        write(self.gold, "przyklad_02", "przelew.json", PRZ)  # missing in pred
        write(self.gold, "przyklad_03", "x.json", ODW)
        write(self.pred, "przyklad_01", "a.json", PRZ)
        write(self.pred, "przyklad_03", "extra.json", PRZ)  # extra przelew
        r = S.score_dirs(self.pred, self.gold)
        fields = r["by_type"]["exact"]["przelew"].fields
        self.assertEqual(set(fields), set(matched.fields))
        self.assertEqual(fields["przelew_bankowy.kwota"], [1, 1, 1])

    def test_nested_list_alignment(self):
        g = {"mocodawca": [{"data": {"nazwa": "A"}, "podpisujacy": [{"imie_nazwisko": "a"}, {"imie_nazwisko": "b"}]},
                           {"data": {"nazwa": "B"}, "podpisujacy": [{"imie_nazwisko": "c"}]}]}
        p = {"mocodawca": [{"data": {"nazwa": "B"}, "podpisujacy": [{"imie_nazwisko": "c"}]},
                           {"data": {"nazwa": "A"}, "podpisujacy": [{"imie_nazwisko": "b"}, {"imie_nazwisko": "a"}]}]}
        c = S.compare_docs(p, g, S.eq_exact)
        self.assertEqual((c.tp, c.fp, c.fn), (5, 0, 0))

    def test_three_items_non_square(self):
        g = [{"a": 1, "b": 1, "c": 1}, {"a": 1, "b": 1, "c": 9}]
        p = [{"a": 1, "b": 1, "c": 9}, {"a": 1, "b": 1, "c": 1}, {"a": 7}]
        c = S.compare(p, g, S.eq_exact)
        self.assertEqual((c.tp, c.fp, c.fn), (6, 1, 0))

    def test_dict_vs_list_mismatch(self):
        c = S.compare({"x": {"a": 1}}, {"x": [{"a": 1}]}, S.eq_exact)
        self.assertEqual((c.tp, c.fp, c.fn), (0, 1, 1))

    def test_extra_pred_key_is_fp(self):
        p = json.loads(json.dumps(PRZ))
        p["przelew_bankowy"]["extra"] = "x"
        c = S.compare_docs(p, PRZ, S.eq_exact)
        self.assertEqual((c.tp, c.fp, c.fn), (3, 1, 0))

    def test_parse_cases_exact(self):
        self.assertEqual(S.parse_cases("01-05,60"), {1, 2, 3, 4, 5, 60})
        self.assertIsNone(S.parse_cases(None))

    def test_bom_invalid_and_unknown_type(self):
        write(self.gold, "przyklad_01", "przelew.json", PRZ)
        d = self.pred / "przyklad_01"
        d.mkdir()
        (d / "bom.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(PRZ).encode("utf-8"))
        (d / "bad.json").write_text("{not json", encoding="utf-8")
        (d / "unk.json").write_text(json.dumps({"foo": "x", "baz": [1, 2]}), encoding="utf-8")
        r = S.score_dirs(self.pred, self.gold)
        self.assertEqual((r["exact"].tp, r["exact"].fp, r["exact"].fn), (3, 3, 0))
        self.assertIn("unknown", r["by_type"]["exact"])

    def test_malformed_cases_is_clean_error(self):
        import subprocess, sys
        out = subprocess.run([sys.executable, "-X", "utf8", "-m", "eval.score", "--pred", str(self.pred),
                              "--gold", str(self.pred), "--cases", "1-x"],
                             capture_output=True, text=True, encoding="utf-8",
                             cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(out.returncode, 2)
        self.assertNotIn("Traceback", out.stderr)

    def test_stray_pred_case_warns_once(self):
        import contextlib, io
        write(self.gold, "przyklad_01", "przelew.json", PRZ)
        write(self.pred, "przyklad_1", "a.json", PRZ)
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            S.score_dirs(self.pred, self.gold)
        self.assertEqual(buf.getvalue().count("przyklad_1"), 1)

    def test_unknown_gold_warns_once_with_name(self):
        import contextlib, io
        write(self.gold, "przyklad_01", "weird.json", {"foo": 1})
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            S.score_dirs(self.pred, self.gold)
        self.assertEqual(buf.getvalue().count("weird.json"), 1)


if __name__ == "__main__":
    unittest.main()
