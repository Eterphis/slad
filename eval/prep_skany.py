"""Lay out the UZP scan set (dane/skany/<type>/<NNNN>/<NNNN>.{pdf,json}) and the negatives as input/gold trees.

usage: python -m eval.prep_skany <dest> [--src <uzp-data>/dane]
  <dest>/input/<typ>_<NNNN>/<NNNN>.pdf, <dest>/gold/<typ>_<NNNN>/<NNNN>.json  (typ = odw | pel | prz)
  <dest>/input/negatywne/*.pdf (no gold: every output there must be an empty JSON)
then: python -m odw2json --input <dest>/input --output <dest>/output
      python -m eval.score --pred <dest>/output --gold <dest>/gold
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

TYPES = {"odwolania": "odw", "pelnomocnictwa": "pel", "potwierdzenia": "prz"}


def default_src() -> Path:
    env = os.environ.get("UZP_DATA")
    if env:
        return Path(env) / "dane"
    here = Path(__file__).resolve().parents[1]
    for base in (here, *here.parents):
        if (base / "uzp-data" / "dane").is_dir():
            return base / "uzp-data" / "dane"
    raise SystemExit("uzp-data/dane not found: set UZP_DATA or pass --src")


def prepare(dest: Path, src: Path) -> tuple[int, int]:
    if dest.exists():
        shutil.rmtree(dest)
    n = 0
    for folder, short in TYPES.items():
        for case in sorted((src / "skany" / folder).glob("*")):
            pdfs, golds = list(case.glob("*.pdf")), list(case.glob("*.json"))
            if not pdfs:
                continue
            name = f"{short}_{case.name}"
            (dest / "input" / name).mkdir(parents=True)
            (dest / "gold" / name).mkdir(parents=True)
            for f in pdfs:
                shutil.copy2(f, dest / "input" / name / f.name)
                n += 1
            for f in golds:
                shutil.copy2(f, dest / "gold" / name / f.name)
    neg = 0
    if (src / "negatywne").is_dir():
        (dest / "input" / "negatywne").mkdir(parents=True)
        for f in sorted((src / "negatywne").glob("*.pdf")):
            shutil.copy2(f, dest / "input" / "negatywne" / f.name)
            neg += 1
    return n, neg


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dest")
    ap.add_argument("--src", default=None)
    a = ap.parse_args()
    n, neg = prepare(Path(a.dest), Path(a.src) if a.src else default_src())
    print(f"scans: {n} pdfs, negatives: {neg} pdfs -> {a.dest}")


if __name__ == "__main__":
    main()
