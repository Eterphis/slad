"""Reading-order text from word boxes, and a garbage detector for text layers."""
from __future__ import annotations

import re

from odw2json.model import Word

MIN_CHARS = 20
MIN_LETTER_RATIO = 0.6
MAX_BAD_RATIO = 0.05
_LINE_OVERLAP = 0.5  # a word joins a line when it overlaps the line's y-range by this share of the smaller height
_BLOCK_GAP = 1.0  # blank line when the gap between lines exceeds this many median line heights
_COLUMN_GAP = 0.8  # a label is a column header when the gap after it exceeds this many line heights
_DECORATION = frozenset("-_.=*~|+—–…")
_CID =re.compile(r"\(cid:\d+\)")


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)


def group_lines(words: list[Word]) -> list[list[Word]]:
    """Cluster words into lines by vertical position; each line sorted by x, lines sorted by y.

    A word joins a line when its vertical centre is within half of the smaller height (word vs. the line's
    typical word) of the line's centre. The line's band does not grow with each word: on scans a slightly skewed
    OCR line has a tall box, and a growing union of boxes used to swallow the neighbouring lines. A word that
    overlaps a word already in the line horizontally belongs to another line.
    """
    lines: list[list] = []  # [sum of centres, count, typical height, words]
    for word in sorted(words, key=lambda x: (x.y0 + x.y1) / 2):
        cy, h = (word.y0 + word.y1) / 2, word.y1 - word.y0
        placed = False
        for line in reversed(lines[-8:]):
            lcy, lh = line[0] / line[1], line[2]
            tol = _LINE_OVERLAP * min(h, lh) if h > 0 and lh > 0 else 0
            # words of one visual line never overlap horizontally: an overlap means a neighbouring line
            if abs(cy - lcy) <= tol and not any(w.x0 < word.x1 - 1 and word.x0 < w.x1 - 1 for w in line[3]):
                line[0] += cy
                line[1] += 1
                line[3].append(word)
                placed = True
                break
        if not placed:
            lines.append([cy, 1, h, [word]])
    lines.sort(key=lambda ln: ln[0] / ln[1])
    return _label_before_block([sorted(ln[3], key=lambda x: x.x0) for ln in lines])


def _height(line: list[Word]) -> float:
    return max(w.y1 for w in line) - min(w.y0 for w in line)


def _label_before_block(lines: list[list[Word]]) -> list[list[Word]]:
    """Two-column header: a label centred beside a wrapped value reads before the whole value.

    Reading order puts the label on the line where the value's vertical middle is, so the value starts above it. A
    line that starts with a short `label:` word, then a wide column gap and the value column, takes the label off and
    puts it in front of the directly preceding lines that start at that value column (at most four, touching).
    """
    out = list(lines)
    i = 1
    while i < len(out):
        ln = out[i]
        h = _height(ln)
        if len(ln) >= 2 and ln[0].text.endswith(":") and ln[1].x0 - ln[0].x1 > _COLUMN_GAP * h:
            vx, tol = ln[1].x0, 0.5 * h
            j, top = i, min(w.y0 for w in ln)
            while j > 0 and i - j < 4:
                prev = out[j - 1]
                if (abs(prev[0].x0 - vx) > tol or top - max(w.y1 for w in prev) > 0.5 * h
                        or prev[0].text.endswith(":")):
                    break
                j, top = j - 1, min(w.y0 for w in prev)
            if j < i:
                out[j] = [ln[0]] + out[j]
                out[i] = ln[1:]
        i += 1
    return out


def build_text(words: list[Word]) -> str:
    """Page text: one line per visual line, blank line between blocks, hyphenated line ends joined.

    Hyphen joining affects only this string, never the word boxes.
    """
    if not words:
        return ""
    lines = group_lines(words)
    heights = sorted(max(w.y1 for w in ln) - min(w.y0 for w in ln) for ln in lines)
    median_h = heights[len(heights) // 2] or 1.0
    out: list[str] = []
    prev_bottom = None
    for ln in lines:
        top = min(w.y0 for w in ln)
        bottom = max(w.y1 for w in ln)
        text = " ".join(w.text for w in ln)
        if prev_bottom is not None:
            gap = top - prev_bottom
            if gap > _BLOCK_GAP * median_h:
                out.append("")
        prev_bottom = bottom
        if out and out[-1] != "" and _joins(out[-1], text):
            out[-1] = out[-1][:-1] + text
        else:
            out.append(text)
    return "\n".join(out)


def _joins(prev: str, nxt: str) -> bool:
    """Hyphen at the end of prev glued to a lowercase letter-continuation at the start of nxt."""
    return len(prev) >= 2 and prev[-1] == "-" and prev[-2].isalpha() and nxt[:1].isalpha() and nxt[:1].islower()


def is_garbage_text(text: str) -> bool:
    """True when a text layer is empty, too short, mostly non-letters or has broken encoding."""
    compact = "".join(text.split())
    if len(compact) < MIN_CHARS:
        return True
    cid = sum(len(m.group(0)) for m in _CID.finditer(compact))
    bad = sum(1 for c in compact if c == "\ufffd" or (ord(c) < 32) or 0xE000 <= ord(c) <= 0xF8FF) + cid
    if bad / len(compact) > MAX_BAD_RATIO:
        return True
    # rules and signature lines ("-----", ".....", "_____") are layout, not content: leave them out of the ratio
    body = [c for c in compact if c not in _DECORATION]
    if len(body) < MIN_CHARS // 2:
        return True
    return sum(1 for c in body if c.isalnum()) / len(body) < MIN_LETTER_RATIO
