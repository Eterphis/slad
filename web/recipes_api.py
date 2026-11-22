"""Document classes from the web UI: list, read, validate, try and save recipes/<name>.yaml (hot reload, no restart).

All rules come from the engine's own loader (`odw2json.engine.recipes.check_recipe_text`); this module only adds
file handling (atomic write, .bak), the name rule and the read-only switch for public demo hosting.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from odw2json import factory
from odw2json.engine import RecipeEngine, RecipeError
from odw2json.engine.recipes import ROOT, check_recipe_text, load_recipe, recipes_dir
from odw2json.write import complete

router = APIRouter()

NAME_RE = re.compile(r"[a-z][a-z0-9_]{1,40}")
SCHEMA_FILE_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.json")
UZP_CLASSES = ("odwolanie", "pelnomocnictwo", "przelew")
TEMPLATE = ROOT / "recipes" / "_template.yaml.example"
MAX_FILES = 10
MAX_BYTES = 30 * 1024 * 1024


def readonly() -> bool:
    return os.environ.get("ODW2JSON_READONLY_RECIPES") == "1"


def _forbid_readonly() -> None:
    if readonly():
        raise HTTPException(403, "Edycja klas jest wyłączona na tym serwerze (tryb tylko do odczytu). Uruchom aplikację lokalnie, aby dodawać klasy.")


def _check_name(name: str) -> str:
    if not NAME_RE.fullmatch(name):
        raise HTTPException(422, "Niepoprawna nazwa klasy. Użyj małych liter, cyfr i podkreślenia, od litery, 2 do 41 znaków (np. wezwanie_do_zaplaty).")
    return name


def _path_for(name: str) -> Path | None:
    d = recipes_dir()
    for ext in (".yaml", ".yml"):
        if (d / (name + ext)).is_file():
            return d / (name + ext)
    return None


def count_fields(fields: list[dict] | None) -> int:
    n = 0
    for f in fields or []:
        n += count_fields(f["fields"]) if f.get("fields") else 1
    return n


def _set_path(obj: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    for p in parts[:-1]:
        nxt = obj.get(p)
        if not isinstance(nxt, dict):
            nxt = obj[p] = {}
        obj = nxt
    obj[parts[-1]] = value


def skeleton_from_spec(spec: dict) -> dict:
    """Null skeleton from the field paths of a recipe ('a.b' nests; 'a[].b' and list_of_blocks make a one-item list)."""
    def build(fields: list[dict]) -> dict:
        out: dict[str, Any] = {}
        for f in fields or []:
            if "list_of_blocks" in f:
                _set_path(out, f["path"], [build(f.get("fields") or [])])
            elif "[]" in f["path"]:
                head, _, tail = f["path"].partition("[]")
                tail = tail.lstrip(".")
                _set_path(out, head, [{tail: None}] if tail else [None])
            else:
                _set_path(out, f["path"], None)
        return out
    return build(spec.get("fields") or [])


def _skeleton_text(spec: dict) -> str:
    return json.dumps(skeleton_from_spec(spec), ensure_ascii=False, indent=2) + "\n"


def _schema_errors(spec: dict, schema_text: str | None) -> list[dict[str, Any]]:
    """The output skeleton named by the recipe must be given (or already exist) and be a JSON object."""
    ref = spec.get("output_schema")
    if not ref:
        return []
    err = lambda m, p="output_schema": [{"path": p, "line": None, "message": m}]  # noqa: E731
    if schema_text is not None and schema_text.strip():
        if not SCHEMA_FILE_RE.fullmatch(ref) or ref == "recipe.schema.json":
            return err(f"Nazwa szkieletu {ref!r} musi być zwykłą nazwą pliku .json (bez katalogów), np. {{klasa}}.output.json.")
        try:
            val = json.loads(schema_text)
        except json.JSONDecodeError as e:
            return err(f"Szkielet wyniku nie jest poprawnym JSON-em: {e.msg} (linia {e.lineno}, kolumna {e.colno}).", "(szkielet wyniku)")
        if not isinstance(val, (dict, list)):
            return err("Szkielet wyniku musi być obiektem JSON.", "(szkielet wyniku)")
        return []
    if not any((b / ref).is_file() for b in (recipes_dir(), ROOT)):
        return err(f"Plik szkieletu {ref!r} nie istnieje. Wklej szkielet wyniku albo kliknij „Szkielet z pól”.")
    return []


def validate_text(text: str, schema_text: str | None = None, name: str | None = None) -> dict[str, Any]:
    spec, errors = check_recipe_text(text)
    if spec is not None and not errors:
        errors += _schema_errors(spec, schema_text)
        if name and spec["class"] != name:
            errors.append({"path": "class", "line": 1, "message": f"Nazwa klasy w pliku ({spec['class']!r}) musi być taka jak nazwa pliku ({name!r})."})
        elif not name and not NAME_RE.fullmatch(spec["class"]):
            errors.append({"path": "class", "line": 1, "message": "Nazwa klasy: małe litery, cyfry i podkreślenie, od litery (np. wezwanie_do_zaplaty)."})
    warnings = []
    if spec is not None and not errors and not spec.get("output_schema"):
        warnings.append("Brak output_schema: wynik zawiera tylko pola znalezione w dokumencie. Dodaj szkielet, aby brakujące pola miały wartość null.")
    ok = not errors
    return {"ok": ok, "errors": errors, "warnings": warnings,
            "class": spec.get("class") if isinstance(spec, dict) else None,
            "fields": count_fields(spec.get("fields")) if ok and spec else None}


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copyfile(path, path.with_name(path.name + ".bak"))
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content if content.endswith("\n") else content + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---- routes -------------------------------------------------------------------------------------------------
def listing() -> dict[str, Any]:
    from odw2json.write import classes as schema_classes

    d = recipes_dir()
    items, names = [], set(schema_classes())
    for p in sorted([*d.glob("*.yaml"), *d.glob("*.yml")]):
        try:
            r = load_recipe(p)
            items.append({"name": r.name, "file": p.name, "description": r.spec.get("description", ""),
                          "fields": count_fields(r.fields), "protected": r.name in UZP_CLASSES, "error": None})
            names.add(r.name)
        except RecipeError as e:
            items.append({"name": p.stem, "file": p.name, "description": "", "fields": 0, "protected": p.stem in UZP_CLASSES, "error": str(e)})
    return {"classes": sorted(names), "recipes": items, "readonly": readonly(), "protected": list(UZP_CLASSES)}


@router.get("/api/recipe-template")
def template() -> dict[str, Any]:
    text = TEMPLATE.read_text(encoding="utf-8")
    spec, _ = check_recipe_text(text)
    return {"text": text, "output_schema": _skeleton_text(spec) if spec else ""}


class DraftBody(BaseModel):
    text: str
    output_schema: str | None = None


@router.post("/api/recipes/skeleton")
def skeleton(body: DraftBody) -> dict[str, Any]:
    spec, errors = check_recipe_text(body.text)
    if spec is None or errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=422)  # type: ignore[return-value]
    return {"ok": True, "output_schema": _skeleton_text(spec)}


@router.post("/api/recipes/validate")
def validate(body: DraftBody) -> dict[str, Any]:
    return validate_text(body.text, body.output_schema)


@router.get("/api/recipes/{name}")
def read(name: str) -> dict[str, Any]:
    _check_name(name)
    p = _path_for(name)
    if p is None:
        raise HTTPException(404, f"Nie ma klasy {name!r}.")
    text = p.read_text(encoding="utf-8")
    spec, _ = check_recipe_text(text)
    spec = spec if isinstance(spec, dict) else {}
    schema = None
    ref = spec.get("output_schema")
    if ref:
        for b in (p.parent, ROOT):
            f = b / ref
            if f.is_file():
                schema = {"file": ref, "text": f.read_text(encoding="utf-8")}
                break
        else:
            schema = {"file": ref, "text": None}
    dicts = sorted({s["dictionary"] for f in _walk(spec.get("fields")) for s in f.get("strategies", []) if s.get("use") == "lookup"})
    return {"name": name, "file": p.name, "text": text, "output_schema": schema, "dictionaries": dicts,
            "protected": name in UZP_CLASSES, "readonly": readonly()}


def _walk(fields):
    for f in fields or []:
        yield f
        yield from _walk(f.get("fields"))


class PutBody(DraftBody):
    pass


@router.put("/api/recipes/{name}")
def save(name: str, body: PutBody) -> dict[str, Any]:
    _forbid_readonly()
    _check_name(name)
    res = validate_text(body.text, body.output_schema, name)
    if not res["ok"]:
        return JSONResponse({"detail": "Receptura nie przeszła sprawdzenia. Nic nie zapisano.", **res}, status_code=422)  # type: ignore[return-value]
    existing = _path_for(name)
    for p in sorted([*recipes_dir().glob("*.yaml"), *recipes_dir().glob("*.yml")]):  # another file with this class name
        if p != existing:
            try:
                if load_recipe(p).name == name:
                    raise HTTPException(409, f"Klasa {name!r} jest już zdefiniowana w pliku {p.name}.")
            except RecipeError:
                pass
    spec = yaml.safe_load(body.text)
    path = existing or recipes_dir() / f"{name}.yaml"
    if spec.get("output_schema") and body.output_schema and body.output_schema.strip():
        _atomic_write(recipes_dir() / spec["output_schema"], body.output_schema)
    _atomic_write(path, body.text)
    return {"ok": True, "name": name, "file": path.name, "created": existing is None, "fields": res["fields"], "warnings": res["warnings"]}


@router.delete("/api/recipes/{name}")
def delete(name: str, force: bool = False) -> dict[str, Any]:
    _forbid_readonly()
    _check_name(name)
    p = _path_for(name)
    if p is None:
        raise HTTPException(404, f"Nie ma klasy {name!r}.")
    if name in UZP_CLASSES and not force:
        raise HTTPException(409, f"Klasa {name!r} jest jedną z trzech klas zadania UZP. Usunięcie jej zepsuje wynik; jeśli to zamierzone, ponów z force=true.")
    bak = p.with_name(p.name + ".bak")
    os.replace(p, bak)  # recoverable: the file stays next to the recipes as <name>.yaml.bak
    return {"ok": True, "name": name, "backup": bak.name}


@router.post("/api/recipes/try")
async def try_recipe(text: str = Form(...), output_schema: str | None = Form(None), files: list[UploadFile] = File(...)) -> Any:
    """Run a draft recipe (nothing is saved) on uploaded PDFs: classification of all classes incl. the draft, fields, evidence."""
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Za dużo plików (maksymalnie {MAX_FILES}).")
    res = validate_text(text, output_schema)
    if not res["ok"]:
        return JSONResponse({"detail": "Receptura nie przeszła sprawdzenia.", **res}, status_code=422)
    draft = res["class"]
    spec = yaml.safe_load(text)
    with tempfile.TemporaryDirectory(prefix="odw2json_try_") as tmp:
        rdir, pdir = Path(tmp) / "recipes", Path(tmp) / "pdf"
        rdir.mkdir(); pdir.mkdir()
        for p in recipes_dir().iterdir():  # the saved classes, except the one being edited
            if p.is_file() and p.suffix in (".yaml", ".yml", ".json"):
                if p.suffix != ".json" and p.stem == draft:
                    continue
                shutil.copyfile(p, rdir / p.name)
        (rdir / f"{draft}.yaml").write_text(text, encoding="utf-8")
        if spec.get("output_schema") and output_schema and output_schema.strip():
            (rdir / spec["output_schema"]).write_text(output_schema, encoding="utf-8")
        total, docs = 0, []
        for i, f in enumerate(files):
            raw = await f.read()
            total += len(raw)
            if total > MAX_BYTES:
                raise HTTPException(400, "Wgrane pliki są za duże (limit 30 MB łącznie).")
            name = re.sub(r"[^\w.\- ()]", "_", re.split(r"[\\/]", f.filename or "")[-1], flags=re.UNICODE) or "plik.pdf"
            if not name.lower().endswith(".pdf"):
                raise HTTPException(400, f"Plik „{name}” nie jest PDF-em.")
            (pdir / f"{i}.pdf").write_bytes(raw)
            docs.append((i, name))
        try:
            engine = RecipeEngine(rdir)
            engine.recipes
        except RecipeError as e:
            raise HTTPException(422, f"Inna receptura w katalogu jest uszkodzona, więc nie da się porównać klas: {e}") from None
        out = []
        for i, name in docs:
            try:
                doc = factory.default_ingestor().ingest(str(pdir / f"{i}.pdf"))
                cls = engine.classify(doc)
                ext = engine.extract(doc, draft)
            except Exception as e:  # one unreadable PDF must not hide the others
                out.append({"input_name": name, "error": f"{type(e).__name__}: {e}"})
                continue
            data = complete(ext.data, draft)
            out.append({
                "input_name": name,
                "classification": dataclasses.asdict(cls),
                "draft_class": draft,
                "draft_score": cls.scores.get(draft, 0.0),
                "matched": cls.doc_class == draft,
                "data": data,
                "evidence": [dataclasses.asdict(e) for e in ext.evidence],
            })
    return {"ok": True, "class": draft, "documents": out, "warnings": res["warnings"]}
