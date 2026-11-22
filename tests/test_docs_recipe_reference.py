"""The recipe reference in docs/ADDING_A_DOCUMENT_CLASS.md names every registered strategy, normaliser, validator."""
import unittest
from pathlib import Path

from odw2json.engine.normalise import NORMALISERS, VALIDATORS
from odw2json.engine.strategies import STRATEGIES

DOC = Path(__file__).resolve().parents[1] / "docs" / "ADDING_A_DOCUMENT_CLASS.md"


class RecipeReferenceInSyncTests(unittest.TestCase):
    def test_every_registered_name_is_documented(self):
        text = DOC.read_text(encoding="utf-8")
        missing = [n for n in [*STRATEGIES, *NORMALISERS, *VALIDATORS] if f"`{n}`" not in text]
        self.assertEqual(missing, [], f"document these in {DOC.name}")


if __name__ == "__main__":
    unittest.main()
