"""Default component wiring: T003 ingestor (text layer + OCR) and the T004 recipe engine.

The recipes directory comes from env ODW2JSON_RECIPES (the CLI's --recipes sets it), default ./recipes.
The processing profile (`profiles/<name>.yaml`, odw2json/profiles.py) picks the ingestor options: `--profile` >
env ODW2JSON_PROFILE > `ocr`.
"""
from __future__ import annotations

from functools import cache

from .model import Classifier, Extractor, Ingestor


@cache
def ingestor_for(profile: str) -> Ingestor:
    from . import profiles
    from .ingest import default_ingestor as make

    return make(profiles.load_profile(profile).ingest_config())


def default_ingestor() -> Ingestor:
    """Ingestor of the active profile (env ODW2JSON_PROFILE, default `ocr`); an unset env gives today's behaviour."""
    from . import profiles

    return ingestor_for(profiles.resolve_name())


@cache
def recipe_engine():
    """One engine serves as both classifier and extractor (recipes loaded once, reloaded on file change)."""
    from .engine import RecipeEngine

    eng = RecipeEngine()
    eng.recipes  # load eagerly: a broken recipe raises RecipeError here, at startup, not once per document
    return eng


def default_classifier() -> Classifier:
    return recipe_engine()


@cache
def _llm_extractor(engine, model: str, n_ctx: int, threads) -> Extractor:
    from .llm import make_extractor

    return make_extractor(engine, model, n_ctx=n_ctx, threads=threads)


def extractor_for(profile: str) -> Extractor:
    """The recipe engine, wrapped by the grounded local-LLM reader when the profile asks for it
    (`reader: {kind: llm, model: ..}`); the model loads on first use and a missing model leaves the recipe output as is.
    Keyed by the engine, so clearing `recipe_engine`'s cache (new recipes directory) also renews the wrapper."""
    from . import profiles

    engine = recipe_engine()
    reader = profiles.load_profile(profile).reader
    if reader and reader.get("kind") == "llm":
        return _llm_extractor(engine, reader.get("model", "models/Qwen3-1.7B-Q8_0.gguf"), int(reader.get("n_ctx", 4096)), reader.get("threads"))
    return engine


def default_extractor() -> Extractor:
    from . import profiles

    return extractor_for(profiles.resolve_name())


def build_components(profile: str | None = None) -> tuple[Ingestor, Classifier, Extractor]:
    """(ingestor, classifier, extractor) for a profile; what every pool worker builds once."""
    from . import profiles

    name = profiles.resolve_name(profile)
    return ingestor_for(name), default_classifier(), extractor_for(name)
