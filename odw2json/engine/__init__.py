"""Generic recipe engine: classification with reject and field extraction, driven only by recipes/*.yaml.

The engine knows no document type. A class = one recipe YAML (+ its output JSON skeleton).
"""
from .engine import RecipeEngine
from .normalise import register_normaliser, register_validator
from .recipes import Recipe, RecipeError, load_recipes
from .strategies import register_strategy

__all__ = ["RecipeEngine", "Recipe", "RecipeError", "load_recipes", "register_strategy", "register_normaliser", "register_validator"]
