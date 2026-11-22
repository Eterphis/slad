"""Extraction strategies. Each takes (context, strategy spec, scope) and yields candidates in preference order.

Recipes name them in `use:`. Register more with `register_strategy`. Patterns are matched on folded text
(lower case, no diacritics); candidate text is cut from the original text at the same offsets.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from odw2json.model import Word

from .text import Text, bbox, fold

FLAGS = re.IGNORECASE | re.MULTILINE


@dataclass
class Scope:
    start: int
    end: int


@dataclass
class Candidate:
    value: Any  # raw string (normalised later) or a typed value (lookup/const/derived)
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    snippet: str | None = None


@dataclass
class Context:
    text: Text
    item: dict[str, Any]  # values already set in the current object (for derived)
    dictionary: Callable[[str], list[dict[str, Any]]]


STRATEGIES: dict[str, Callable[[Context, dict, Scope], Iterator[Candidate]]] = {}


def register_strategy(name: str):
    def deco(fn):
        STRATEGIES[name] = fn
        return fn

    return deco


_cache: dict[tuple[str, bool], re.Pattern] = {}


def compile_pattern(pat: str, loose_spaces: bool = False) -> re.Pattern:
    """loose_spaces: a literal space matches any (or no) whitespace (OCR drops and adds spaces)."""
    key = (pat, loose_spaces)
    if key not in _cache:
        src = re.sub(r"(?<!\\) ", r"\\s*", pat) if loose_spaces else pat
        _cache[key] = re.compile(src, FLAGS)
    return _cache[key]


def _group_span(m: re.Match) -> tuple[int, int]:
    if "v" in m.re.groupindex and m.group("v") is not None:
        return m.span("v")
    if m.re.groups and m.group(1) is not None:
        return m.span(1)
    return m.span(0)


def _span_candidate(t: Text, a: int, b: int) -> Candidate:
    page, box = t.locate(a, b)
    ls = t.raw.rfind("\n", 0, a) + 1
    le = t.raw.find("\n", b)
    return Candidate(t.raw[a:b], page, box, t.raw[ls : le if le >= 0 else len(t.raw)].strip()[:300])


@register_strategy("regex")
def regex(ctx: Context, spec: dict, scope: Scope) -> Iterator[Candidate]:
    t = ctx.text
    if spec.get("raw"):  # case-sensitive on the original text (e.g. capitalised person names)
        pat, hay = re.compile(spec["pattern"], re.MULTILINE), t.raw
    else:
        pat, hay = compile_pattern(spec["pattern"]), t.low
    spans = [_group_span(m) for m in pat.finditer(hay, scope.start, scope.end)]
    spans = [(a, b) for a, b in spans if b > a]
    if "nth" in spec:  # only the n-th distinct value (0 = first, -1 = last), e.g. sender then recipient account
        seen: dict[str, tuple[int, int]] = {}
        for a, b in spans:
            seen.setdefault(re.sub(r"\s+", "", hay[a:b]), (a, b))
        picked = list(seen.values())
        n = int(spec["nth"])
        spans = [picked[n]] if -len(picked) <= n < len(picked) else []
    for a, b in spans:
        yield _span_candidate(t, a, b)


def join_lines(s: str) -> str:
    s = re.sub(r"(\w)-\n(\w)", lambda m: m[1] + m[2] if m[2].islower() else m[0].replace("\n", ""), s)
    return re.sub(r"\s+", " ", s).strip()


@register_strategy("between")
def between(ctx: Context, spec: dict, scope: Scope) -> Iterator[Candidate]:
    t = ctx.text
    end_pat = compile_pattern(spec["end"]) if spec.get("end") else re.compile(r"\n[ \t]*\n")
    for m in compile_pattern(spec["start"]).finditer(t.low, scope.start, scope.end):
        e = end_pat.search(t.low, m.end(), scope.end)
        b = e.start() if e else scope.end
        a = m.end()
        while a < b and t.raw[a].isspace():
            a += 1
        if b > a:
            c = _span_candidate(t, a, b)
            c.value = join_lines(c.value)
            yield c


def _lines_in(t: Text, scope: Scope) -> list[int]:
    if not t.lines:
        return []
    return list(range(t.line_index(scope.start), t.line_index(max(scope.start, scope.end - 1)) + 1))


def _col_gap(words: list[Word]) -> float:
    h = sorted(w.y1 - w.y0 for w in words)[len(words) // 2] if words else 10.0
    return max(12.0, 1.5 * h)


def _value_match(spec: dict, text: str) -> tuple[int, int] | None:
    if not text.strip():
        return None
    if spec.get("value") is None:
        a = len(text) - len(text.lstrip(" :\t-–"))
        return (a, len(text.rstrip())) if text.strip(" :\t-–") else None
    m = compile_pattern(spec["value"]).search(fold(text))
    if not m:
        return None
    return m.span("v") if "v" in m.re.groupindex and m.group("v") is not None else m.span(0)


def _words_candidate(words: list[Word], spec: dict, page: int, snippet: str) -> Candidate | None:
    text = " ".join(w.text for w in words)
    span = _value_match(spec, text)
    if not span:
        return None
    pos, picked = 0, []
    for w in words:
        if pos < span[1] and pos + len(w.text) > span[0]:
            picked.append(w)
        pos += len(w.text) + 1
    return Candidate(text[span[0] : span[1]], page, bbox(picked), snippet)


def _column(words: list[Word], x0: float, x1: float) -> list[Word]:
    return [w for w in words if x0 - 12 <= w.x0 < x1]


def _continue(t: Text, i: int, n: int, x0: float | None = None, x1: float = float("inf")) -> list[list[Word]] | list[str]:
    """Up to n following lines that continue a value: plain text lines, or (with x0) the words of each line
    inside the column [x0, x1) whose first word is aligned at x0."""
    out: list = []
    for ln in t.lines[i + 1 :]:
        if len(out) >= n or not ln.text.strip():
            break
        if x0 is None:
            out.append(ln.text)
            continue
        col = _column(ln.words or [], x0, x1)
        if not col or abs(col[0].x0 - x0) > 8:
            break
        out.append(col)
    return out


_LABEL_END = r"(?:(?<=\W)|(?!\w))"


@register_strategy("after_label")
def after_label(ctx: Context, spec: dict, scope: Scope) -> Iterator[Candidate]:
    """Value right of the label on its line (up to the next column gap), else below in the label's column."""
    t = ctx.text
    labels = [compile_pattern(p, loose_spaces=True) for p in spec["labels"]]
    # pages without word boxes: the label must end at a word boundary ("nr ref" is not the start of "referencyjny")
    plain_labels = [compile_pattern(p + _LABEL_END, loose_spaces=True) for p in spec["labels"]]
    extra = int(spec.get("max_lines", 1)) - 1
    idx = _lines_in(t, scope)
    for k, i in enumerate(idx):
        ln = t.lines[i]
        low = t.low[ln.start : ln.start + len(ln.text)]
        for lab, plain in zip(labels, plain_labels):
            m = (lab if ln.words else plain).search(low)
            if not m:
                continue
            if not ln.words:  # plain text: rest of the line, else the next non-empty line
                rest = ln.text[m.end() :]
                more = _continue(t, i, extra) if extra else []
                span = _value_match(spec, " ".join([rest] + more))
                if span:
                    yield Candidate(" ".join([rest] + more)[span[0] : span[1]], ln.page, None, ln.text)
                nxt = next((t.lines[j] for j in idx[k + 1 :] if t.lines[j].text.strip()), None)
                if spec.get("below", True) and nxt is not None:
                    span = _value_match(spec, nxt.text)
                    if span:
                        yield Candidate(nxt.text[span[0] : span[1]], nxt.page, None, f"{ln.text} / {nxt.text}")
                continue
            words = ln.words
            first = ln.word_at(m.start())
            last = ln.word_at(max(m.start(), m.end() - 1))
            gap = _col_gap(words)
            right = words[last + 1 :]
            # the first gap separates label and value; the next big gap starts another column
            cut = next((j for j in range(1, len(right)) if right[j].x0 - right[j - 1].x1 > gap), len(right))
            value_words, next_col = right[:cut], right[cut:]
            if value_words and value_words[0].x0 - words[last].x1 > gap and not _value_match(spec, " ".join(w.text for w in value_words)):
                next_col = right  # a lone label followed by another column's label: nothing on the right
                value_words = []
            x1 = next_col[0].x0 - 4 if next_col else float("inf")
            if value_words:
                cont = _continue(t, i, extra, value_words[0].x0, x1) if extra else []
                c = _words_candidate(value_words + [w for x in cont for w in x], spec, ln.page, ln.text)
                if c:
                    yield c
            if not spec.get("below", True):
                continue
            x0 = words[first].x0
            for j in idx[k + 1 :]:
                below = t.lines[j]
                if not below.text.strip() or not below.words:
                    continue
                col = _column(below.words, x0, x1)
                if not col:
                    break
                lines = [col] + (_continue(t, j, extra, col[0].x0, x1) if extra else [])
                c = _words_candidate([w for x in lines for w in x], spec, below.page, f"{ln.text} / {below.text}")
                if c:
                    yield c
                break


