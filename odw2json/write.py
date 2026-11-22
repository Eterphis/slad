"""Schema-complete JSON writer: every output has all keys of the UZP schema for its class (null = unknown)."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

_cache: dict[str, Any] = {}


def classes() -> list[str]:
    """Known classes = schemas/<class>.json (a new class needs only a schema file, no code)."""
    return sorted(p.stem for p in SCHEMA_DIR.glob("*.json"))


def skeleton(doc_class: str) -> Any:
    """Fresh copy of the null skeleton for a class. Raises KeyError for unknown classes."""
    if doc_class not in _cache:
        path = SCHEMA_DIR / f"{doc_class}.json"
        if not re.fullmatch(r"[\w-]+", doc_class) or not path.is_file():
            raise KeyError(doc_class)
        _cache[doc_class] = json.loads(path.read_text(encoding="utf-8"))
    return copy.deepcopy(_cache[doc_class])


def fill(value: Any, template: Any) -> Any:
    if isinstance(template, dict):
        src = value if isinstance(value, dict) else {}
        return {k: fill(src.get(k), t) for k, t in template.items()}
    if isinstance(template, list):
        item_t = template[0]
        if isinstance(value, dict):  # a single entity given as an object
            value = [value]
        items = value if isinstance(value, list) and value else [None]
        return [fill(i, item_t) for i in items]
    return None if isinstance(value, (dict, list)) else value


_fill = fill  # old name


def complete(data: dict[str, Any], doc_class: str) -> dict[str, Any]:
    """Return data reshaped to the class schema: missing keys -> null, unknown keys dropped,
    lists keep every item (completed) and get one all-null item when empty.
    A class without schemas/<class>.json (defined by a recipe's output_schema) keeps data as the engine completed it."""
    try:
        skel = skeleton(doc_class)
    except KeyError:
        return data
    return fill(data, skel)


def write_json(path: str | Path, data: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return p
