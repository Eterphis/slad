"""Builds dictionaries/polish_words.txt, the word list of the `restore_diacritics` normaliser.

Sources: the string values of the example answer files (public training data: dane/przyklad_*, dane/skany) and
dictionaries/polish_words.extra.txt (hand-written domain words: opłata, pełnomocnictwo, ...).
A word is kept when it has Polish letters and its plain-ASCII spelling is not itself used as a word anywhere in the
sources ("lad" next to "ład" would make restoring unsafe).

    python dictionaries/build_polish_words.py <dane folder> [--no-scans]
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
PL = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
_MAP = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def fold(w: str) -> str:
    return unicodedata.normalize("NFC", w).translate(_MAP)


def strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


def words(text: str):
    text = re.sub(r"\S+@\S+", " ", text)  # e-mail addresses are ASCII by nature
    return re.findall(r"[^\W\d_]{3,}", text)


def main(root: str) -> None:
    seen: set[str] = set()
    files = sorted(Path(root).glob("przyklad_*/*.json"))
    if "--no-scans" not in sys.argv:
        files += sorted(Path(root).glob("skany/*/*/*.json"))
    for f in files:
        for s in strings(json.loads(f.read_text(encoding="utf-8"))):
            seen.update(w.lower() for w in words(s))
    extra = HERE / "polish_words.extra.txt"
    if extra.exists():
        seen.update(w.strip().lower() for w in extra.read_text(encoding="utf-8").split() if len(w.strip()) >= 3)
    plain = {w for w in seen if not any(c in PL for c in w)}
    out = sorted(w for w in seen if any(c in PL for c in w) and fold(w) not in plain)
    (HERE / "polish_words.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(len(out), "words")


if __name__ == "__main__":
    main(sys.argv[1])
