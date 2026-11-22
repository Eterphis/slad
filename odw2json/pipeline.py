"""ingest -> classify -> extract -> write, per case folder."""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from functools import partial
from pathlib import Path

from . import factory
from .case import apply_case
from .model import CaseResult, Classification, Classifier, DocumentResult, Extractor, Ingestor
from .write import complete, write_json

log = logging.getLogger("odw2json")


def _pdfs(case_dir: Path) -> list[Path]:
    return sorted(p for p in case_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")


def _process_pdf(pdf: Path, ingestor: Ingestor, classifier: Classifier, extractor: Extractor) -> DocumentResult:
    try:
        doc = ingestor.ingest(str(pdf))
        cls = classifier.classify(doc)
        if cls.doc_class is None:
            return DocumentResult(str(pdf), None, cls, None)
        ext = extractor.extract(doc, cls.doc_class)
        ext.data = complete(ext.data, cls.doc_class)
        return DocumentResult(str(pdf), pdf.stem + ".json", cls, ext)
    except ImportError:  # broken environment, not a bad document: fail loudly
        raise
    except Exception as e:  # one broken PDF must never kill the batch
        log.exception("failed on %s", pdf)
        return DocumentResult(str(pdf), None, Classification(None, 0.0, reason="error"), None, [f"{type(e).__name__}: {e}"])


def process_case(case_dir, ingestor=None, classifier=None, extractor=None) -> CaseResult:
    """Process one case folder; does not write files (the caller decides)."""
    case_dir = Path(case_dir)
    ingestor = ingestor or factory.default_ingestor()
    classifier = classifier or factory.default_classifier()
    extractor = extractor or factory.default_extractor()
    for extra in sorted(p for p in case_dir.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf" and p.parent != case_dir):
        log.warning("skipping %s: PDFs must lie directly in the case folder", extra)
    docs = [_process_pdf(p, ingestor, classifier, extractor) for p in _pdfs(case_dir)]
    return apply_case(CaseResult(case_dir.name, docs))


REJECTED_JSON = ("{}", "empty", "none")


def write_rejected(path: Path, mode: str) -> None:
    """UZP: a document that belongs to no class gets an empty .json ('{}' = valid JSON, 'empty' = 0 bytes)."""
    if mode == "none":
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n" if mode == "{}" else "", encoding="utf-8")


def default_workers() -> int:
    """env ODW2JSON_WORKERS, else min(4, cpu_count // 2), at least 1 (4 workers peak well under 8 GB, see docs/PROFILES.md)."""
    try:
        return max(1, int(os.environ["ODW2JSON_WORKERS"]))
    except (KeyError, ValueError):
        return max(1, min(4, (os.cpu_count() or 2) // 2))


# -- worker pool ------------------------------------------------------------------------------------------------
_W: tuple | None = None  # (ingestor, classifier, extractor) of this worker process, built once


def _init_worker(builder) -> None:
    global _W
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _W = builder()


def _run_pdf(pdf: str):
    t0 = time.perf_counter()
    res = _process_pdf(Path(pdf), *_W)
    return res, time.perf_counter() - t0


def _failed(pdf: Path, why: str) -> DocumentResult:
    return DocumentResult(str(pdf), None, Classification(None, 0.0, reason="error"), None, [why])


def _run_pool(pdfs: list[Path], workers: int, builder) -> list[tuple[DocumentResult, float]]:
    """Results in input order. A worker that dies (OOM, native crash) fails only the document it was running."""
    out: list = [None] * len(pdfs)
    with ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(builder,)) as ex:
        futs = [ex.submit(_run_pdf, str(p)) for p in pdfs]
        for i, f in enumerate(futs):
            try:
                out[i] = f.result()
            except BrokenProcessPool:
                break
    pending = [i for i, r in enumerate(out) if r is None]
    pool = None
    try:
        for i in pending:  # the pool broke: find the culprit by running the rest one document at a time
            if pool is None:
                pool = ProcessPoolExecutor(1, initializer=_init_worker, initargs=(builder,))
            try:
                out[i] = pool.submit(_run_pdf, str(pdfs[i])).result()
            except BrokenProcessPool:
                log.error("worker died on %s; document gets an empty result", pdfs[i])
                out[i] = (_failed(pdfs[i], "WorkerCrash: the worker process died"), 0.0)
                pool.shutdown(wait=False, cancel_futures=True)
                pool = None
    finally:
        if pool is not None:
            pool.shutdown()
    return out


def process_input(input_dir, output_dir, ingestor=None, classifier=None, extractor=None, rejected_json="{}",
                  workers=1, profile=None, builder=None, stats=None) -> list[CaseResult]:
    """Walk <input>/<case>/*.pdf and write <output>/<case>/<basename>.json for every PDF: the extraction for an
    accepted document, an empty JSON (see `rejected_json`) for a rejected or unreadable one.

    `workers` > 1 runs documents in a spawn process pool; each worker builds its components once with `builder`
    (picklable callable returning (ingestor, classifier, extractor); default `factory.build_components(profile)`).
    Injected components are not shipped to workers: they force a serial run. Files are written by this process in
    sorted order, so the output tree is identical for every worker count. `stats`, if given, receives
    {"workers": n, "docs": [{"path", "case", "seconds"}]}."""
    if rejected_json not in REJECTED_JSON:
        raise ValueError(f"rejected_json must be one of {REJECTED_JSON}")
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not input_dir.is_dir():
        log.warning("input directory %s does not exist", input_dir)
        return []
    for loose in sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"):
        log.warning("skipping %s: PDFs must lie in <input>/<case>/", loose)
    cases = sorted(p for p in input_dir.iterdir() if p.is_dir())
    for c in cases:
        for extra in sorted(p for p in c.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf" and p.parent != c):
            log.warning("skipping %s: PDFs must lie directly in the case folder", extra)
    jobs = [(c, p) for c in cases for p in _pdfs(c)]
    injected = any(x is not None for x in (ingestor, classifier, extractor))
    n = 1 if injected else max(1, min(int(workers or 1), len(jobs)))
    builder = builder or partial(factory.build_components, profile)
    if n > 1:
        os.environ.setdefault("ODW2JSON_OCR_THREADS", str(max(1, (os.cpu_count() or 2) // n)))  # inherited by workers
        done = _run_pool([p for _, p in jobs], n, builder)
    else:
        if injected:
            comps = (ingestor or factory.default_ingestor(), classifier or factory.default_classifier(),
                     extractor or factory.default_extractor())
        else:
            comps = builder()
        done = []
        for _, p in jobs:
            t0 = time.perf_counter()
            done.append((_process_pdf(p, *comps), time.perf_counter() - t0))
    if stats is not None:
        stats["workers"] = n
        stats["docs"] = [{"path": str(p), "case": c.name, "seconds": round(t, 4)} for (c, p), (_, t) in zip(jobs, done)]
    by_case: dict[str, list[DocumentResult]] = {c.name: [] for c in cases}
    for (c, _), (d, _) in zip(jobs, done):
        by_case[c.name].append(d)
    results: list[CaseResult] = []
    for c in cases:
        res = apply_case(CaseResult(c.name, by_case[c.name]))  # same case step as process_case (web), before writing
        for d in res.documents:
            if d.output_name and d.extraction is not None:
                write_json(output_dir / res.case / d.output_name, d.extraction.data)
            else:
                write_rejected(output_dir / res.case / (Path(d.input_path).stem + ".json"), rejected_json)
        results.append(res)
    return results
