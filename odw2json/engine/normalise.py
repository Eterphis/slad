"""Normalisers (raw string -> value, None = not a valid value) and soft validators (value -> bool).

Recipes refer to them by name. Register more with `register_normaliser` / `register_validator`.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable

from .text import fold

NORMALISERS: dict[str, Callable[[str], Any]] = {}
VALIDATORS: dict[str, Callable[[Any], bool]] = {}


def register_normaliser(name: str):
    def deco(fn):
        NORMALISERS[name] = fn
        return fn

    return deco


def register_validator(name: str):
    def deco(fn):
        VALIDATORS[name] = fn
        return fn

    return deco


_MONTHS = {  # folded stems of Polish month names (genitive and nominative), and Roman numerals
    "stycz": 1, "lut": 2, "marz": 3, "marc": 3, "kwie": 4, "maj": 5, "czerw": 6, "lip": 7, "sierp": 8,
    "wrze": 9, "pazdz": 10, "listop": 11, "grud": 12,
}
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12}


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


@register_normaliser("date_pl")
def date_pl(s: str) -> str | None:
    t = fold(s)
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        return _iso(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})", t)
    if m:
        return _iso(int(m[3]), int(m[2]), int(m[1]))
    m = re.search(r"(?<!\d)(\d{1,2})\s+(\d{1,2})\s+(\d{4})(?!\d)", t)  # "20 04 2026" (separators lost by OCR)
    if m:
        return _iso(int(m[3]), int(m[2]), int(m[1]))
    m = re.search(r"(\d{1,2})[\s.]*([a-z]+)[\s.]*(\d{4})", t)
    if m:
        word = m[2]
        month = _ROMAN.get(word) or next((v for k, v in _MONTHS.items() if word.startswith(k)), None)
        if month:
            return _iso(int(m[3]), month, int(m[1]))
    return None


@register_normaliser("amount_pl")
def amount_pl(s: str) -> float | None:
    m = re.search(r"\d[\d  .]*(?:,\d{1,2})?|\d+(?:\.\d{1,2})?", s)
    if not m:
        return None
    num = m.group(0).replace(" ", "").replace(" ", "").strip(".")
    if "," in num:
        num = num.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", num):  # 1.234 = thousands
        num = num.replace(".", "")
    try:
        return float(num)
    except ValueError:
        return None


@register_normaliser("digits")
def digits(s: str) -> str | None:
    d = re.sub(r"\D", "", s)
    return d or None


@register_normaliser("int")
def to_int(s: Any) -> int | None:
    if isinstance(s, int):
        return s
    m = re.search(r"\d+", str(s))
    return int(m.group(0)) if m else None


@register_normaliser("iban_pl")
def iban_pl(s: str) -> str | None:
    d = re.sub(r"[^0-9]", "", re.sub(r"(?i)^\s*PL", "", s.strip()))
    return d if len(d) == 26 else None


@register_normaliser("ted")
def ted(s: str) -> str | None:
    m = re.search(r"(\d{4})\s*/\s*S\s*\d{1,3}\s*-\s*(\d{6})", s)
    if m:
        return f"{m[2]}-{m[1]}"
    m = re.search(r"(\d{5,6})\s*-\s*(\d{4})", s)
    return f"{m[1]}-{m[2]}" if m else None


@register_normaliser("bzp")
def bzp(s: str) -> str | None:
    v = re.sub(r"\s+", "", s)
    return v or None


@register_normaliser("strip")
def strip(s: str) -> str | None:
    v = re.sub(r"\s+", " ", s).strip(" \t,;:")
    return v or None


@register_normaliser("unquote")
def unquote(s: str) -> str | None:
    quotes = " \t,;:\"'„”“»«"
    v = re.sub(r"\s+", " ", s).strip(quotes)
    if v.endswith(".") and any(q in s for q in "\"„”“»«"):  # „title”. -> title (a sentence-final dot after the quote)
        v = v.rstrip(".").strip(quotes)
    return v or None


@register_normaliser("flag")
def flag(s: str) -> int | None:
    """1 when a marker phrase was found (the matched text is irrelevant), e.g. "prowadzący postępowanie"."""
    return 1 if s and s.strip() else None


@register_normaliser("upper")
def upper(s: str) -> str | None:
    return strip(s.upper()) if s else None


@register_normaliser("title")
def title(s: str) -> str | None:
    v = strip(s)
    return " ".join(w[:1].upper() + w[1:].lower() for w in v.split(" ")) if v else None


@register_normaliser("ocr_digits")
def ocr_digits(s: str) -> str | None:
    """Digits of an identifier read by OCR: letters that look like digits (o/O -> 0, l/I/| -> 1) are mapped first."""
    return digits(s.translate(str.maketrans("oOlI|", "00111")))


# OCR drops the space between two name words: "HalinaBaran" -> "Halina Baran". Both parts start upper-case and have at
# least two letters. Only the `person` normaliser does this: company names ("BudMax"), e-mails and URLs keep theirs.
_UP, _LOW = "A-ZĄĆĘŁŃÓŚŹŻ", "a-ząćęłńóśźż"
_GLUED_NAME = re.compile(rf"(?:[{_UP}][{_LOW}]+){{2,}}")
_NAME_WORD = re.compile(rf"[{_UP}][{_LOW}]+")


def _split_glued(token: str) -> str:
    if not _GLUED_NAME.fullmatch(token) or token.startswith(("Mc", "Mac")):
        return token
    return " ".join(_NAME_WORD.findall(token))


@register_normaliser("person")
def person(s: str) -> str | None:
    """A person's name: whitespace collapsed; ALL-CAPS ("JAN KOWALSKI-NOWAK") -> "Jan Kowalski-Nowak"."""
    v = strip(s)
    if not v:
        return v
    if v != v.upper():
        return " ".join("-".join(_split_glued(t) for t in w.split("-")) for w in v.split(" "))
    return re.sub(r"[^\W\d_]+", lambda m: m[0][0] + m[0][1:].lower(), v)


