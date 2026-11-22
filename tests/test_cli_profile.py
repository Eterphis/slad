import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from odw2json import cli


class CliProfileTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))

    def test_unknown_profile_exit_2(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(cli.main(["--profile", "nope", "--input", "x", "--output", "y"]), 2)
        self.assertIn("profile error", err.getvalue())

    def test_profile_and_workers_reach_pipeline(self):
        with mock.patch.object(cli, "process_input", return_value=[]) as m:
            self.assertEqual(cli.main(["--profile", "text", "--workers", "3", "--input", "i", "--output", "o"]), 0)
        kw = m.call_args.kwargs
        self.assertEqual((kw["profile"], kw["workers"]), ("text", 3))
        self.assertEqual(os.environ["ODW2JSON_PROFILE"], "text")

    def test_env_profile_and_workers(self):
        os.environ["ODW2JSON_PROFILE"] = "text"
        os.environ["ODW2JSON_WORKERS"] = "2"
        with mock.patch.object(cli, "process_input", return_value=[]) as m:
            cli.main(["--input", "i", "--output", "o"])
        self.assertEqual((m.call_args.kwargs["profile"], m.call_args.kwargs["workers"]), ("text", 2))

    def test_stats_file(self):
        def fake(*a, **kw):
            kw["stats"].update({"workers": 1, "docs": []})
            return []
        with tempfile.TemporaryDirectory() as d, mock.patch.object(cli, "process_input", side_effect=fake):
            cli.main(["--input", "i", "--output", "o", "--stats", str(Path(d) / "s.json")])
            self.assertEqual(json.loads((Path(d) / "s.json").read_text())["workers"], 1)

    def test_bad_workers(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["--workers", "0"])


if __name__ == "__main__":
    unittest.main()
