"""Load and validate recipes (recipes/*.yaml) and dictionaries (dictionaries/*.yaml)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from .strategies import compile_pattern
from .text import fold

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_FILE = ROOT / "recipes" / "recipe.schema.json"


class RecipeError(ValueError):
    """A recipe or dictionary file is invalid; the message names the file and the place."""


@dataclass
class Recipe:
    name: str
    path: Path
    spec: dict[str, Any]

    @property
    def classify(self) -> dict[str, Any]:
        return self.spec["classify"]

    @property
    def fields(self) -> list[dict[str, Any]]:
        return self.spec.get("fields") or []

    @property
    def sections(self) -> list[dict[str, Any]]:
        return self.spec.get("sections") or []

    def skeleton(self) -> Any | None:
        """The output skeleton named by output_schema (None = use the writer's schemas/<class>.json)."""
        ref = self.spec.get("output_schema")
        if not ref:
            return None
        for base in (self.path.parent, ROOT):
            p = base / ref
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))
        raise RecipeError(f"{self.path.name}: output_schema {ref!r} not found")


def recipes_dir(explicit: str | os.PathLike | None = None) -> Path:
    """--recipes option > env ODW2JSON_RECIPES > <repo>/recipes."""
    return Path(explicit or os.environ.get("ODW2JSON_RECIPES") or ROOT / "recipes")


def dictionaries_dir(explicit: str | os.PathLike | None = None) -> Path:
    return Path(explicit or os.environ.get("ODW2JSON_DICTIONARIES") or ROOT / "dictionaries")


_validator = None


def _schema_validator():
    global _validator
    if _validator is None:
        _validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))
    return _validator


def _where(err) -> str:
    return "/".join(str(p) for p in err.absolute_path) or "(top level)"


def _check_regexes(spec: Any, where: str, name: str) -> None:
    keys = {"pattern", "start", "end", "exclude", "not_after"}
    if isinstance(spec, dict):
        for k, v in spec.items():
            is_value = k == "value" and spec.get("use") == "after_label" and isinstance(v, str)
            if k in keys and isinstance(v, str) or k == "labels" and isinstance(v, list) or is_value:
                for pat in v if isinstance(v, list) else [v]:
                    try:
                        re.compile(pat)
                        if k == "pattern" and spec.get("squash"):
                            from .engine import squash_pattern

                            re.compile(squash_pattern(pat))
                    except re.error as e:
                        err = RecipeError(f"{name}: {where}/{k}: bad regex {pat!r}: {e}")
                        err.where = f"{where}/{k}".strip("/")
                        raise err from None
            _check_regexes(v, f"{where}/{k}", name)
    elif isinstance(spec, list):
        for i, v in enumerate(spec):
            if isinstance(v, str) and where.endswith(("forbidden", "required")):
                _check_regexes({"pattern": v}, f"{where}/{i}", name)
            else:
                _check_regexes(v, f"{where}/{i}", name)


def load_recipe(path: Path) -> Recipe:
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RecipeError(f"{path.name}: not valid YAML: {e}") from None
    errors = sorted(_schema_validator().iter_errors(spec), key=lambda e: list(e.absolute_path))
    if errors:
        msgs = "; ".join(f"{_where(e)}: {e.message}" for e in errors[:5])
        raise RecipeError(f"{path.name}: {msgs}")
    _check_regexes(spec, "", path.name)
    return Recipe(spec["class"], path, spec)


RESERVED = {"case"}  # configuration files in the recipes folder that are not document-class recipes


def load_recipes(directory: str | os.PathLike | None = None) -> list[Recipe]:
    d = recipes_dir(directory)
    files = [p for p in sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml")) if p.stem not in RESERVED]  # guards a class file named case.yaml; the case config lives in recipes/case/ (odw2json/case)
    recipes = [load_recipe(p) for p in files]
    names = [r.name for r in recipes]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise RecipeError(f"{d}: class defined twice: {sorted(dup)}")
    return recipes


def load_dictionary(name: str, directory: str | os.PathLike | None = None) -> list[dict[str, Any]]:
    p = dictionaries_dir(directory) / f"{name}.yaml"
    if not p.is_file():
        raise RecipeError(f"dictionary {name!r} not found ({p})")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not all(isinstance(e, dict) and isinstance(e.get("triggers"), list) for e in entries):
        raise RecipeError(f"{p.name}: expected 'entries: [{{id, label, triggers: [...]}}]'")
    for e in entries:
        for trig in e["triggers"]:
            try:
                compile_pattern(fold(str(trig)), loose_spaces=True)
            except re.error as err:
                raise RecipeError(f"{p.name}: entry {e.get('id')!r}: bad regex in trigger {trig!r}: {err} (triggers are regular expressions)") from None
    return entries


def signature(directory: Path) -> tuple:
    """Changes when a recipe file is added, removed or edited (engine reloads without a restart)."""
    files = sorted(directory.glob("*.y*ml"))
    return tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in files)