@register_normaliser("company")
def company(s: str) -> str | None:
    """A company name with common OCR slips in the legal form fixed ("Sp. z 0.o." -> "Sp. z o.o.")."""
    v = strip(s)
    if not v:
        return v
    v = re.sub(r"\b([zZ])\s*[0oO]\s*\.\s*[0oO]\s*\.", r"\1 o.o.", v)
    return v.strip(' "„”')


def _weighted(d: str, weights: list[int], mod: int) -> int:
    return sum(int(a) * b for a, b in zip(d, weights)) % mod


@register_validator("nip")
def nip_ok(v: Any) -> bool:
    d = re.sub(r"\D", "", str(v))
    return len(d) == 10 and _weighted(d, [6, 5, 7, 2, 3, 4, 5, 6, 7], 11) == int(d[9])


@register_validator("regon")
def regon_ok(v: Any) -> bool:
    d = re.sub(r"\D", "", str(v))
    if len(d) == 9:
        return _weighted(d, [8, 9, 2, 3, 4, 5, 6, 7], 11) % 10 == int(d[8])
    if len(d) == 14:
        return _weighted(d, [2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8], 11) % 10 == int(d[13])
    return False


@register_validator("pesel")
def pesel_ok(v: Any) -> bool:
    d = re.sub(r"\D", "", str(v))
    if len(d) != 11:
        return False
    return (10 - sum(int(a) * b for a, b in zip(d, [1, 3, 7, 9, 1, 3, 7, 9, 1, 3])) % 10) % 10 == int(d[10])


@register_validator("krs")
def krs_ok(v: Any) -> bool:
    return bool(re.fullmatch(r"\d{10}", re.sub(r"\s", "", str(v))))


@register_validator("iban")
def iban_ok(v: Any) -> bool:
    d = re.sub(r"\D", "", str(v))
    if len(d) != 26:
        return False
    return int(d[2:] + "2521" + d[:2]) % 97 == 1  # PL = 25 21


_OCR_LETTERS = str.maketrans("ñÑ", "ńŃ")  # OCR reads the acute accent as a tilde
_PL_LETTERS = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
_FOLD_PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
_words_cache: dict[tuple[str, float], dict[str, str]] = {}


@register_normaliser("ocr_text")
def ocr_text(s: str) -> str | None:
    """Free text read by OCR: tilde letters -> Polish letters (Ñ -> Ń); a colon misread for the dot inside a
    case number ("DA.ZP:242.13.2026" -> "DA.ZP.242.13.2026")."""
    v = strip(s.translate(_OCR_LETTERS))
    if not v:
        return v
    return re.sub(r"\S+", lambda m: re.sub(r"(?<=[A-Za-z]):(?=\d)", ".", m[0]) if "." in m[0] else m[0], v)


def _polish_words() -> dict[str, set[str]]:
    """folded lower-case word -> its Polish spellings (usually one), from dictionaries/polish_words.txt (see build_polish_words.py)."""
    from .recipes import dictionaries_dir

    path = dictionaries_dir() / "polish_words.txt"
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return {}
    if key not in _words_cache:
        words = path.read_text(encoding="utf-8").split()
        _words_cache.clear()
        table: dict[str, set[str]] = {}
        for w in words:
            table.setdefault(w.translate(_FOLD_PL), set()).add(w)
        _words_cache[key] = table
    return _words_cache[key]


@register_normaliser("restore_diacritics")
def restore_diacritics(s: str) -> str | None:
    """Text whose Polish letters OCR dropped ("odwolania"): every plain-ASCII word that the domain word list knows
    with diacritics gets them back, keeping its case (ALL CAPS, Capitalised, lower); a word with wrong accents is
    repaired the same way. Unknown words stay as they are."""
    words = _polish_words()

    def fix(m: re.Match) -> str:
        w = m[0]
        key = w.lower().translate(_FOLD_PL)  # also repairs wrong accents ("Lódź" -> "Łódź")
        forms = words.get(key) or (words.get(key.replace("q", "a")) if "q" in key else None)  # OCR: ogonek read as q
        if not forms or w.lower() in forms or len(forms) > 1:  # unknown, already right, or ambiguous (usługa / usługą)
            return w
        good = next(iter(forms))
        return good.upper() if len(w) > 1 and w.isupper() else good.capitalize() if w[0].isupper() else good

    return re.sub(r"[^\W\d_]+", fix, s) if s else s
