"""F1 versus cost, per processing profile x evaluation set x worker count.

usage: python -m eval.bench --profiles text,ocr --sets heldout,skany,negatywne --workers 1,4 --out .acc/bench
                            [--gate] [--accept] [--cold] [--history bench/history.csv] [--src <uzp-data>/dane]

Sets: dev (przyklad_01-40), heldout (41-60), skany (30 scans with gold), noisy (eval.make_noisy tree, optional,
--noisy-dir), negatywne (12 documents that must give `{}`). Each (profile, set, workers) is one `python -m odw2json`
subprocess, so peak RSS (psutil, parent + all workers, sampled) is isolated per run. Quality comes from
eval.score as a library (never modified here). Writes <out>/bench-<date>-<commit>.json and .md, appends
bench/history.csv and ends with `bench: <P> profiles x <S> sets ok`. See docs/PROFILES.md for how to read the table.

Gate (`--gate`): compared with the last row of history.csv flagged accepted=1 for the same profile/set/workers:
F1 (exact or normalized) on heldout/skany may drop by at most 0.005; p95 time and peak RSS may grow by at most 20 %
(ignoring growth under 0.05 s / 50 MB, which is noise). Exit 1 on a violation. `--accept` flags this run's rows as
the new baseline. Time numbers are warm-OCR-cache unless `--cold` (fresh cache per run: honest scan cost).
"""
from __future__ import annotations

import argparse
import csv
import datetime
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from eval import prep_skany, score

ROOT = Path(__file__).resolve().parents[1]
SETS = ("dev", "heldout", "skany", "noisy", "negatywne")
CASES = {"dev": set(range(1, 41)), "heldout": set(range(41, 61))}
GATED_SETS = ("heldout", "skany")
F1_TOLERANCE = 0.005
GROWTH = 1.20
MIN_ABS_SECONDS = 0.05
MIN_ABS_MB = 50.0
COLUMNS = ["date", "commit", "profile", "set", "workers", "docs", "f1_exact", "f1_norm", "reject_acc", "false_rejects",
           "p50", "p95", "docs_per_min", "peak_rss_mb", "model_mb", "cold", "accepted"]


# ---------------------------------------------------------------- pure helpers

def percentile(values, q):
    """Linear-interpolated percentile (q in 0..100); 0.0 for an empty list."""
    xs = sorted(values)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * q / 100.0
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _is_empty_json(path: Path) -> bool:
    if not path.is_file():
        return True  # no file = rejected (rejected_json=none)
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return True
    try:
        return json.loads(text) == {}
    except ValueError:
        return False


def reject_stats(input_dir, output_dir) -> dict:
    """{"docs": n, "rejected": r}: for every input PDF, is its output empty (`{}`, 0 bytes or absent)?"""
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    docs = rejected = 0
    for pdf in sorted(input_dir.rglob("*.pdf")):
        docs += 1
        if _is_empty_json(output_dir / pdf.parent.relative_to(input_dir) / (pdf.stem + ".json")):
            rejected += 1
    return {"docs": docs, "rejected": rejected}


def score_set(pred_dir, gold_dir, cases=None) -> tuple[float, float]:
    """(exact F1, normalized F1) through eval.score."""
    res = score.score_dirs(pred_dir, gold_dir, cases)
    return res["exact"].f1, res["normalized"].f1


@dataclass
class SetSpec:
    name: str
    input: Path
    gold: Path | None
    cases: set | None = None


