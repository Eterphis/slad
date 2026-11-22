"""Contract shared by every module of odw2json (ingest -> classify -> extract -> write).

Owned by the coordinator. Tasks code against these types; changing them is a contract change (D-###).
Coordinates are PDF points with the origin at the top-left of the page, for text-layer and OCR words alike.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float = 1.0  # OCR confidence 0..1; 1.0 for words from a text layer


@dataclass
class Page:
    number: int  # 1-based
    width: float
    height: float
    words: list[Word]
    text: str  # page text in reading order, lines separated by "\n" (built by the ingestor)
    source: str  # "text" (PDF text layer) | "ocr"


@dataclass
class Document:
    path: str
    pages: list[Page]

    @property
    def text(self) -> str:
        return "\n\f".join(p.text for p in self.pages)


@dataclass
class Evidence:
    path: str  # JSON path of the field, e.g. "Odwolujacy[0].nip"
    value: Any
    page: int | None = None
    snippet: str | None = None  # source text the value came from
    rule: str | None = None  # which recipe rule / strategy produced it
    confidence: float = 1.0
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class Classification:
    doc_class: str | None  # recipe class name, or None = rejected (no output file is written)
    score: float
    scores: dict[str, float] = field(default_factory=dict)
    reason: str = ""


@dataclass
class Extraction:
    data: dict[str, Any]  # schema-complete JSON object (every key present, null when unknown)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class DocumentResult:
    input_path: str
    output_name: str | None  # "<input basename>.json", or None when rejected
    classification: Classification
    extraction: Extraction | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class Check:
    name: str  # e.g. "pelnomocnictwo.mocodawca == odwolanie.Odwolujacy"
    ok: bool | None  # None = not applicable
    detail: str = ""


@dataclass
class CaseResult:
    case: str  # input sub-folder name
    documents: list[DocumentResult]
    checks: list[Check] = field(default_factory=list)


class Ingestor(Protocol):
    def ingest(self, pdf_path: str) -> Document: ...


class Classifier(Protocol):
    def classify(self, doc: Document) -> Classification: ...


class Extractor(Protocol):
    def extract(self, doc: Document, doc_class: str) -> Extraction: ...
