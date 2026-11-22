"""Build a noisy, scanned-looking copy of held-out cases (proxy for real scanned appeals).

    python -m eval.make_noisy --cases 41-50 --out <dir> [--src <UZP_DATA>/dane] [--dpi 200] [--seed 20260101]

Reads ``<src>/przyklad_NN/*.pdf`` + ``*.json`` (src defaults to ``$UZP_DATA/dane``) and writes
``<out>/input/przyklad_NN/*.pdf`` (image-only PDFs, no text layer) and ``<out>/gold/przyklad_NN/*.json``.
Each page is rendered with pypdfium2 and degraded reproducibly (seed derived from the base seed and the
file/page name): rotation within +-1.5 deg, blur, uneven brightness, optional stamp / signature blob,
salt-and-pepper noise and JPEG artefacts. Output should stay outside the repo (data licence unclear).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import sys
from pathlib import Path
import time as _time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

_FIXED_DATE = _time.gmtime(1767225600)  # 2026-01-01 UTC; Pillow wants struct_time

DEFAULT_SEED = 20260101
DEFAULT_DPI = 200
MAX_ROTATION = 1.5


def parse_cases(spec: str) -> list[int]:
    """'41-50' or '01,07,41-43' -> sorted unique case numbers."""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return sorted(out)


def _rng(seed: int, key: str) -> np.random.Generator:
    h = hashlib.sha256(f"{seed}:{key}".encode()).digest()
    return np.random.default_rng(int.from_bytes(h[:8], "big"))


def degrade_image(img: Image.Image, rng: np.random.Generator) -> Image.Image:
    """Apply scan-like degradations to a page image. Deterministic for a given rng state."""
    img = img.convert("L")
    w, h = img.size
    # slight rotation, white fill
    angle = float(rng.uniform(-MAX_ROTATION, MAX_ROTATION))
    img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
    # blur
    img = img.filter(ImageFilter.GaussianBlur(float(rng.uniform(0.5, 1.1))))
    arr = np.asarray(img, dtype=np.float32)
    # uneven brightness: linear gradient + low-frequency bump
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    gx, gy = rng.uniform(-0.10, 0.10, 2)
    cx, cy = rng.uniform(0.2, 0.8, 2)
    bump = float(rng.uniform(-0.08, 0.04)) * np.exp(
        -(((xx / w - cx) ** 2 + (yy / h - cy) ** 2) / 0.08)
    )
    factor = 0.93 + gx * (xx / w - 0.5) + gy * (yy / h - 0.5) + bump
    arr = arr * factor
    # stamp / signature blob (optional)
    pil = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if rng.random() < 0.6:
        pil = _add_blob(pil, rng)
    arr = np.asarray(pil, dtype=np.float32)
    # salt-and-pepper
    frac = float(rng.uniform(0.002, 0.006))
    mask = rng.random(arr.shape)
    arr = np.where(mask < frac / 2, 0.0, arr)
    arr = np.where((mask >= frac / 2) & (mask < frac), 255.0, arr)
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    # JPEG artefacts
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=int(rng.integers(30, 56)))
    buf.seek(0)
    return Image.open(buf).convert("L")


def _add_blob(img: Image.Image, rng: np.random.Generator) -> Image.Image:
    """Semi-transparent grey ellipse ring (stamp) or scribble (signature) in the lower half."""
    w, h = img.size
    layer = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(layer)
    x = int(rng.uniform(0.15, 0.7) * w)
    y = int(rng.uniform(0.55, 0.9) * h)
    if rng.random() < 0.5:
        r = int(rng.uniform(0.05, 0.09) * w)
        d.ellipse([x, y, x + 2 * r, y + 2 * r], outline=140, width=max(2, r // 14))
        d.ellipse([x + r // 3, y + r // 3, x + 2 * r - r // 3, y + 2 * r - r // 3], outline=140, width=2)
    else:
        pts = [(x + i * w // 60, y + int(rng.uniform(-1, 1) * h / 40)) for i in range(12)]
        d.line(pts, fill=120, width=max(2, w // 300))
    layer = layer.filter(ImageFilter.GaussianBlur(1.0))
    return Image.fromarray(np.minimum(np.asarray(img), 255 - np.asarray(layer)).astype(np.uint8))


def render_pages(pdf_path: Path, dpi: int) -> list[Image.Image]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return [pdf[i].render(scale=dpi / 72.0).to_pil().convert("L") for i in range(len(pdf))]
    finally:
        pdf.close()


def noisy_pdf(src: Path, dst: Path, dpi: int = DEFAULT_DPI, seed: int = DEFAULT_SEED) -> int:
    """Write an image-only degraded copy of ``src`` to ``dst``. Returns the page count."""
    pages = render_pages(src, dpi)
    imgs = [degrade_image(p, _rng(seed, f"{src.parent.name}/{src.name}/{i}")) for i, p in enumerate(pages)]
    dst.parent.mkdir(parents=True, exist_ok=True)
    first, rest = imgs[0], imgs[1:]
    first.save(dst, format="PDF", save_all=True, append_images=rest, resolution=float(dpi),
               creationDate=_FIXED_DATE, modDate=_FIXED_DATE)  # fixed metadata: byte-reproducible output
    return len(imgs)


def build(src_root: Path, out: Path, cases: list[int], dpi: int = DEFAULT_DPI, seed: int = DEFAULT_SEED) -> tuple[int, int]:
    """Returns (pdfs written, gold files copied)."""
    n_pdf = n_gold = 0
    for n in cases:
        case = f"przyklad_{n:02d}"
        cdir = src_root / case
        if not cdir.is_dir():
            raise FileNotFoundError(f"case folder not found: {cdir}")
        for pdf in sorted(cdir.glob("*.pdf")):
            noisy_pdf(pdf, out / "input" / case / pdf.name, dpi, seed)
            n_pdf += 1
        for js in sorted(cdir.glob("*.json")):
            dst = out / "gold" / case / js.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(js, dst)
            n_gold += 1
        print(f"{case}: done", flush=True)
    return n_pdf, n_gold


def default_src(start: Path | None = None) -> str | None:
    """$UZP_DATA/dane, else the nearest ``uzp-data/dane`` in the current folder or a parent (repo or worktree)."""
    if os.environ.get("UZP_DATA"):
        return os.path.join(os.environ["UZP_DATA"], "dane")
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / "uzp-data" / "dane").is_dir():
            return str(d / "uzp-data" / "dane")
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.make_noisy", description=__doc__.split("\n")[0])
    ap.add_argument("--cases", default="41-50")
    ap.add_argument("--out", required=True)
    ap.add_argument("--src", default=None, help="folder with przyklad_NN (default $UZP_DATA/dane)")
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args(argv)
    src = args.src or default_src()
    if not src:
        ap.error("set --src or the UZP_DATA environment variable (or clone the data into <repo>/uzp-data)")
    n_pdf, n_gold = build(Path(src), Path(args.out), parse_cases(args.cases), args.dpi, args.seed)
    print(f"wrote {n_pdf} noisy pdfs, {n_gold} gold files to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