def prepare_set(name: str, work: Path, src: Path, noisy_dir: Path | None = None) -> SetSpec:
    """Lay out the input tree (<input>/<case>/*.pdf) of an evaluation set and find its gold."""
    work = Path(work)
    if name in CASES:
        dest = work / name / "input"
        shutil.rmtree(work / name, ignore_errors=True)
        for case in sorted(src.glob("przyklad_*")):
            no = score._case_no(case.name)
            if no in CASES[name]:
                (dest / case.name).mkdir(parents=True)
                for pdf in sorted(case.glob("*.pdf")):
                    shutil.copy2(pdf, dest / case.name / pdf.name)
        return SetSpec(name, dest, src, CASES[name])
    if name == "skany":
        prep_skany.prepare(work / "skany", src)
        shutil.rmtree(work / "skany" / "input" / "negatywne", ignore_errors=True)
        return SetSpec(name, work / "skany" / "input", work / "skany" / "gold")
    if name == "negatywne":
        dest = work / "negatywne" / "input" / "negatywne"
        shutil.rmtree(work / "negatywne", ignore_errors=True)
        dest.mkdir(parents=True)
        for pdf in sorted((src / "negatywne").glob("*.pdf")):
            shutil.copy2(pdf, dest / pdf.name)
        return SetSpec(name, work / "negatywne" / "input", None)
    if name == "noisy":
        if noisy_dir is None or not (Path(noisy_dir) / "input").is_dir():
            raise SystemExit("set 'noisy' needs --noisy-dir <dir from eval.make_noisy> (with input/ and gold/)")
        return SetSpec(name, Path(noisy_dir) / "input", Path(noisy_dir) / "gold")
    raise SystemExit(f"unknown set {name!r}; choose from {', '.join(SETS)}")


def _fmt(v, spec):
    return "-" if v is None or v == "" else format(float(v), spec)


