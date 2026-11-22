"""LlmExtractor: the recipe engine plus the grounded reader, behind the same Extractor interface."""
from __future__ import annotations

import dataclasses
import json
import logging
import os
from typing import Any

from odw2json.engine.engine import _sections
from odw2json.engine.text import Text
from odw2json.model import Classification, Document, Extraction

from .plan import Plan, build_plan
from .reader import Decision, LlmReader
from .runtime import LlamaCppRuntime, Runtime, RuntimeUnavailable

log = logging.getLogger("odw2json.llm")


class LlmExtractor:
    """Classifier and Extractor of the wrapped engine (`engine.classify/extract/recipes/dictionary`); after the
    recipes ran, fields that opt in with `llm:` and are still empty or weak are read by the local model.
    If the model cannot run (no weights, no runtime) the recipe output is returned unchanged."""

    def __init__(self, engine, runtime: Runtime):
        self.engine = engine
        self.reader = LlmReader(runtime)
        self._plans: dict[tuple, Plan] = {}
        self._broken: str | None = None
        self.last: list[Decision] = []

    def classify(self, doc: Document) -> Classification:
        return self.engine.classify(doc)

    def _plan(self, doc_class: str) -> Plan:
        recipe = self.engine.recipes[doc_class]
        key = (doc_class, self.engine._sig)
        if key not in self._plans:
            self._plans[key] = build_plan(recipe.spec, self.engine.dictionary)
        return self._plans[key]

    def extract(self, doc: Document, doc_class: str) -> Extraction:
        ext = self.engine.extract(doc, doc_class)
        self.last = []
        plan = self._plan(doc_class)
        if not plan or self._broken:
            return ext
        text = Text(doc)
        sections = {n: text.raw[s.start : s.end] for n, s in _sections(self.engine.recipes[doc_class], text).items()}
        try:
            self.last = self.reader.read(doc, ext, plan, sections)
        except RuntimeUnavailable as e:
            self._broken = str(e)
            log.warning("LLM reader disabled, recipe output kept: %s", e)
        self._trace(doc, doc_class)
        return ext

    def _trace(self, doc: Document, doc_class: str) -> None:
        path = os.environ.get("ODW2JSON_LLM_TRACE")
        if not path or not self.last:
            return
        row: dict[str, Any] = {"doc": os.path.basename(doc.path), "class": doc_class, "model": self.reader.runtime.name, "decisions": [dataclasses.asdict(d) for d in self.last]}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_extractor(engine, model: str, n_ctx: int = 4096, threads: int | None = None) -> LlmExtractor:
    """Profile hook: `reader: {kind: llm, model: models/<file>.gguf}`."""
    return LlmExtractor(engine, LlamaCppRuntime(model, n_ctx=n_ctx, n_threads=threads))
