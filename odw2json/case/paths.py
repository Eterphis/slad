"""Tiny JSON path language: `a.b[*].c`, `a[0].b`. A dict where a list is expected is treated as a 1-item list."""
from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(r"^([^\[\]]+)(?:\[(\*|\d+)\])?$")


def _tokens(path: str) -> list[tuple[str, str | None]]:
    out = []
    for part in path.split("."):
        m = _TOKEN.match(part)
        if not m:
            raise ValueError(f"bad path {path!r}")
        out.append((m.group(1), m.group(2)))
    return out


def expand(data: Any, path: str) -> list[tuple[str, Any]]:
    """All (concrete path, value) pairs the path addresses; missing keys are skipped, null values kept."""
    found: list[tuple[str, Any]] = [("", data)]
    for key, idx in _tokens(path):
        nxt: list[tuple[str, Any]] = []
        for p, v in found:
            if not isinstance(v, dict) or key not in v:
                continue
            child, base = v[key], (p + "." if p else "") + key
            if idx is None:
                nxt.append((base, child))
                continue
            items = child if isinstance(child, list) else [child]
            for i, item in enumerate(items):
                if idx == "*" or int(idx) == i:
                    nxt.append((f"{base}[{i}]", item))
        found = nxt
    return found


def assign(data: Any, concrete: str, value: Any) -> bool:
    """Set the value at a concrete path (as returned by `expand`); False if it does not exist."""
    toks = _tokens(concrete)
    cur = data
    for n, (key, idx) in enumerate(toks):
        if not isinstance(cur, dict) or key not in cur:
            return False
        last = n == len(toks) - 1
        if idx is None:
            if last:
                cur[key] = value
                return True
            cur = cur[key]
        else:
            child = cur[key]
            if isinstance(child, dict):
                child = [child]
            if not isinstance(child, list) or int(idx) >= len(child):
                return False
            if last:
                child[int(idx)] = value
                return True
            cur = child[int(idx)]
    return False