def to_markdown(rows) -> str:
    L = ["| profile | set | workers | docs | F1 exact | F1 norm | reject acc | false rejects | p50 s | p95 s | docs/min | peak RSS MB | model MB | OCR cache |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        ra = "-" if r.get("reject_acc") is None else f"{100 * float(r['reject_acc']):.1f}%"
        L.append(f"| {r['profile']} | {r['set']} | {r['workers']} | {r['docs']} | {_fmt(r.get('f1_exact'), '.4f')} | "
                 f"{_fmt(r.get('f1_norm'), '.4f')} | {ra} | {_fmt(r.get('false_rejects'), '.0f')} | {_fmt(r['p50'], '.2f')} | "
                 f"{_fmt(r['p95'], '.2f')} | {_fmt(r['docs_per_min'], '.1f')} | {_fmt(r['peak_rss_mb'], '.0f')} | "
                 f"{_fmt(r['model_mb'], '.0f')} | {'cold' if r.get('cold') else 'warm'} |")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- history and gate

def read_history(path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_history(path, rows, date, commit, accepted=False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.is_file()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            out = {k: ("" if r.get(k) is None else r.get(k)) for k in COLUMNS}
            out.update(date=date, commit=commit, accepted=1 if accepted else 0,
                       cold=1 if r.get("cold") else 0)
            for k in ("f1_exact", "f1_norm", "reject_acc", "p50", "p95", "docs_per_min", "peak_rss_mb", "model_mb"):
                if out[k] != "":
                    out[k] = round(float(out[k]), 4)
            w.writerow(out)


def last_accepted(history, profile, set_name, workers):
    hit = None
    for h in history:
        if (h.get("accepted") == "1" and h.get("profile") == profile and h.get("set") == set_name
                and str(h.get("workers")) == str(workers)):
            hit = h
    return hit


def check_gate(rows, history) -> list[str]:
    bad = []
    for r in rows:
        base = last_accepted(history, r["profile"], r["set"], r["workers"])
        if base is None:
            continue
        tag = f"{r['profile']}/{r['set']}/w{r['workers']}"
        if r["set"] in GATED_SETS:
            for key, label in (("f1_exact", "F1 exact"), ("f1_norm", "F1 normalized")):
                old, new = base.get(key), r.get(key)
                if old not in (None, "") and new is not None and float(new) < float(old) - F1_TOLERANCE:
                    bad.append(f"{tag}: {label} {float(new):.4f} < {float(old):.4f} - {F1_TOLERANCE}")
        for key, label, floor in (("p95", "p95 time", MIN_ABS_SECONDS), ("peak_rss_mb", "peak RSS", MIN_ABS_MB)):
            old, new = base.get(key), r.get(key)
            if old in (None, "") or new is None:
                continue
            old, new = float(old), float(new)
            if new > old * GROWTH and new - old >= floor:
                bad.append(f"{tag}: {label} {new:.2f} > {old:.2f} x {GROWTH}")
    return bad


# ---------------------------------------------------------------- measuring

class PeakRss:
    """Context manager sampling the summed RSS of a process and all its descendants; `.peak_mb` afterwards."""

    def __init__(self, pid: int, interval: float = 0.2):
        import psutil

        self._ps, self._proc, self.interval = psutil, psutil.Process(pid), interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self.peak = 0

    def _sample(self):
        total = 0
        try:
            procs = [self._proc, *self._proc.children(recursive=True)]
        except self._ps.Error:
            return
        for p in procs:
            try:
                total += p.memory_info().rss
            except self._ps.Error:
                pass
        self.peak = max(self.peak, total)

    def _loop(self):
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval)

    def __enter__(self):
        self._sample()
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._sample()
        self._stop.set()
        self._thread.join()

    @property
    def peak_mb(self) -> float:
        return self.peak / (1024 * 1024)


def model_size_mb(profile: str) -> float:
    """Model files the profile loads: the RapidOCR ONNX models when OCR is on (+ a reader model path, if set)."""
    from odw2json import profiles

    prof = profiles.load_profile(profile)
    total = 0
    if prof.ocr_enabled:
        spec = importlib.util.find_spec("rapidocr")
        if spec and spec.submodule_search_locations:
            for loc in spec.submodule_search_locations:
                total += sum(f.stat().st_size for f in Path(loc).rglob("*.onnx"))
    model = (prof.reader or {}).get("model")
    if model and Path(model).exists():
        total += sum(f.stat().st_size for f in Path(model).rglob("*") if f.is_file()) if Path(model).is_dir() else Path(model).stat().st_size
    return total / (1024 * 1024)


@dataclass
class Context:
    work: Path
    src: Path | None
    cold: bool = False
    noisy_dir: Path | None = None
    specs: dict | None = None

    def spec(self, name: str) -> SetSpec:
        if self.specs is None:
            self.specs = {}
        if name not in self.specs:
            self.specs[name] = prepare_set(name, self.work / "sets", self.src or prep_skany.default_src(), self.noisy_dir)
        return self.specs[name]


def measure(profile: str, set_name: str, workers: int, ctx: Context) -> dict:
    """Run the CLI once on a set and return one result row."""
    spec = ctx.spec(set_name)
    run_dir = ctx.work / "runs" / f"{profile}-{set_name}-w{workers}"
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)
    out_dir, stats_file = run_dir / "out", run_dir / "stats.json"
    env = dict(os.environ, PYTHONUTF8="1")
    cache_dir = None
    if ctx.cold:
        cache_dir = tempfile.mkdtemp(prefix="odw2json-cold-")
        env["ODW2JSON_OCR_CACHE_DIR"] = cache_dir
    cmd = [sys.executable, "-X", "utf8", "-m", "odw2json", "--input", str(spec.input), "--output", str(out_dir),
           "--profile", profile, "--workers", str(workers), "--stats", str(stats_file)]
    t0 = time.perf_counter()
    try:
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        with PeakRss(proc.pid) as rss:
            log, _ = proc.communicate()
    finally:
        if cache_dir:
            shutil.rmtree(cache_dir, ignore_errors=True)
    wall = time.perf_counter() - t0
    (run_dir / "log.txt").write_text(log or "", encoding="utf-8")
    if proc.returncode != 0 or not stats_file.is_file():
        raise SystemExit(f"odw2json failed for {profile}/{set_name}/w{workers} (exit {proc.returncode}); see {run_dir / 'log.txt'}")
    secs = [d["seconds"] for d in json.loads(stats_file.read_text(encoding="utf-8"))["docs"]]
    rej = reject_stats(spec.input, out_dir)
    row = dict(profile=profile, set=set_name, workers=workers, docs=rej["docs"], f1_exact=None, f1_norm=None,
               reject_acc=None, false_rejects=None, p50=percentile(secs, 50), p95=percentile(secs, 95),
               docs_per_min=60.0 * rej["docs"] / wall if wall else 0.0, peak_rss_mb=rss.peak_mb,
               model_mb=model_size_mb(profile), cold=ctx.cold, wall_s=wall)
    if spec.gold is None:
        row["reject_acc"] = rej["rejected"] / rej["docs"] if rej["docs"] else None
    else:
        row["f1_exact"], row["f1_norm"] = score_set(out_dir, spec.gold, spec.cases)
        row["false_rejects"] = rej["rejected"]
    return row


# ---------------------------------------------------------------- main

def _git_commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip() or "nogit"
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def _csv_arg(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def main(argv=None, measure=measure, commit=None, today=None) -> int:
    from odw2json import profiles

    ap = argparse.ArgumentParser(prog="eval.bench", description=__doc__.split("\n\n")[0])
    ap.add_argument("--profiles", default="text,ocr")
    ap.add_argument("--sets", default=None, help=f"comma list of {','.join(SETS)} (default: all but noisy)")
    ap.add_argument("--workers", default="1,4", help="comma list of worker counts (default 1,4)")
    ap.add_argument("--out", default="bench-out")
    ap.add_argument("--history", default=str(ROOT / "bench" / "history.csv"))
    ap.add_argument("--src", default=None, help="<uzp-data>/dane (default: found like eval.prep_skany)")
    ap.add_argument("--noisy-dir", default=None)
    ap.add_argument("--gate", action="store_true", help="exit 1 on a regression vs the last accepted history row")
    ap.add_argument("--accept", action="store_true", help="flag this run's rows as accepted baseline")
    ap.add_argument("--cold", action="store_true", help="fresh OCR cache for every run (cost of scans, slow)")
    ap.add_argument("--record", action="store_true",
                    help="append this run to --history (tracked file); without it (or --accept) only <out>/history.csv")
    a = ap.parse_args(argv)

    names = _csv_arg(a.profiles)
    for n in names:
        try:
            profiles.load_profile(n)
        except profiles.ProfileError as e:
            raise SystemExit(f"profile error: {e}")
    sets = _csv_arg(a.sets) if a.sets else [s for s in SETS if s != "noisy"]
    for s in sets:
        if s not in SETS:
            raise SystemExit(f"unknown set {s!r}; choose from {', '.join(SETS)}")
    try:
        counts = [int(x) for x in _csv_arg(a.workers)]
    except ValueError:
        raise SystemExit("--workers must be a comma list of integers")
    if not counts or min(counts) < 1:
        raise SystemExit("--workers must be >= 1")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    src = Path(a.src) if a.src else None
    ctx = Context(out / "work", src, a.cold, Path(a.noisy_dir) if a.noisy_dir else None)
    rows = []
    for p in names:
        for s in sets:
            for w in counts:
                print(f"bench: {p} / {s} / {w} worker(s) ...", flush=True)
                r = measure(p, s, w, ctx)
                rows.append(r)
                print(f"  F1 {_fmt(r.get('f1_exact'), '.4f')}  reject {_fmt(r.get('reject_acc'), '.2f')}  p95 {r['p95']:.2f}s  "
                      f"{r['docs_per_min']:.1f} docs/min  RSS {r['peak_rss_mb']:.0f} MB", flush=True)

    commit = commit or _git_commit()
    today = today or datetime.date.today().isoformat()
    md = to_markdown(rows)
    meta = {"date": today, "commit": commit, "cpu_count": os.cpu_count(), "platform": platform.platform(),
            "cold": a.cold, "profiles": names, "sets": sets, "workers": counts}
    (out / f"bench-{today}-{commit}.json").write_text(json.dumps({"meta": meta, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / f"bench-{today}-{commit}.md").write_text(md, encoding="utf-8")
    print(md)

    violations = check_gate(rows, read_history(a.history)) if a.gate else []
    # Only an explicit --record/--accept touches the tracked history; plain runs (CI, acceptance checks) must not
    # leave the checkout dirty, so they append to a copy in --out.
    hist = a.history if (a.record or a.accept) else str(out / "history.csv")
    append_history(hist, rows, today, commit, accepted=a.accept and not violations)
    if violations:
        for v in violations:
            print(f"GATE FAIL {v}")
        return 1
    print(f"bench: {len(names)} profiles x {len(sets)} sets ok")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
