"""Bench logic with fakes: no UZP data, no OCR, no subprocess."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from eval import bench


def row(profile="ocr", set_="heldout", workers=1, f1=0.95, p95=1.0, rss=500.0, **kw):
    r = dict(profile=profile, set=set_, workers=workers, docs=20, f1_exact=f1, f1_norm=f1 + 0.01, reject_acc=None,
             false_rejects=0, p50=0.5, p95=p95, docs_per_min=60.0, peak_rss_mb=rss, model_mb=30.0, cold=False)
    r.update(kw)
    return r


class MathTests(unittest.TestCase):
    def test_percentile(self):
        xs = [1, 2, 3, 4, 5]
        self.assertEqual(bench.percentile(xs, 50), 3)
        self.assertEqual(bench.percentile(xs, 0), 1)
        self.assertEqual(bench.percentile(xs, 100), 5)
        self.assertAlmostEqual(bench.percentile([0, 10], 95), 9.5)
        self.assertEqual(bench.percentile([], 95), 0.0)
        self.assertEqual(bench.percentile([7], 95), 7)


class RejectTests(unittest.TestCase):
    def test_counts(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "in" / "negatywne").mkdir(parents=True)
            for n in "abcd":
                (d / "in" / "negatywne" / f"{n}.pdf").write_bytes(b"x")
            (d / "out" / "negatywne").mkdir(parents=True)
            (d / "out" / "negatywne" / "a.json").write_text("{}\n")
            (d / "out" / "negatywne" / "b.json").write_text("")
            (d / "out" / "negatywne" / "c.json").write_text('{"x": 1}')
            # d.json missing counts as rejected too (rejected_json=none)
            self.assertEqual(bench.reject_stats(d / "in", d / "out"), {"docs": 4, "rejected": 3})


class ScoreTests(unittest.TestCase):
    def test_score_set(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            gold = {"przelew_bankowy": {"kwota": 1.5, "tytul": "Abc"}}
            (d / "gold" / "przyklad_41").mkdir(parents=True)
            (d / "gold" / "przyklad_41" / "p.json").write_text(json.dumps(gold))
            (d / "pred" / "przyklad_41").mkdir(parents=True)
            (d / "pred" / "przyklad_41" / "p.json").write_text(json.dumps({"przelew_bankowy": {"kwota": 1.5, "tytul": "abc"}}))
            ex, nm = bench.score_set(d / "pred", d / "gold", {41})
            self.assertAlmostEqual(ex, 0.5)  # 1 TP, 1 FP + 1 FN -> 2/(2+1+1)
            self.assertEqual(nm, 1.0)


class PrepareTests(unittest.TestCase):
    def test_dev_heldout_trees(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "dane"
            for n in (1, 41):
                c = src / f"przyklad_{n:02d}"
                c.mkdir(parents=True)
                (c / "a.pdf").write_bytes(b"x")
                (c / "a.json").write_text("{}")
            spec = bench.prepare_set("heldout", Path(d) / "work", src)
            self.assertEqual(sorted(p.parent.name for p in spec.input.rglob("*.pdf")), ["przyklad_41"])
            self.assertEqual(spec.cases, set(range(41, 61)))
            self.assertEqual(spec.gold, src)
            spec = bench.prepare_set("dev", Path(d) / "work", src)
            self.assertEqual(sorted(p.parent.name for p in spec.input.rglob("*.pdf")), ["przyklad_01"])

    def test_skany_and_negatives_split(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "dane"
            c = src / "skany" / "odwolania" / "0001"
            c.mkdir(parents=True)
            (c / "0001.pdf").write_bytes(b"x")
            (c / "0001.json").write_text("{}")
            (src / "negatywne").mkdir(parents=True)
            (src / "negatywne" / "n.pdf").write_bytes(b"x")
            sk = bench.prepare_set("skany", Path(d) / "work", src)
            self.assertEqual([p.name for p in sk.input.rglob("*.pdf")], ["0001.pdf"])
            self.assertIsNotNone(sk.gold)
            ng = bench.prepare_set("negatywne", Path(d) / "work", src)
            self.assertEqual([p.name for p in ng.input.rglob("*.pdf")], ["n.pdf"])
            self.assertIsNone(ng.gold)


class TableTests(unittest.TestCase):
    def test_markdown(self):
        md = bench.to_markdown([row(), row(set_="negatywne", f1_exact=None, f1_norm=None, reject_acc=1.0)])
        self.assertIn("| profile | set | workers |", md)
        self.assertIn("0.9500", md)
        self.assertIn("100.0%", md)
        self.assertEqual(md.count("\n| ocr |"), 2)

    def test_history_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "sub" / "history.csv"
            bench.append_history(h, [row()], "2026-11-21", "abc1234", accepted=True)
            bench.append_history(h, [row(f1=0.9)], "2026-11-22", "def5678", accepted=False)
            rows = bench.read_history(h)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["commit"], "abc1234")
            self.assertEqual(float(bench.last_accepted(rows, "ocr", "heldout", 1)["f1_exact"]), 0.95)
            self.assertIsNone(bench.last_accepted(rows, "ocr", "heldout", 4))


class GateTests(unittest.TestCase):
    base = [dict(profile="ocr", set="heldout", workers="1", f1_exact="0.95", p95="1.0", peak_rss_mb="500", accepted="1"),
            dict(profile="ocr", set="skany", workers="1", f1_exact="0.80", p95="20", peak_rss_mb="1500", accepted="1")]

    def test_pass(self):
        self.assertEqual(bench.check_gate([row(f1=0.95), row(set_="skany", f1=0.80, p95=20, rss=1500)], self.base), [])

    def test_f1_drop(self):
        v = bench.check_gate([row(f1=0.9)], self.base)
        self.assertEqual(len(v), 1)
        self.assertIn("heldout", v[0])
        self.assertEqual(bench.check_gate([row(f1=0.9451)], self.base), [])  # within 0.005

    def test_f1_not_gated_on_dev(self):
        base = [dict(self.base[0], set="dev")]
        self.assertEqual(bench.check_gate([row(set_="dev", f1=0.5)], base), [])

    def test_p95_and_rss_growth(self):
        v = bench.check_gate([row(p95=1.3, rss=500)], self.base)
        self.assertTrue(any("p95" in x for x in v))
        v = bench.check_gate([row(p95=1.0, rss=700)], self.base)
        self.assertTrue(any("RSS" in x for x in v))

    def test_tiny_absolute_growth_ignored(self):
        base = [dict(self.base[0], p95="0.01", peak_rss_mb="100")]
        self.assertEqual(bench.check_gate([row(p95=0.03, rss=120)], base), [])

    def test_no_baseline_passes(self):
        self.assertEqual(bench.check_gate([row(profile="text")], self.base), [])

    def test_unaccepted_rows_ignored(self):
        base = [dict(self.base[0], accepted="0", f1_exact="0.99")]
        self.assertEqual(bench.check_gate([row(f1=0.5)], base), [])


def fake_measure(profile, set_name, workers, ctx):
    r = row(profile=profile, set_=set_name, workers=workers)
    if set_name == "negatywne":
        r.update(f1_exact=None, f1_norm=None, reject_acc=1.0)
    return r


class MainTests(unittest.TestCase):
    def run_main(self, args, history=None):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            h = history or str(Path(d) / "history.csv")
            with redirect_stdout(out):
                code = bench.main(["--out", str(Path(d) / "bench"), "--history", h, *args], measure=fake_measure,
                                  commit="abc1234", today="2026-11-21")
            files = sorted(p.name for p in (Path(d) / "bench").iterdir())
            hist = Path(h).read_text() if Path(h).exists() else ""
            rows = bench.read_history(h) if Path(h).exists() else []
        return code, out.getvalue(), files, hist, rows

    def test_summary_line_and_outputs(self):
        code, out, files, hist, _ = self.run_main(["--profiles", "text,ocr", "--sets", "heldout,skany,negatywne", "--workers", "1,4"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip().splitlines()[-1], "bench: 2 profiles x 3 sets ok")
        self.assertIn("bench-2026-11-21-abc1234.json", files)
        self.assertIn("bench-2026-11-21-abc1234.md", files)
        self.assertEqual(hist, "")  # a plain run never touches the tracked history (keeps the checkout clean)
        self.assertIn("history.csv", files)  # it appends to a copy in --out instead

    def test_record_appends_to_tracked_history(self):
        _, _, _, hist, _ = self.run_main(["--profiles", "text,ocr", "--sets", "heldout,skany,negatywne",
                                          "--workers", "1,4", "--record"])
        self.assertEqual(len(hist.strip().splitlines()), 1 + 12)

    def test_gate_fails_exit_1(self):
        with tempfile.TemporaryDirectory() as d:
            h = str(Path(d) / "h.csv")
            bench.append_history(h, [row(f1=0.99)], "x", "y", accepted=True)
            code, out, _, _, _ = self.run_main(["--profiles", "ocr", "--sets", "heldout", "--workers", "1", "--gate"], history=h)
            self.assertEqual(code, 1)
            self.assertIn("GATE FAIL", out)
            self.assertNotIn("sets ok", out)

    def test_accept_marks_rows(self):
        with tempfile.TemporaryDirectory() as d:
            h = str(Path(d) / "h.csv")
            self.run_main(["--profiles", "ocr", "--sets", "heldout", "--workers", "1", "--accept"], history=h)
            self.assertEqual(bench.last_accepted(bench.read_history(h), "ocr", "heldout", 1)["accepted"], "1")

    def test_unknown_profile_or_set(self):
        with self.assertRaises(SystemExit):
            self.run_main(["--profiles", "nope", "--sets", "heldout", "--workers", "1"])
        with self.assertRaises(SystemExit):
            self.run_main(["--profiles", "ocr", "--sets", "bogus", "--workers", "1"])


class PeakRssTests(unittest.TestCase):
    def test_sampler_sees_this_process(self):
        import os

        with bench.PeakRss(os.getpid(), interval=0.02) as p:
            blob = bytearray(20 * 1024 * 1024)
            blob[::4096] = b"x" * len(blob[::4096])
            import time

            time.sleep(0.1)
        self.assertGreater(p.peak_mb, 20)


if __name__ == "__main__":
    unittest.main()
