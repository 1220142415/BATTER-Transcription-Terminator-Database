import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stage_site


class StageSiteCliTests(unittest.TestCase):
    def test_build_failure_is_actionable_locally_and_in_github(self):
        for github, expected in (("", "FAIL  missing package 100%\ncheck path"),
                                 ("true", "::error::missing package 100%25%0Acheck path")):
            with self.subTest(github=github), \
                    patch.dict(os.environ, {"GITHUB_ACTIONS": github}), \
                    patch.object(sys, "argv", ["stage_site.py", "--mode", "worker", "--jbrowse-dir", "unused"]), \
                    patch.object(stage_site, "assemble_v04", side_effect=stage_site.StageError("missing package 100%\ncheck path")), \
                    contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(stage_site.main(), 1)
                self.assertEqual(stderr.getvalue(), expected + "\n")
