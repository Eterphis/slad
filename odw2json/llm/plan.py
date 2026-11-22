"""What the model is asked, read from a recipe: field-level `llm:` blocks and the class-level `llm:` block.

Nothing here names a document class; a new class gets LLM help by writing `llm:` in its YAML.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

DEFAULT_PAGES = 2
DEFAULT_MAX_CHARS = 6000


@dataclass
class AskField:
    path: str  # output JSON path of the scalar, lists addressed as name[0]
    question: str
    hint: str = ""
    type: str = "string"  # string | integer
    choices: list[dict[str, Any]] | None = None  # [{id, label}]: the model picks an id, quoting the text that shows it
    normalize: list[str] = field(default_factory=list)
    validate: str | None = None
    override: bool = False  # may also replace a value the recipe read with less than full confidence (e.g. OCR)
    when: str | None = None  # regex on the folded document text: ask only when it matches
    section: str | None = None  # narrow the context to this recipe section
    also: dict[str, str] | None = None  # choices only: {path, key}: also set `path` to the chosen entry's `key` (e.g. label)

    @property
    def key(self) -> str:
        return re.sub(r"\W+", "_", self.path).strip("_")


@dataclass
class AskGroup:
    """A list of items (people, parties): each item has a key field and further fields to fill."""

    path: str  # output path of the list, e.g. "items"
    question: str
    key: str  # identity sub-field used to align the model's items with the recipe's items
    fields: list[AskField]  # paths relative to the item
    hint: str = ""
    when: str | None = None


@dataclass
class Plan:
    fields: list[AskField] = field(default_factory=list)
    groups: list[AskGroup] = field(default_factory=list)
    pages: int = DEFAULT_PAGES
    max_chars: int = DEFAULT_MAX_CHARS

    def __bool__(self) -> bool:
        return bool(self.fields or self.groups)


def _names(v) -> list[str]:
    return [] if not v else [v] if isinstance(v, str) else list(v)


def _field(spec: dict, path: str, base: dict | None = None) -> AskField:
    base = base or {}
    return AskField(
        path=path,
        question=spec.get("question") or base.get("question") or f"Value of {path}",
        hint=spec.get("hint", ""),
        type=spec.get("type", "string"),
        choices=spec.get("choices"),
        normalize=_names(spec.get("normalize", base.get("normalize"))),
        validate=spec.get("validate", base.get("validate")),
        override=bool(spec.get("override", False)),
        when=spec.get("when"),
        section=spec.get("section"),
        also=spec.get("also"),
    )


def _walk(fields: list[dict], prefix: str, out: list[AskField]) -> None:
    for f in fields:
        if "list_of_blocks" in f:
            _walk(f.get("fields") or [], f"{prefix}{f['path']}[0].", out)
        elif f.get("llm"):
            out.append(_field(f["llm"], prefix + f["path"].replace("[]", "[0]"), f))


def build_plan(spec: dict[str, Any], dictionaries) -> Plan:
    """spec = the parsed recipe; dictionaries(name) -> entries, used by `choices: {dictionary: name}`."""
    block = spec.get("llm") or {}
    ctx = block.get("context") or {}
    plan = Plan(pages=int(ctx.get("pages", DEFAULT_PAGES)), max_chars=int(ctx.get("max_chars", DEFAULT_MAX_CHARS)))
    _walk(spec.get("fields") or [], "", plan.fields)
    for f in block.get("fields") or []:
        plan.fields.append(_field(f, f["path"]))
    for g in block.get("groups") or []:
        plan.groups.append(
            AskGroup(g["path"], g.get("question", g["path"]), g["key"], [_field(f, f["path"]) for f in g["fields"]], g.get("hint", ""), g.get("when"))
        )
    for f in plan.fields:
        if isinstance(f.choices, dict):  # {dictionary: name}
            f.choices = [dict(e) for e in dictionaries(f.choices["dictionary"])]
    return plan
