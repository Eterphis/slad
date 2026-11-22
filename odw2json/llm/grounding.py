"""Grounding: a value read by the model counts only when its quote is found in the page text.

Comparison runs on a folded "skeleton" (lower case, no diacritics, letters and digits only), so the model may drop
or repair punctuation, whitespace and accents without losing a legitimate quote, while a sentence it made up is
never found. Nothing here knows a document class.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from odw2json.model import Document

MIN_QUOTE = 3  # folded characters; shorter quotes prove nothing


def _fold_char(c: str) -> str:
    if c in "łŁ":
        return "l"
    base = unicodedata.normalize("NFD", c.lower())[:1]
    return base if base.isascii() and base.isalnum() else ""


def skeleton(text: str) -> str:
    """Letters and digits only, lower case, diacritics removed."""
    return "".join(_fold_char(c) for c in text)


@dataclass(frozen=True)
class Found:
    page: int
    snippet: str  # the original text span (with its diacritics and line breaks) the quote matched


class _Page:
    def __init__(self, number: int, text: str):
        self.number, self.text = number, text
        chars, offs = [], []
        for i, c in enumerate(text):
            f = _fold_char(c)
            if f:
                chars.append(f)
                offs.append(i)
        self.skel, self.offs = "".join(chars), offs

    def find(self, needle: str) -> str | None:
        i = self.skel.find(needle)
        if i < 0:
            return None
        a, b = self.offs[i], self.offs[i + len(needle) - 1] + 1
        return self.text[a:b]


class PageText:
    """The pages a quote may be found in (the model only ever saw these pages)."""

    def __init__(self, pages: list[tuple[int, str]]):
        self.pages = [_Page(n, t) for n, t in pages]

    @classmethod
    def of(cls, doc: Document, numbers: list[int] | None = None) -> "PageText":
        return cls([(p.number, p.text or "") for p in doc.pages if numbers is None or p.number in numbers])

    def find(self, quote: str | None) -> Found | None:
        """Where the quote occurs, or None (empty, too short, or not in the text)."""
        needle = skeleton(quote or "")
        if len(needle) < MIN_QUOTE:
            return None
        for p in self.pages:
            span = p.find(needle)
            if span is not None:
                return Found(p.number, span)
        return None


def contains_value(quote: str | None, value: str | None) -> bool:
    """The transcribed value must be part of its own quote (otherwise the quote proves nothing about it)."""
    v = skeleton(str(value or ""))
    return bool(v) and v in skeleton(quote or "")
