"""STUBS (T001). Replaced by T003 (ingest: text layer + OCR + word boxes) and T004 (classify/extract recipes)."""
from __future__ import annotations

import re

from .model import Classification, Document, Extraction, Page
from .write import skeleton


class PdfplumberIngestor:
    """STUB: pdfplumber page text only, no OCR, no word boxes."""

    def __init__(self) -> None:
        import pdfplumber  # a missing dependency must fail at start-up, not per document

        self._pdfplumber = pdfplumber

    def ingest(self, pdf_path: str) -> Document:
        pdfplumber = self._pdfplumber

        pages: list[Page] = []
        with pdfplumber.open(pdf_path) as pdf:
            for i, pg in enumerate(pdf.pages, 1):
                pages.append(Page(i, float(pg.width), float(pg.height), [], pg.extract_text() or "", "text"))
        return Document(str(pdf_path), pages)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


class KeywordClassifier:
    """STUB: weighted keyword scores; signals near the document start weigh most.
    Ties are broken by priority odwolanie > przelew > pelnomocnictwo; no signal -> reject."""

    PRIORITY = ("odwolanie", "przelew", "pelnomocnictwo")

    def classify(self, doc: Document) -> Classification:
        t = _norm(doc.text)
        squashed = t.replace(" ", "")  # headings are sometimes letter-spaced: "P E Ł N O M O C N I C T W O"
        head, shead = t[:600], squashed[:600]
        scores = {
            "odwolanie": 3.0 * bool(re.search(r"(?m)^(prezes )?krajow(a|ej) izb", doc.text.lower()[:600]))
            + 2.0 * ("odwołujący:" in head)
            + 0.5 * ("krajowej izby" in t)
            + 0.5 * ("odwołanie" in t or "odwolanie" in t),
            "przelew": 3.0 * ("przelew" in head)
            + 1.0 * ("potwierdzenie" in head)
            + 1.0 * ("na rachunek" in t or "rachunek nadawcy" in t or "rachunek obciążany" in t)
            + 1.0 * ("dane nadawcy" in t)
            + 0.5 * ("kwota" in t),
            "pelnomocnictwo": 2.0 * ("pełnomocnictw" in shead or "pelnomocnictw" in shead)
            + 2.0 * ("pełnomocnictw" in squashed[:80]),  # a title right at the top
        }
        best = max(self.PRIORITY, key=lambda k: scores[k])  # max keeps the first of equals
        if scores[best] < 2:
            return Classification(None, 0.0, scores, "no keyword matched")
        return Classification(best, scores[best], scores, "keyword stub")


class SkeletonExtractor:
    """STUB: returns the null skeleton."""

    def extract(self, doc: Document, doc_class: str) -> Extraction:
        return Extraction(skeleton(doc_class))
