"""Merging duplicate names in a list (`dedupe:` on a recipe field).

The same person is often read twice: once in capitals and once in mixed case, or with one letter OCR got wrong
("Zawadżki" in the body, "Zawadzki" at the signature). Two names are the same when they are equal after folding
(casefold, no diacritics, one space) or, with `fuzzy: N`, differ by at most N characters.
"""
from __future__ import annotations

import re

from .text import fold


def key(name: str) -> str:
    return re.sub(r"\s+", " ", fold(str(name))).strip()


def _within(a: str, b: str, limit: int) -> bool:
    """Levenshtein distance a..b <= limit (small limits, short strings)."""
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= limit


def same_name(a: str, b: str, fuzzy: int = 0) -> bool:
    ka, kb = key(a), key(b)
    return ka == kb or (fuzzy > 0 and _within(ka, kb, fuzzy))


def prefer(old: str, new: str) -> str:
    """The form to keep for one person: mixed case beats ALL CAPS / lower case; on a tie the later one (the signature)."""
    def mixed(s: str) -> bool:
        return s != s.upper() and s != s.lower()

    return old if mixed(old) and not mixed(new) else new


def dedupe_names(names: list[str], fuzzy: int = 0) -> list[str]:
    """Names in document order, one per person, at the position of the first mention."""
    return [n for n, _ in dedupe_items([(n, None) for n in names], fuzzy)]


def dedupe_items(items: list[tuple[str, object]], fuzzy: int = 0) -> list[tuple[str, object]]:
    """(name, payload) pairs; the payload (e.g. evidence) follows the name that is kept."""
    out: list[tuple[str, object]] = []
    for name, payload in items:
        for i, (old, _) in enumerate(out):
            if same_name(old, name, fuzzy):
                if prefer(old, name) is name:
                    out[i] = (name, payload)
                break
        else:
            out.append((name, payload))
    return out
