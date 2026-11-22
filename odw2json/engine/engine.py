"""RecipeEngine: the Classifier and Extractor of odw2json, driven only by recipe files."""
from __future__ import annotations

import dataclasses
import dataclasses
import os
import re
from typing import Any

from odw2json.model import Classification, Document, Evidence, Extraction
from odw2json.write import fill as fill_skeleton  # same completion rule as the writer
from odw2json.write import skeleton as schema_skeleton

from .dedupe import dedupe_items, prefer, same_name
from .normalise import NORMALISERS, PAGE_AWARE, VALIDATORS
from .recipes import Recipe, RecipeError, dictionaries_dir, load_dictionary, load_recipes, recipes_dir, signature
from .strategies import STRATEGIES, Candidate, Context, Scope, compile_pattern
from .text import Text, fold, squash

OCR_CONFIDENCE = 0.9  # values read from OCR pages
INVALID_CONFIDENCE = 0.5  # value failed its checksum validator (kept, never dropped)


class RecipeEngine:
    def __init__(self, recipes: str | os.PathLike | None = None, dictionaries_dir: str | os.PathLike | None = None):
        self.dir = recipes_dir(recipes)
        self._dict_dir = dictionaries_dir
        self._sig: tuple | None = None
        self._recipes: dict[str, Recipe] = {}
        self._dicts: dict[str, list[dict[str, Any]]] = {}

    # ---- recipes (reloaded when a file in the directory changes: a new YAML = a new class, no restart)
    @property
    def recipes(self) -> dict[str, Recipe]:
        sig = signature(self.dir)
        if sig != self._sig:
            recipes = {r.name: r for r in load_recipes(self.dir)}
            self._dicts = {}
            for r in recipes.values():  # dictionaries referenced by lookups: a typo fails now, not per document
                for name in _lookup_dictionaries(r.fields):
                    self.dictionary(name)
            self._recipes = recipes
            self._sig = sig
        return self._recipes

    def dictionary(self, name: str) -> list[dict[str, Any]]:
        if name not in self._dicts:
            self._dicts[name] = load_dictionary(name, dictionaries_dir(self._dict_dir))
        return self._dicts[name]

    # ---- classification
    def classify(self, doc: Document) -> Classification:
        recipes = self.recipes
        if not recipes:
            return Classification(None, 0.0, {}, f"no recipes in {self.dir}")
        flat = " ".join(Text(doc).low.split())
        views = {False: flat, True: squash(flat)}
        scores: dict[str, float] = {}
        notes: dict[str, str] = {}
        for name, r in recipes.items():
            c = r.classify
            if any(_signal_hit(s, views) for s in c.get("forbidden", [])):
                scores[name], notes[name] = 0.0, "forbidden signal"
                continue
            if not all(_signal_hit(s, views) for s in c.get("required", [])):
                scores[name], notes[name] = 0.0, "required signal missing"
                continue
            scores[name] = float(sum(s.get("weight", 1) for s in c["signals"] if _signal_hit(s, views)))
        ranked = sorted(scores, key=lambda n: -scores[n])
        best = ranked[0]
        second = scores[ranked[1]] if len(ranked) > 1 else 0.0
        c = recipes[best].classify
        if scores[best] < c.get("min_score", 1):
            why = notes.get(best) or f"best {best} {scores[best]:g} < min_score {c.get('min_score', 1):g}"
            return Classification(None, scores[best], scores, f"rejected: {why}")
        if scores[best] - second < c.get("margin", 0.5):
            return Classification(None, scores[best], scores, f"rejected: ambiguous ({best} {scores[best]:g} vs {ranked[1]} {second:g})")
        return Classification(best, scores[best], scores, f"recipe {recipes[best].path.name}")

    # ---- extraction
    def extract(self, doc: Document, doc_class: str) -> Extraction:
        recipe = self.recipes.get(doc_class)
        if recipe is None:
            raise RecipeError(f"no recipe for class {doc_class!r} in {self.dir}")
        text = Text(doc)
        sections = _sections(recipe, text)
        data: dict[str, Any] = {}
        evidence: list[Evidence] = []
        whole = Scope(0, len(text.raw))
        self._fields(recipe.fields, text, sections, whole, data, "", evidence)
        skel = recipe.skeleton()
        if skel is None:
            try:
                skel = schema_skeleton(doc_class)
            except KeyError:
                skel = None
        if skel is not None:  # evidence paths follow the output JSON (lists are wrapped as [0])
            evidence = [dataclasses.replace(e, path=_output_path(e.path, skel)) for e in evidence]
        if skel is not None:  # evidence paths follow the output JSON (lists are wrapped as [0])
            evidence = [dataclasses.replace(e, path=_output_path(e.path, skel)) for e in evidence]
        return Extraction(fill_skeleton(data, skel) if skel is not None else data, evidence)

    def _fields(self, fields, text, sections, scope, item, prefix, evidence) -> None:
        for f in fields:
            fscope = scope
            if f.get("section"):
                sec = sections.get(f["section"])
                if sec is None:
                    continue
                fscope = Scope(max(scope.start, sec.start), min(scope.end, sec.end))
                if fscope.end <= fscope.start:
                    continue
            if "list_of_blocks" in f:
                self._blocks(f, text, sections, fscope, item, prefix, evidence)
            elif "attach_to" in f:
                self._attached(f, text, sections, fscope, item, prefix, evidence)
            else:
                self._field(f, text, fscope, item, prefix, evidence, sections)

    def _blocks(self, f, text, sections, scope, item, prefix, evidence) -> None:
        spec = f["list_of_blocks"]
        end = scope.end
        if spec.get("end"):
            m = compile_pattern(spec["end"]).search(text.low, scope.start, scope.end)
            end = m.start() if m else end
        starts = [m.start() for m in compile_pattern(spec["start"]).finditer(text.low, scope.start, end)]
        starts = starts[: spec.get("max", len(starts))]
        if len(starts) < spec.get("min_blocks", 0):  # e.g. one principal, not a list: the whole scope is one item
            starts, end = [scope.start], scope.end
        items: list[dict[str, Any]] = []
        for i, a in enumerate(starts):
            b = starts[i + 1] if i + 1 < len(starts) else end
            sub: dict[str, Any] = {}
            self._fields(f["fields"], text, sections, Scope(a, b), sub, f"{prefix}{f['path']}[{i}].", evidence)
            items.append(sub)
        existing = _get(item, f["path"])
        if spec.get("merge") and isinstance(existing, list) and existing:
            dedupers = {g["path"].partition("[]")[0]: (g["path"].partition("[]")[2].lstrip("."), g["dedupe"])
                        for g in f["fields"] if g.get("dedupe") is not None and "[]" in g["path"]}
            for i, sub in enumerate(items):  # extra blocks join the last existing item
                target = existing[min(i, len(existing) - 1)]
                for k, v in sub.items():
                    if isinstance(target.get(k), list):  # lists: add only items not there yet
                        _merge_list(target[k], v, dedupers.get(k))
                    else:
                        target.setdefault(k, v)
            return
        _set(item, f["path"], items)

    def _attached(self, f, text, sections, scope, item, prefix, evidence) -> None:
        """A value printed beside each item of a list already read (`attach_to: list[].key`): item i is searched in
        the text from the end of its own mention up to the next item's mention (at most `window` characters)."""
        head, _, key = f["attach_to"].partition("[]")
        key = key.lstrip(".")
        rows = _get(item, head)
        if not isinstance(rows, list):
            return
        pats = []
        for row in rows:
            name = row.get(key) if isinstance(row, dict) else None
            ok = isinstance(name, str) and name.strip()
            pats.append(re.compile(r"\s+".join(re.escape(t) for t in fold(name).split())) if ok else None)
        mentions = [[m.span() for m in p.finditer(text.low, scope.start, scope.end)] if p else [] for p in pats]
        starts = sorted(a for spans in mentions for a, _ in spans)
        sub_field = {**f, "path": f["path"].partition("[]")[2].lstrip(".")}
        for i, row in enumerate(rows):
            for _, a in mentions[i]:  # the first mention that is followed by a value (a name may also stand in a letterhead)
                b = min([a + f.get("window", 200), scope.end, *[x for x in starts if x >= a]])
                self._field(sub_field, text, Scope(a, b), row, f"{head}[{i}].", evidence)
                if _get(row, sub_field["path"]) is not None:
                    break

    def _field(self, f, text, scope, item, prefix, evidence, sections=None) -> None:
        ctx = Context(text, item, self.dictionary)
        path = f["path"]
        for strat in f["strategies"]:
            fn = STRATEGIES[strat["use"]]
            scope_ = scope
            if strat.get("section"):  # this strategy alone searches inside a named section
                sec = (sections or {}).get(strat["section"])
                if sec is None:
                    continue
                scope_ = Scope(max(scope.start, sec.start), min(scope.end, sec.end))
                if scope_.end <= scope_.start:
                    continue
            if strat.get("all"):
                found, seen = [], set()
                for c in fn(ctx, strat, scope_):  # every distinct value once, in document order
                    v = _normalise(f, c.value, text.sources.get(c.page))
                    if v is not None and v not in seen:
                        seen.add(v)
                        found.append((v, c))
                if found and f.get("dedupe") is not None:  # the same person read twice (capitals, one OCR letter)
                    found = dedupe_items(found, f["dedupe"].get("fuzzy", 0))
                if found:
                    head, _, tail = path.partition("[]")
                    tail = tail.lstrip(".")
                    rows = []
                    for i, (v, c) in enumerate(found):
                        row: dict[str, Any] = {}
                        _set(row, tail, v) if tail else None
                        rows.append(row if tail else v)
                        evidence.append(_evidence(f"{prefix}{head}[{i}]" + (f".{tail}" if tail else ""), v, c, strat, f, text))
                    _set(item, head, rows)
                    return
                continue
            for c in fn(ctx, strat, scope_):
                v = _normalise(f, c.value, text.sources.get(c.page))
                if v is not None:
                    _set(item, path, v)
                    evidence.append(_evidence(prefix + path, v, c, strat, f, text))
                    return


