from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from . import factory, profiles
from .pipeline import default_workers, process_input


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="odw2json", description="PDF cases -> JSON (UZP contract)")
    ap.add_argument("--input", default="./input", help="folder with <case>/*.pdf (default ./input)")
    ap.add_argument("--output", default="./output", help="folder for <case>/<name>.json (default ./output)")
    ap.add_argument("--recipes", default=None, help="folder with <class>.yaml recipes (default ./recipes or env ODW2JSON_RECIPES)")
    ap.add_argument("--rejected-json", choices=["{}", "empty", "none"], default=os.environ.get("ODW2JSON_REJECTED_JSON", "{}"),
                    help="output for a document of no class: '{}' (default, UZP: empty .json), 'empty' (0 bytes) or 'none' (no file)")
    ap.add_argument("--profile", default=None,
                    help=f"processing profile from profiles/<name>.yaml (default env ODW2JSON_PROFILE, else {profiles.DEFAULT_PROFILE}; "
                         f"available: {', '.join(profiles.list_profiles()) or 'none'}); see docs/PROFILES.md")
    ap.add_argument("--workers", type=int, default=None,
                    help=f"parallel worker processes (default env ODW2JSON_WORKERS, else min(4, cpu_count // 2) = {default_workers()} here)")
    ap.add_argument("--stats", default=None, help="write per-document timings (JSON) to this file (used by eval.bench)")
    args = ap.parse_args(argv)
    if args.workers is not None and args.workers < 1:
        ap.error("--workers must be >= 1")
    workers = args.workers if args.workers is not None else default_workers()
    if args.recipes:
        os.environ["ODW2JSON_RECIPES"] = args.recipes
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from .engine import RecipeError

    try:
        profile = profiles.resolve_name(args.profile)
        prof = profiles.load_profile(profile)  # fail loudly before processing anything
    except profiles.ProfileError as e:
        print(f"profile error: {e}", file=sys.stderr)
        return 2
    os.environ["ODW2JSON_PROFILE"] = profile  # inherited by worker processes
    if prof.reader and prof.reader.get("kind") == "llm":
        from .llm.fetch import ensure_model  # first run: download the weights once (sha256 checked); offline = skipped

        ensure_model(prof.reader)
    try:
        factory.recipe_engine()  # fail loudly before processing anything
    except RecipeError as e:
        print(f"recipe error: {e}", file=sys.stderr)
        return 2
    logging.getLogger("odw2json").info("profile %s, %d worker(s)", profile, workers)
    stats: dict = {}
    results = process_input(args.input, args.output, rejected_json=args.rejected_json, workers=workers, profile=profile, stats=stats)
    if args.stats:
        with open(args.stats, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=1)
    total = sum(len(r.documents) for r in results)
    written = sum(1 for r in results for d in r.documents if d.output_name)
    print(f"{len(results)} cases, {total} pdfs, {written} json written, {total - written} rejected/failed")
    failed = sum(1 for r in results for d in r.documents if d.warnings)
    if total and failed == total:
        print("every PDF failed; check the log above (dependencies installed? pip install -r requirements.txt)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
