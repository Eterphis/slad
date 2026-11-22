"""Prompt and answer schema, built only from the plan (recipe `llm:` blocks)."""
from __future__ import annotations

import re
from typing import Any

from .plan import AskField, AskGroup

SYSTEM = (
    "You read the text of a Polish legal or banking document (it may come from OCR and contain errors). "
    "Transcribe values exactly as they are printed: do not translate, reformat, correct or guess. "
    "For every field return `value` and `quote`, where `quote` is a short verbatim passage of the text that contains "
    "the value. When the text does not state the value, return null (or an empty list). /no_think"
)


def group_key(g: AskGroup) -> str:
    return re.sub(r"\W+", "_", g.path).strip("_")


def _leaf(f: AskField) -> dict[str, Any]:
    vt = "integer" if (f.type == "integer" or f.choices) else "string"
    return {
        "type": "object",
        "properties": {"value": {"type": [vt, "null"]}, "quote": {"type": ["string", "null"]}},
        "required": ["value", "quote"],
        "additionalProperties": False,
    }


def _describe(f: AskField) -> str:
    text = f.question + (f" {f.hint}" if f.hint else "")
    if f.choices:
        text += " Answer with the number of one option: " + "; ".join(f"{c['id']} = {c['label']}" for c in f.choices) + "."
    return text


def build(fields: list[AskField], groups: list[AskGroup], context: str) -> tuple[str, dict[str, Any]]:
    """(user message, JSON schema of the answer)."""
    props: dict[str, Any] = {}
    lines: list[str] = []
    for f in fields:
        props[f.key] = _leaf(f)
        lines.append(f"- {f.key}: {_describe(f)}")
    for g in groups:
        item = {f.key: _leaf(f) for f in g.fields}
        props[group_key(g)] = {
            "type": "array",
            "items": {"type": "object", "properties": item, "required": list(item), "additionalProperties": False},
            "maxItems": 8,
        }
        sub = "; ".join(f"{f.key} = {_describe(f)}" for f in g.fields)
        lines.append(f"- {group_key(g)}: a list. {g.question} {g.hint} Each item has: {sub}")
    schema = {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
    user = "Fields:\n" + "\n".join(lines) + '\n\nDocument text:\n"""\n' + context + '\n"""\nAnswer with JSON only.'
    return user, schema
