"""Ingest: PDF -> Document of word-box Pages (text layer or OCR). Public entry point: default_ingestor()."""
from __future__ import annotations

import sys

from odw2json.model import Ingestor

from .layout import build_text, is_garbage_text
from .ocr import OcrBackend, backend_names, get_backend, register_backend
from .pdf import PdfIngestor

for _s in (sys.stdout, sys.stderr):  # Windows consoles default to cp1250/cp1252 and break Polish diacritics
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def default_ingestor(config: dict | None = None) -> Ingestor:
    """Config keys: ocr.backend (env ODW2JSON_OCR overrides), ingest.dpi, ingest.cache, ingest.cache_dir."""
    return PdfIngestor(config=config)


__all__ = [
    "default_ingestor", "PdfIngestor", "OcrBackend", "register_backend", "get_backend", "backend_names",
    "build_text", "is_garbage_text",
]
