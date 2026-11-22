import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odw2json import profiles
from odw2json.profiles import ProfileError


def write(d, name, text):
    (Path(d) / f"{name}.yaml").write_text(text, encoding="utf-8")


class ProfileLoadTests(unittest.TestCase):
    def test_shipped_profiles(self):
        names = profiles.list_profiles()
        self.assertIn("text", names)
        self.assertIn("ocr", names)
        self.assertFalse(profiles.load_profile("text").ocr_enabled)
        self.assertTrue(profiles.load_profile("ocr").ocr_enabled)

    def test_default_is_ocr(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ODW2JSON_PROFILE", None)
            self.assertEqual(profiles.resolve_name(None), "ocr")

    def test_precedence_arg_over_env(self):
        with mock.patch.dict(os.environ, {"ODW2JSON_PROFILE": "text"}):
            self.assertEqual(profiles.resolve_name(None), "text")
            self.assertEqual(profiles.resolve_name("ocr"), "ocr")

    def test_ingest_config(self):
        cfg = profiles.load_profile("text").ingest_config()
        self.assertEqual(cfg["ocr"]["enabled"], False)

    def test_unknown_profile_lists_choices(self):
        with self.assertRaises(ProfileError) as cm:
            profiles.load_profile("nope")
        self.assertIn("ocr", str(cm.exception))

    def test_unknown_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "x", "description: x\nocrr: {enabled: true}\n")
            with self.assertRaises(ProfileError):
                profiles.load_profile("x", d)

    def test_unknown_reader_kind_fails_loudly(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "llm", "description: x\nreader: {kind: remote-api, model: m}\n")
            with self.assertRaises(ProfileError) as cm:
                profiles.load_profile("llm", d)
            self.assertIn("reader", str(cm.exception))

    def test_reader_null_ok(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "p", "description: x\nocr: {enabled: false}\nreader: null\n")
            self.assertFalse(profiles.load_profile("p", d).ocr_enabled)

    def test_bad_name_rejected(self):
        with self.assertRaises(ProfileError):
            profiles.load_profile("../evil")

    def test_env_dir(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "mine", "description: mine\nocr: {enabled: false}\n")
            with mock.patch.dict(os.environ, {"ODW2JSON_PROFILES": d}):
                self.assertEqual(profiles.list_profiles(), ["mine"])


if __name__ == "__main__":
    unittest.main()