# ---- validation of recipe text (used by the web editor; same rules as load_recipe, but all errors, with lines)
def _line_of(root: Any, path: list) -> int | None:
    """1-based line of the node at `path` in a composed YAML tree (the deepest node that exists)."""
    node, line = root, None
    for part in path:
        if node is None:
            break
        line = node.start_mark.line + 1
        if isinstance(node, yaml.MappingNode):
            nxt = None
            for k, v in node.value:
                if k.value == part:
                    nxt, line = v, k.start_mark.line + 1
                    break
            node = nxt
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int) and part < len(node.value):
            node = node.value[part]
            line = node.start_mark.line + 1
        else:
            break
    return line if line is not None else (root.start_mark.line + 1 if root is not None else None)


def check_recipe_text(text: str, dictionaries: str | os.PathLike | None = None) -> tuple[dict | None, list[dict[str, Any]]]:
    """Validate recipe YAML text without touching disk. Returns (spec or None, errors); each error is
    {"path": "fields/0/strategies/0/pattern", "line": 12 or None, "message": ...}. No errors = loadable."""
    from .normalise import NORMALISERS, VALIDATORS
    from .strategies import STRATEGIES

    try:
        spec = yaml.safe_load(text)
        root = yaml.compose(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        why = getattr(e, "problem", None) or str(e)
        return None, [{"path": "(yaml)", "line": mark.line + 1 if mark else None, "message": f"not valid YAML: {why}"}]
    if not isinstance(spec, dict):
        return None, [{"path": "(top level)", "line": 1, "message": "a recipe is a YAML mapping: start with 'class: name' and 'classify:'"}]

    def err(path: list, message: str) -> dict[str, Any]:
        return {"path": "/".join(str(p) for p in path) or "(top level)", "line": _line_of(root, path), "message": message}

    errors: list[dict[str, Any]] = []
    for e in sorted(_schema_validator().iter_errors(spec), key=lambda e: list(map(str, e.absolute_path))):
        if e.validator in ("oneOf", "anyOf") and e.context:
            e = jsonschema.exceptions.best_match(e.context) or e
        errors.append(err(list(e.absolute_path), e.message[:300]))
    if errors:
        return spec, errors[:12]
    try:
        _check_regexes(spec, "", "recipe")
    except RecipeError as e:
        where = getattr(e, "where", "")
        path = [int(p) if p.isdigit() else p for p in where.split("/") if p]
        errors.append(err(path, "bad regex" + str(e).split("bad regex", 1)[-1] + " (check brackets and escape literal characters with a backslash)"))

    def walk(fields: list, base: list) -> None:
        for i, f in enumerate(fields or []):
            fp = base + [i]
            for n in ([f["normalize"]] if isinstance(f.get("normalize"), str) else f.get("normalize") or []):
                if n not in NORMALISERS:
                    errors.append(err(fp + ["normalize"], f"unknown normaliser {n!r}; known: {', '.join(sorted(NORMALISERS))}"))
            if f.get("validate") and f["validate"] not in VALIDATORS:
                errors.append(err(fp + ["validate"], f"unknown validator {f['validate']!r}; known: {', '.join(sorted(VALIDATORS))}"))
            for j, s in enumerate(f.get("strategies") or []):
                if s["use"] not in STRATEGIES:
                    errors.append(err(fp + ["strategies", j, "use"], f"unknown strategy {s['use']!r}"))
                elif s["use"] == "lookup":
                    try:
                        load_dictionary(s["dictionary"], dictionaries)
                    except RecipeError as de:
                        errors.append(err(fp + ["strategies", j, "dictionary"], str(de)))
            walk(f.get("fields") or [], fp + ["fields"])

    walk(spec.get("fields"), ["fields"])
    return spec, errors[:12]
