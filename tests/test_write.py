import json
import tempfile
import unittest
from pathlib import Path

from odw2json import write


class SkeletonTests(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(set(write.classes()), {"odwolanie", "pelnomocnictwo", "przelew"})

    def test_skeleton_is_fresh_copy(self):
        a = write.skeleton("przelew")
        a["przelew_bankowy"]["kwota"] = 1
        self.assertIsNone(write.skeleton("przelew")["przelew_bankowy"]["kwota"])

    def test_unsafe_class(self):
        with self.assertRaises(KeyError):
            write.skeleton("../README")

    def test_unknown_class(self):
        with self.assertRaises(KeyError):
            write.skeleton("nope")


class CompleteTests(unittest.TestCase):
    def test_fills_missing_keys_with_null(self):
        out = write.complete({"przelew_bankowy": {"kwota": 5.0}}, "przelew")
        self.assertEqual(out["przelew_bankowy"]["kwota"], 5.0)
        self.assertIsNone(out["przelew_bankowy"]["tytul"])

    def test_empty_list_gets_one_null_item(self):
        out = write.complete({"Odwolujacy": []}, "odwolanie")
        self.assertEqual(len(out["Odwolujacy"]), 1)
        self.assertIsNone(out["Odwolujacy"][0]["nip"])
        self.assertIsNone(out["Odwolujacy"][0]["pelnomocnik"]["mail"])

    def test_multiple_list_items_kept_and_completed(self):
        data = {"mocodawca": [{"data": {"nip": "1"}}, {"data": {"nip": "2"}, "podpisujacy": [{"imie_nazwisko": "A"}, {"imie_nazwisko": "B"}]}]}
        out = write.complete(data, "pelnomocnictwo")
        self.assertEqual(len(out["mocodawca"]), 2)
        self.assertEqual(len(out["mocodawca"][1]["podpisujacy"]), 2)
        self.assertEqual(len(out["mocodawca"][0]["podpisujacy"]), 1)
        self.assertIsNone(out["mocodawca"][0]["data"]["krs"])
        self.assertEqual(len(out["pelnomocnicy"]), 1)

    def test_drops_unknown_keys(self):
        out = write.complete({"przelew_bankowy": {"foo": 1}, "bar": 2}, "przelew")
        self.assertEqual(set(out), {"przelew_bankowy"})
        self.assertNotIn("foo", out["przelew_bankowy"])

    def test_dict_for_list_is_wrapped(self):
        out = write.complete({"Odwolujacy": {"nazwa": "X"}}, "odwolanie")
        self.assertEqual(out["Odwolujacy"][0]["nazwa"], "X")

    def test_none_for_object_gives_skeleton(self):
        out = write.complete({"OdwolanieKIO": None}, "odwolanie")
        self.assertIn("data", out["OdwolanieKIO"])


class WriteTests(unittest.TestCase):
    def test_write_json_utf8_no_ascii_escape(self):
        with tempfile.TemporaryDirectory() as d:
            p = write.write_json(Path(d) / "case" / "x.json", {"a": "Łódź"})
            raw = p.read_bytes()
            self.assertIn("Łódź".encode("utf-8"), raw)
            self.assertEqual(json.loads(raw.decode("utf-8")), {"a": "Łódź"})


if __name__ == "__main__":
    unittest.main()