def _merge_list(target: list, new: list, dedupe: tuple[str, dict] | None) -> None:
    """Add items not there yet; with `dedupe` (key, spec) an item naming the same person replaces/keeps the existing one."""
    for x in new:
        if x in target:
            continue
        if dedupe and isinstance(x, dict) and isinstance(x.get(dedupe[0]), str):
            key, spec = dedupe
            hit = next((t for t in target if isinstance(t, dict) and isinstance(t.get(key), str)
                        and same_name(t[key], x[key], spec.get("fuzzy", 0))), None)
            if hit is not None:
                hit[key] = prefer(hit[key], x[key])
                continue
        target.append(x)


def _signal_hit(sig: str | dict, views: dict[bool, str]) -> bool:
    if isinstance(sig, str):
        sig = {"pattern": sig}
    pat = sig["pattern"]
    if sig.get("squash"):
        pat = squash_pattern(pat)
    text = views[bool(sig.get("squash"))]
    if sig.get("head"):
        text = text[: sig["head"]]
    return compile_pattern(pat).search(text) is not None


_QUANT = re.compile(r"(?:[*+?]|\{\d+(?:,\d*)?\})\??")


def squash_pattern(pat: str) -> str:
    r"""Rewrite a pattern for whitespace-free text: drop literal spaces and standalone \s tokens (with their
    quantifier) outside character classes; classes such as [^\s] and escaped characters stay untouched."""
    out: list[str] = []
    i, n = 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "\\" and i + 1 < n:
            if pat[i + 1] == "s":
                i += 2
                q = _QUANT.match(pat, i)
                i = q.end() if q else i
            else:
                out.append(pat[i : i + 2])
                i += 2
        elif c == "[":
            j = i + 1
            if j < n and pat[j] == "^":
                j += 1
            if j < n and pat[j] == "]":
                j += 1
            while j < n and pat[j] != "]":
                j += 2 if pat[j] == "\\" else 1
            out.append(pat[i : j + 1])
            i = j + 1
        elif c == " ":
            i += 1
            q = _QUANT.match(pat, i)
            i = q.end() if q else i
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _lookup_dictionaries(fields: list[dict]) -> set[str]:
    names: set[str] = set()
    for f in fields:
        names.update(s["dictionary"] for s in f.get("strategies", []) if s.get("use") == "lookup")
        names.update(_lookup_dictionaries(f.get("fields") or []))
    return names


