"""Swappable OCR backends.

A backend is any object with ``ocr(image) -> list[(text, box, conf)]`` where ``image`` is a PIL RGB image,
``box`` is ``(x0, y0, x1, y1)`` in image pixels (origin top-left) and ``conf`` is 0..1.
Register a new one with ``register_backend("name", factory)``; select it with config ``ocr.backend`` or the
environment variable ``ODW2JSON_OCR``. See docs/ocr-backends.md in the module docstring of ``get_backend``.
"""
from __future__ import annotations

import os
import shutil
from typing import Any, Callable, Protocol

OcrLine = tuple[str, tuple[float, float, float, float], float]


class OcrBackend(Protocol):
    def ocr(self, image: Any) -> list[OcrLine]: ...


_REGISTRY: dict[str, Callable[[dict], OcrBackend]] = {}


def register_backend(name: str, factory: Callable[[dict], OcrBackend]) -> None:
    """Add an OCR backend. ``factory`` receives the ``ocr`` config dict and returns a backend object."""
    _REGISTRY[name] = factory


def backend_names() -> list[str]:
    return sorted(_REGISTRY)


def get_backend(config: dict | None = None) -> OcrBackend:
    """Resolve the backend: env ODW2JSON_OCR > config['ocr']['backend'] > 'rapidocr'.

    To add a backend: implement ``ocr(image)`` as above, call ``register_backend`` at import time, and set
    ``ODW2JSON_OCR=<name>`` (or ``ocr: {backend: <name>}`` in the config).
    """
    cfg = dict((config or {}).get("ocr") or {})
    name = os.environ.get("ODW2JSON_OCR") or cfg.get("backend") or "rapidocr"
    if name not in _REGISTRY:
        raise ValueError(f"unknown OCR backend {name!r}; available: {backend_names()}")
    return _REGISTRY[name](cfg)


class RapidOcrBackend:
    """RapidOCR (Apache-2.0) on onnxruntime, CPU only.

    Default: the PP-OCRv6 detection/recognition models bundled inside the ``rapidocr`` wheel, so a plain
    ``pip install -r requirements.txt`` works offline (no model download) and reads Polish diacritics.
    Config ``ocr.rec_lang`` (e.g. "latin") switches to a downloadable language-specific recognition model.
    """

    def __init__(self, cfg: dict):
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

        params: dict = {"Global.log_level": "error"}
        if cfg.get("rec_lang"):
            params["Rec.lang_type"] = LangRec(cfg["rec_lang"])
            params["Rec.ocr_version"] = OCRVersion(cfg.get("ocr_version", "PP-OCRv5"))
            params["Rec.model_type"] = ModelType(cfg.get("model_type", "mobile"))
        # onnxruntime defaults to one thread per core in EVERY process; with a worker pool the pipeline sets
        # ODW2JSON_OCR_THREADS (cores // workers) so N workers do not oversubscribe the CPU N times over
        threads = os.environ.get("ODW2JSON_OCR_THREADS") or cfg.get("threads")
        if threads and int(threads) > 0:
            params["EngineConfig.onnxruntime.intra_op_num_threads"] = int(threads)
            params["EngineConfig.onnxruntime.inter_op_num_threads"] = 1
        self._engine = RapidOCR(params=params)

    def ocr(self, image: Any) -> list[OcrLine]:
        import numpy as np

        res = self._engine(np.asarray(image.convert("RGB"))[:, :, ::-1])
        if res is None or res.boxes is None or res.txts is None:
            return []
        out: list[OcrLine] = []
        for quad, text, score in zip(res.boxes, res.txts, res.scores):
            xs = [float(p[0]) for p in quad]
            ys = [float(p[1]) for p in quad]
            out.append((text, (min(xs), min(ys), max(xs), max(ys)), float(score)))
        return out


class TesseractBackend:
    """Tesseract via pytesseract (needs the tesseract binary and ``pol`` traineddata; used in Docker)."""

    def __init__(self, cfg: dict):
        import pytesseract

        if not (shutil.which("tesseract") or cfg.get("cmd")):
            raise RuntimeError("tesseract binary not found")
        if cfg.get("cmd"):
            pytesseract.pytesseract.tesseract_cmd = cfg["cmd"]
        self._t = pytesseract
        self._lang = cfg.get("lang", "pol")

    def ocr(self, image: Any) -> list[OcrLine]:
        d = self._t.image_to_data(image, lang=self._lang, output_type=self._t.Output.DICT)
        lines: dict[tuple, list[int]] = {}
        for i, txt in enumerate(d["text"]):
            if txt.strip() and float(d["conf"][i]) >= 0:
                lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(i)
        out: list[OcrLine] = []
        for idx in lines.values():
            x0 = min(d["left"][i] for i in idx)
            y0 = min(d["top"][i] for i in idx)
            x1 = max(d["left"][i] + d["width"][i] for i in idx)
            y1 = max(d["top"][i] + d["height"][i] for i in idx)
            conf = sum(float(d["conf"][i]) for i in idx) / len(idx) / 100.0
            out.append((" ".join(d["text"][i] for i in idx), (x0, y0, x1, y1), conf))
        return out


register_backend("rapidocr", RapidOcrBackend)
register_backend("tesseract", TesseractBackend)
