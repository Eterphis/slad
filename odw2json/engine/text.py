"""Document text model for matching: lines (with word boxes when known) and a folded, offset-preserving copy.

`fold` is length-preserving (one output char per input char), so a match found in the folded text maps
back to the same offsets in the original text: values and evidence keep their diacritics and case.
"""
from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass

from odw2json.ingest.layout import group_lines
from odw2json.model import Document, Word

_SPECIAL = {"ł": "l", "Ł": "l", "đ": "d", "ø": "o", "ß": "s", " ": " ", "\t": " "}
_DASHES = "‐‑‒–—―−"


def _fold_char(c: str) -> str:
    if c in _SPECIAL:
        return _SPECIAL[c]
    if c in _DASHES:
        return "-"
    low = c.lower()
    base = unicodedata.normalize("NFD", low)[:1] if len(low) == 1 else c
    return base if len(base) == 1 else c


def fold(text: str) -> str:
    """Casefold + strip diacritics, one char per char (offsets stay valid)."""
    return "".join(_fold_char(c) for c in text)


def squash(text: str) -> str:
    """Remove all whitespace (letter-spaced headings, OCR that drops spaces)."""
    return re.sub(r"\s+", "", text)


def collapse(text: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


@dataclass
class Line:
    page: int
    text: str
    words: list[Word] | None  # None when the page has no word boxes
    start: int = 0  # offset of the line in Text.raw

    def word_at(self, offset: int) -> int | None:
        """Index of the word covering a char offset inside the line (words joined by single spaces)."""
        if not self.words:
            return None
        pos = 0
        for i, w in enumerate(self.words):
            end = pos + len(w.text)
            if offset < end + 1:
                return i
            pos = end + 1
        return len(self.words) - 1


class Text:
    """Lines of the whole document; `raw` = lines joined by "\\n" (blank line between blocks), `low` = fold(raw)."""

    def __init__(self, doc: Document):
        self.lines: list[Line] = []
        self.sources = {p.number: p.source for p in doc.pages}
        for page in doc.pages:
            self.lines += _page_lines(page)
        pos = 0
        for ln in self.lines:
            ln.start = pos
            pos += len(ln.text) + 1
        self.raw = "\n".join(ln.text for ln in self.lines)
        self.low = fold(self.raw)
        self._starts = [ln.start for ln in self.lines]

    def line_index(self, offset: int) -> int:
        return max(0, bisect.bisect_right(self._starts, offset) - 1)

    def locate(self, start: int, end: int) -> tuple[int | None, tuple[float, float, float, float] | None]:
        """Page and bbox (union of word boxes) of a raw-text span."""
        if not self.lines:
            return None, None
        i0, i1 = self.line_index(start), self.line_index(max(start, end - 1))
        boxes = []
        for i in range(i0, i1 + 1):
            ln = self.lines[i]
            if not ln.words:
                continue
            a = ln.word_at(max(0, start - ln.start)) if i == i0 else 0
            b = ln.word_at(max(0, end - 1 - ln.start)) if i == i1 else len(ln.words) - 1
            if a is None or b is None:
                continue
            boxes += ln.words[a : b + 1]
        return self.lines[i0].page, bbox(boxes)


def bbox(words: list[Word]) -> tuple[float, float, float, float] | None:
    if not words:
        return None
    return (min(w.x0 for w in words), min(w.y0 for w in words), max(w.x1 for w in words), max(w.y1 for w in words))


def _page_lines(page) -> list[Line]:
    text = unicodedata.normalize("NFC", page.text or "")
    if not page.words:
        return [Line(page.number, t.strip(), None) for t in text.split("\n")]
    groups = group_lines(page.words)
    heights = sorted(max(w.y1 for w in g) - min(w.y0 for w in g) for g in groups)
    median_h = heights[len(heights) // 2] or 1.0
    out: list[Line] = []
    prev_bottom = None
    for g in groups:
        g = [Word(unicodedata.normalize("NFC", w.text), w.x0, w.y0, w.x1, w.y1, w.conf) for w in g if w.text.strip()]
        if not g:
            continue
        top = min(w.y0 for w in g)
        if prev_bottom is not None and top - prev_bottom > median_h:  # same block rule as ingest.layout.build_text
            out.append(Line(page.number, "", []))
        prev_bottom = max(w.y1 for w in g)
        out.append(Line(page.number, " ".join(w.text for w in g), g))
    return out