def _output_path(path: str, skel: Any) -> str:
    """Evidence path as it appears in the output JSON: a list in the skeleton is addressed as name[0]."""
    out, node = [], skel
    for part in path.split("."):
        m = re.fullmatch(r"(.*?)((?:\[\d+\])*)", part)
        name, idx = m[1], m[2]
        node = node.get(name) if isinstance(node, dict) else None
        if isinstance(node, list):
            idx = idx or "[0]"
            node = node[0] if node else None
        out.append(name + idx)
    return ".".join(out)


def _sections(recipe: Recipe, text: Text) -> dict[str, Scope]:
    out: dict[str, Scope] = {}
    for s in recipe.sections:
        parent = out.get(s["within"]) if s.get("within") else Scope(0, len(text.raw))
        if parent is None:
            continue
        m = compile_pattern(s["start"]).search(text.low, parent.start, parent.end)
        if not m:
            continue
        a = m.start() if s.get("include_start", True) else m.end()
        e = compile_pattern(s["end"]).search(text.low, m.end(), parent.end) if s.get("end") else None
        out[s["name"]] = Scope(a, e.start() if e else parent.end)
    return out


def _normalise(f: dict, value: Any, source: str | None = None) -> Any:
    names = f.get("normalize") or []
    for name in [names] if isinstance(names, str) else names:
        if value is None:
            return None
        if isinstance(value, str) or name == "int":
            value = NORMALISERS[name](value, source) if name in PAGE_AWARE else NORMALISERS[name](value)
    if isinstance(value, str):
        value = value.strip() or None
    return value


def _evidence(path: str, value: Any, c: Candidate, strat: dict, f: dict, text: Text) -> Evidence:
    conf = 1.0
    if f.get("validate") and not VALIDATORS[f["validate"]](value):
        conf = INVALID_CONFIDENCE
    if c.page is not None and text.sources.get(c.page) == "ocr":
        conf *= OCR_CONFIDENCE
    return Evidence(path, value, c.page, c.snippet, strat["use"], conf, c.bbox)


def _get(obj: dict[str, Any], path: str) -> Any:
    for p in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(p)
    return obj


def _set(obj: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    for p in parts[:-1]:
        nxt = obj.get(p)
        if isinstance(nxt, list):  # lists stay lists: descend into the first item (created when empty)
            if not nxt or not isinstance(nxt[0], dict):
                nxt[0:1] = [{}]
            nxt = nxt[0]
        elif not isinstance(nxt, dict):
            nxt = {}
            obj[p] = nxt
        obj = nxt
    obj[parts[-1]] = value


__all__ = ["RecipeEngine"]
