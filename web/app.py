"""FastAPI prototype: upload the PDFs of one case, see class, JSON and per-field evidence."""
from __future__ import annotations

import dataclasses
import functools
import io
import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from odw2json import factory
from odw2json.engine import RecipeError
from odw2json.pipeline import process_case
from . import recipes_api

STATIC = Path(__file__).parent / "static"
MAX_FILES = 40
MAX_BYTES = 60 * 1024 * 1024

app = FastAPI(title="Ślad (odw2json)", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(recipes_api.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _safe_name(name: str) -> str:
    base = re.split(r"[\/]", name or "")[-1].strip()
    return re.sub(r"[^\w.\- ()]", "_", base, flags=re.UNICODE) or "plik.pdf"


def _unique(name: str, taken: set[str]) -> str:
    stem, dot, ext = name.rpartition(".")
    stem, ext = (stem, "." + ext) if dot else (name, "")
    cand, i = name, 2
    while cand.lower() in taken:
        cand, i = f"{stem}_{i}{ext}", i + 1
    taken.add(cand.lower())
    return cand


def _doc_json(d, originals: dict[str, str]) -> dict[str, Any]:
    ext = d.extraction
    return {
        "input_name": originals.get(Path(d.input_path).name, Path(d.input_path).name),
        "output_name": d.output_name,
        "classification": dataclasses.asdict(d.classification),
        "data": ext.data if ext else None,
        "evidence": [dataclasses.asdict(e) for e in ext.evidence] if ext else [],
        "warnings": list(d.warnings),
    }


def _inline_logo(name: str) -> str:
    """The Eterphis logo is inlined so it follows night/daylight through CSS variables (an <img> cannot)."""
    svg = (STATIC / "coldtrace" / name).read_text(encoding="utf-8")
    svg = svg.replace(' role="img" aria-label="Eterphis"', ' aria-hidden="true"')
    return svg.replace('width="205" height="64" ', "")


@functools.lru_cache(maxsize=1)
def _index_html() -> str:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace("<!--ETERPHIS_MARK-->", _inline_logo("eterphis-mark-small.svg"))
    return html.replace("<!--ETERPHIS_WORDMARK-->", _inline_logo("eterphis-wordmark.svg"))


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse(_index_html())


@app.get("/api/recipes")
def recipes() -> dict[str, Any]:
    return recipes_api.listing()


@app.post("/api/process")
async def process(files: list[UploadFile] = File(...), case: str = Form("sprawa")) -> dict[str, Any]:
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Za dużo plików (maksymalnie {MAX_FILES}).")
    with tempfile.TemporaryDirectory(prefix="odw2json_") as tmp:
        case_name = _safe_name(case) or "sprawa"
        case_dir = Path(tmp) / case_name
        case_dir.mkdir()
        taken: set[str] = set()
        originals: dict[str, str] = {}
        total = 0
        for f in files:
            raw = await f.read()
            total += len(raw)
            if total > MAX_BYTES:
                raise HTTPException(400, "Wgrane pliki są za duże (limit 60 MB łącznie).")
            safe = _safe_name(f.filename or "")
            if not safe.lower().endswith(".pdf"):
                raise HTTPException(400, f"Plik „{safe}” nie jest PDF-em.")
            safe = _unique(safe, taken)
            (case_dir / safe).write_bytes(raw)
            originals[safe] = f.filename and _safe_name(f.filename) or safe
        try:
            factory.default_classifier()  # eager recipe load: show one clear message instead of an error per document
        except RecipeError as e:
            raise HTTPException(500, f"Błąd przepisu (recipes): {e}") from None
        res = process_case(case_dir)
        return {
            "case": res.case,
            "documents": [_doc_json(d, originals) for d in res.documents],
            "checks": [dataclasses.asdict(c) for c in res.checks],
        }


class ZipRequest(BaseModel):
    case: str
    files: dict[str, Any]


@app.post("/api/zip")
def make_zip(req: ZipRequest) -> Response:
    if _safe_name(req.case) != req.case or req.case in {"", ".", ".."}:
        raise HTTPException(400, "Niepoprawna nazwa sprawy.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in req.files.items():
            if _safe_name(name) != name or not name.endswith(".json"):
                raise HTTPException(400, f"Niepoprawna nazwa pliku: {name}")
            z.writestr(f"output/{req.case}/{name}", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{req.case}.zip"'})
