"""The grounded reader: fills what the recipes could not read, never overrides a confident recipe value.

Rules (the owner's spec-extraction pattern):
 1. the model transcribes strings as printed, our normalisers and validators turn them into dates, ids, numbers;
 2. every value needs a quote that is found in the text the model was shown, else it is dropped;
 3. a recipe value read with full confidence is never replaced; nulls and low-confidence values are filled,
    values read with less than full confidence (OCR) only on fields that set `override: true`;
 4. every decision is reported, so a rejected value is visible in the trace instead of silent.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from odw2json.engine.normalise import NORMALISERS, VALIDATORS
from odw2json.engine.text import fold
from odw2json.model import Document, Evidence, Extraction

from . import prompt
from .grounding import PageText, contains_value
from .plan import AskField, AskGroup, Plan
from .runtime import Runtime

log = logging.getLogger("odw2json.llm")

LOW_CONFIDENCE = 0.8  # below this the recipe value counts as weak (checksum failed); OCR reads (0.9) are not weak
FILLED_CONFIDENCE = 0.8
UNVALIDATED_CONFIDENCE = 0.4


@dataclass
class Decision:
    path: str
    status: str  # filled | replaced | agreed | kept | no_answer | ungrounded | invalid | unknown_choice
    value: Any = None
    quote: str | None = None
    recipe_value: Any = None
    detail: str = ""


# ---- path helpers: "Parties[0].name"
_PART = re.compile(r"([^.\[\]]+)((?:\[\d+\])*)")


def _steps(path: str) -> list[str | int]:
    out: list[str | int] = []
    for name, idx in _PART.findall(path):
        out.append(name)
        out += [int(i) for i in re.findall(r"\d+", idx)]
    return out


def get_path(data: Any, path: str) -> Any:
    for s in _steps(path):
        try:
            data = data[s]
        except (KeyError, IndexError, TypeError):
            return None
    return data


def set_path(data: Any, path: str, value: Any) -> None:
    steps = _steps(path)
    for s, nxt in zip(steps, steps[1:]):
        try:
            child = data[s]
        except (KeyError, IndexError):
            child = None
        if child is None:
            child = [] if isinstance(nxt, int) else {}
            if isinstance(data, list):
                while len(data) <= s:
                    data.append(None)
            data[s] = child
        data = child
    s = steps[-1]
    if isinstance(data, list):
        while len(data) <= s:
            data.append(None)
    data[s] = value


def _normalise(f: AskField, value: Any) -> Any:
    if value is None:
        return None
    if f.type == "integer" or f.choices:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    for name in f.normalize:
        if value is None:
            return None
        if isinstance(value, str):
            value = NORMALISERS[name](value)
    if isinstance(value, str):
        return value.strip() or None
    return value


class LlmReader:
    def __init__(self, runtime: Runtime, max_tokens: int = 700):
        self.runtime = runtime
        self.max_tokens = max_tokens

    @property
    def rule(self) -> str:
        return f"llm:{self.runtime.name}"

    # ---- main entry
    def read(self, doc: Document, ext: Extraction, plan: Plan, sections: dict[str, str] | None = None) -> list[Decision]:
        """Fill `ext` in place; returns one Decision per question asked."""
        sections = sections or {}
        conf = {e.path: e.confidence for e in ext.evidence}
        folded = fold(doc.text)
        todo_f = [f for f in plan.fields if self._needed(f, ext.data, conf) and self._when(f.when, folded)]
        todo_g = [g for g in plan.groups if self._when(g.when, folded) and self._group_needed(g, ext.data)]
        decisions: list[Decision] = []
        # one call per context: the default pages, plus one per recipe section a field narrows to
        buckets: dict[str | None, tuple[list[AskField], list[AskGroup]]] = {}
        for f in todo_f:
            sec = f.section if f.section in sections else None
            buckets.setdefault(sec, ([], []))[0].append(f)
        if todo_g:
            buckets.setdefault(None, ([], []))[1].extend(todo_g)
        for sec, (fs, gs) in buckets.items():
            pages, ctx = self._context(doc, plan, sections.get(sec) if sec else None)
            user, schema = prompt.build(fs, gs, ctx)
            try:
                answer = json.loads(self.runtime.complete(prompt.SYSTEM, user, schema, self.max_tokens))
                if not isinstance(answer, dict):
                    raise ValueError("answer is not an object")
            except ValueError as e:  # includes json.JSONDecodeError
                log.warning("unreadable model answer: %s", e)
                decisions += [Decision(f.path, "no_answer", detail="unreadable answer") for f in fs]
                continue
            for f in fs:
                decisions.append(self._apply_scalar(ext, f, answer.get(f.key), pages, conf))
            for g in gs:
                decisions += self._apply_group(ext, g, answer.get(prompt.group_key(g)), pages, conf)
        return decisions

    # ---- what to ask
    @staticmethod
    def _when(pattern: str | None, folded: str) -> bool:
        return not pattern or re.search(pattern, folded, re.M) is not None

    @staticmethod
    def _needed(f: AskField, data: Any, conf: dict[str, float]) -> bool:
        if get_path(data, f.path) is None:
            return True
        return conf.get(f.path, 1.0) < (1.0 if f.override else LOW_CONFIDENCE)

    @staticmethod
    def _group_needed(g: AskGroup, data: Any) -> bool:
        items = get_path(data, g.path) or []
        if not any(isinstance(i, dict) and i.get(g.key) is not None for i in items):
            return True
        return any(isinstance(it, dict) and it.get(sf.path) is None for it in items for sf in g.fields)

    @staticmethod
    def _context(doc: Document, plan: Plan, section: str | None) -> tuple[PageText, str]:
        if section:
            pieces = [(0, section[: plan.max_chars])]
        else:
            pieces, used = [], 0
            for p in doc.pages[: plan.pages]:
                t = (p.text or "")[: max(0, plan.max_chars - used)]
                if t.strip():
                    pieces.append((p.number, t))
                    used += len(t)
        return PageText(pieces), "\n\f\n".join(t for _, t in pieces)

    # ---- one answer -> one decision
    @staticmethod
    def _candidate(f: AskField, raw: Any, pages: PageText):
        """(value, quote, page, snippet, rejection status)."""
        if not isinstance(raw, dict) or raw.get("value") in (None, ""):
            return None, None, None, None, "no_answer"
        quote = raw.get("quote")
        found = pages.find(quote)
        if found is None:
            return None, quote, None, None, "ungrounded"
        if not f.choices and f.type != "integer" and not contains_value(quote, raw["value"]):
            return None, quote, None, None, "ungrounded"
        value = _normalise(f, raw["value"])
        if value is None:
            return None, quote, None, None, "invalid"
        if f.choices and value not in {c["id"] for c in f.choices}:
            return None, quote, None, None, "unknown_choice"
        return value, quote, found.page or None, found.snippet, None

    def _apply_scalar(self, ext: Extraction, f: AskField, raw: Any, pages: PageText, conf: dict[str, float]) -> Decision:
        cur = get_path(ext.data, f.path)
        value, quote, page, snippet, bad = self._candidate(f, raw, pages)
        if bad:
            return Decision(f.path, bad, None, quote, cur)
        valid = not f.validate or VALIDATORS[f.validate](value)
        c = conf.get(f.path, 1.0)
        if cur is None:
            if not valid:  # kept as a flagged low-confidence proposal, never as a confident answer
                self._put(ext, f.path, value, page, snippet, UNVALIDATED_CONFIDENCE)
                return Decision(f.path, "filled", value, quote, cur, "failed validator, low confidence")
            self._put(ext, f.path, value, page, snippet, FILLED_CONFIDENCE)
            self._also(ext, f, value, page, snippet)
            return Decision(f.path, "filled", value, quote, cur)
        if cur == value:
            return Decision(f.path, "agreed", value, quote, cur)
        limit = 1.0 if f.override else LOW_CONFIDENCE
        if c < limit and valid:
            self._put(ext, f.path, value, page, snippet, FILLED_CONFIDENCE)
            return Decision(f.path, "replaced", value, quote, cur, f"recipe confidence {c:g}")
        why = "validator failed" if not valid else f"recipe confidence {c:g} is not below {limit:g}"
        return Decision(f.path, "kept", value, quote, cur, why)

    def _also(self, ext: Extraction, f: AskField, value: Any, page, snippet) -> None:
        """A chosen entry also sets a companion field (e.g. the id's label), when that is still empty."""
        if not f.also or not f.choices or get_path(ext.data, f.also["path"]) is not None:
            return
        entry = next((c for c in f.choices if c["id"] == value), None)
        if entry is not None and entry.get(f.also["key"]) is not None:
            self._put(ext, f.also["path"], entry[f.also["key"]], page, snippet, FILLED_CONFIDENCE)

    def _put(self, ext: Extraction, path: str, value: Any, page, snippet, confidence: float) -> None:
        set_path(ext.data, path, value)
        ext.evidence = [e for e in ext.evidence if e.path != path]
        ext.evidence.append(Evidence(path, value, page, snippet, self.rule, confidence))

    def _apply_group(self, ext: Extraction, g: AskGroup, raw: Any, pages: PageText, conf: dict[str, float]) -> list[Decision]:
        if not isinstance(raw, list):
            return [Decision(g.path, "no_answer", detail="no list")]
        out: list[Decision] = []
        key_f = next((f for f in g.fields if f.path == g.key), None)
        existing = get_path(ext.data, g.path)
        existing = existing if isinstance(existing, list) else []
        have_keys = any(isinstance(i, dict) and i.get(g.key) is not None for i in existing)
        for item in raw:
            if not isinstance(item, dict) or key_f is None:
                continue
            kv, quote, *_ = self._candidate(key_f, item.get(key_f.key), pages)
            if kv is None:
                out.append(Decision(f"{g.path}[?].{g.key}", "ungrounded", None, quote))
                continue
            idx = next(
                (i for i, e in enumerate(existing) if isinstance(e, dict) and e.get(g.key) is not None and fold(str(e[g.key])).strip() == fold(str(kv)).strip()),
                None,
            )
            if idx is None:
                if have_keys:  # the recipe already found the people: an unknown one is not added silently
                    out.append(Decision(f"{g.path}[?].{g.key}", "kept", kv, quote, None, "not among the recipe's items"))
                    continue
                idx = self._free_slot(ext, g)
                existing = get_path(ext.data, g.path)
            for f in g.fields:
                path = f"{g.path}[{idx}].{f.path}"
                out.append(self._apply_scalar(ext, dataclasses.replace(f, path=path), item.get(f.key), pages, conf))
        return out

    @staticmethod
    def _free_slot(ext: Extraction, g: AskGroup) -> int:
        items = get_path(ext.data, g.path)
        if not isinstance(items, list):
            set_path(ext.data, g.path, [])
            items = get_path(ext.data, g.path)
        for i, it in enumerate(items):
            if not isinstance(it, dict) or all(v is None for v in it.values()):
                return i
        items.append({})
        return len(items) - 1
