"""Page-image cleaning before OCR (config ``ingest.preprocess``).

Modes: ``none`` (off), ``levels`` (always clean), ``auto`` (default): read the page as is; only when many lines
come back with low confidence (show-through, faint print) read it a second time cleaned and keep, line by line,
the better reading. Always-on ``levels`` costs diacritics on clean pages (measured: scan F1 0.9639 -> 0.8546).

``levels``: grayscale, then a levels stretch that maps everything lighter than ~140 to white and everything
darker than ~40 to black. Light show-through from the back of a page (grey, mirrored text) goes to white while
dark print stays; the detector no longer merges the ghost text into the printed lines. The black point adapts
to faint scans (it follows the page's darkest ink up to 110), so light print is not washed out.
Only numpy and OpenCV (both already required) are used.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np

BLACK_POINT = 40.0   # gray level (0..255) that becomes pure black, for a normal dark-ink scan
MAX_BLACK_POINT = 110.0  # faint scans: the black point follows the page's ink up to this level
SPAN = 100.0         # white point = black point + SPAN


def _levels(image: Any) -> Any:
    from PIL import Image

    g = np.asarray(image.convert("L"), dtype=np.float32)
    ink = float(np.percentile(g, 0.5))  # darkest print on this page
    lo = min(max(BLACK_POINT, ink), MAX_BLACK_POINT)
    hi = lo + SPAN
    out = np.clip((g - lo) / (hi - lo), 0.0, 1.0) * 255.0
    return Image.fromarray(out.astype(np.uint8)).convert("RGB")


GOOD_CONF = 0.8     # a line at or above this is trusted as read
RETRY_LINES = 5     # a page with this many shaky lines (conf < GOOD_CONF) gets a second, cleaned pass


def needs_retry(lines: list, good: float = GOOD_CONF, count: int = RETRY_LINES) -> bool:
    """True when a page looks like show-through / faint print: many lines read with low confidence."""
    return sum(1 for _, _, c in lines if c < good) >= count


def _same_line(a: tuple, b: tuple) -> float:
    """Vertical IoU of two boxes that also overlap horizontally (0 when they sit side by side)."""
    if min(a[2], b[2]) <= max(a[0], b[0]):
        return 0.0
    inter = min(a[3], b[3]) - max(a[1], b[1])
    if inter <= 0:
        return 0.0
    return inter / (max(a[3], b[3]) - min(a[1], b[1]))


def shaky_bands(lines: list, height: int, good: float = GOOD_CONF, gap: int = 40) -> list[tuple[int, int]]:
    """Merged (y0, y1) pixel bands around the shaky lines, padded by half a line, clipped to the page."""
    spans = sorted((l[1][1], l[1][3]) for l in lines if l[2] < good)
    bands: list[list[int]] = []
    for y0, y1 in spans:
        pad = int((y1 - y0) / 2)
        y0, y1 = max(0, int(y0) - pad), min(height, int(y1) + pad)
        if bands and y0 <= bands[-1][1] + gap:
            bands[-1][1] = max(bands[-1][1], y1)
        else:
            bands.append([y0, y1])
    return [(a, b) for a, b in bands]


def merge_lines(base: list, cleaned: list, good: float = GOOD_CONF) -> list:
    """Keep trusted baseline lines; a cleaned line replaces the shaky baseline lines it overlaps if it reads better.

    Cleaned lines that overlap nothing in the baseline (text the first pass lost) are added. A cleaned line that
    touches a trusted baseline line is dropped. Both inputs are lists of (text, box, conf).
    """
    out = list(base)
    for line in cleaned:
        hits = [i for i, b in enumerate(out) if _same_line(line[1], b[1]) > 0.5]
        if any(out[i][2] >= good for i in hits):
            continue
        if not hits:
            out.append(line)
        elif line[2] > max(out[i][2] for i in hits):
            keep = [b for i, b in enumerate(out) if i not in hits]
            out = keep + [line]
    return out


PREPROCESSORS: dict[str, Callable[[Any], Any]] = {"levels": _levels}
NAMES = ["none", "auto", *PREPROCESSORS]


def preprocess_image(image: Any, name: str) -> Any:
    """Return the cleaned PIL RGB image; ``none`` (and ``auto``, which cleans only on retry) return the input."""
    if name in ("none", "auto"):
        return image
    try:
        return PREPROCESSORS[name](image)
    except KeyError:
        raise ValueError(f"unknown ingest.preprocess {name!r}; available: {NAMES}") from None