@register_strategy("lookup")
def lookup(ctx: Context, spec: dict, scope: Scope) -> Iterator[Candidate]:
    """Dictionary entry whose trigger phrase occurs first in the scope; yields entry[return] (default id)."""
    t = ctx.text
    best = None
    for entry in ctx.dictionary(spec["dictionary"]):
        for trig in entry["triggers"]:
            m = compile_pattern(fold(str(trig)), loose_spaces=True).search(t.low, scope.start, scope.end)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), m.end(), entry)
    if best:
        c = _span_candidate(t, best[0], best[1])
        c.value = best[2].get(spec.get("return", "id"))
        if c.value is not None:
            yield c


@register_strategy("const")
def const(ctx: Context, spec: dict, scope: Scope) -> Iterator[Candidate]:
    yield Candidate(spec["value"], snippet="const")


def get_path(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(obj, list):
            obj = obj[0] if obj else None
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part.removesuffix("[]"))
    return obj


@register_strategy("derived")
def derived(ctx: Context, spec: dict, scope: Scope) -> Iterator[Candidate]:
    v = spec.get("value", 1) if get_path(ctx.item, spec["if_set"]) is not None else spec.get("else")
    if v is not None:
        yield Candidate(v, snippet=f"derived from {spec['if_set']}")


def _segments(ln) -> list[tuple[int, int]]:
    """Char spans of a line's column segments: split at big word gaps (word boxes) or at 2+ spaces/tabs."""
    if ln.words:
        gap, spans, pos, a = _col_gap(ln.words), [], 0, 0
        for j, w in enumerate(ln.words):
            if j and w.x0 - ln.words[j - 1].x1 > gap:
                spans.append((a, pos - 1))
                a = pos
            pos += len(w.text) + 1
        spans.append((a, len(ln.text)))
        return spans
    return [(m.start(), m.end()) for m in re.finditer(r"\S+(?: \S+)*", ln.text)]


def _match(pat: str, text: str, raw: bool, start: bool = False):
    p = re.compile(pat, re.MULTILINE) if raw else compile_pattern(pat)
    s = text if raw else fold(text)
    return p.match(s) if start else p.search(s)


@register_strategy("segments")
def segments(ctx: Context, spec: dict, scope: Scope) -> Iterator[Candidate]:
    """Values inside the column segments of each line in scope (signature blocks, tables without labels).

    Every match of `value` in a segment is a candidate (named group 'v' or the whole match) unless the segment
    matches one of `exclude` at its start or one of `not_after` matches the text right before the value.
    `raw: true` matches `value` case-sensitively on the original text (e.g. capitalised person names)."""
    t = ctx.text
    raw = bool(spec.get("raw"))
    excl = spec.get("exclude", [])
    not_after = [compile_pattern(p + r"\s*$") for p in spec.get("not_after", [])]
    val = re.compile(spec["value"], re.MULTILINE) if raw else compile_pattern(spec["value"])
    for i in _lines_in(t, scope):
        ln = t.lines[i]
        if not ln.text.strip() or ln.start + len(ln.text) <= scope.start or ln.start >= scope.end:
            continue
        for a, b in _segments(ln):
            seg = ln.text[a:b]
            if not seg.strip() or any(_match(p, seg.lstrip(" .…_"), False, start=True) for p in excl):
                continue
            for m in val.finditer(seg if raw else fold(seg)):
                va, vb = _group_span(m)
                if vb <= va or any(p.search(fold(seg[:va])) for p in not_after):
                    continue
                yield _span_candidate(t, ln.start + a + va, ln.start + a + vb)
