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

    def test_config_validation_matches_deployed_endpoint_category(self):
        endpoint = {"trackId": "bted_v04_endpoint", "type": "FeatureTrack",
                    "category": ["Experimental 3′ ends", "PMID 123"]}
        signals = [{"trackId": f"signal-{i}", "type": "MultiQuantitativeTrack",
                    "name": "experimental signal", "metadata": {"btedMirroredSignal": True},
                    "adapter": {"subadapters": [
                        {"source": "plus", "color": stage_site.PLUS_STRAND_COLOR},
                        {"source": "minus", "color": stage_site.MINUS_STRAND_COLOR}]}}
                   for i in range(4)]
        config = {"assemblies": [{"sequence": {"trackId": "reference"}}],
                  "tracks": [endpoint, *signals],
                  "defaultSession": {"views": [{"tracks": [
                      {"configuration": track_id} for track_id in
                      ["reference", endpoint["trackId"], *(t["trackId"] for t in signals)]]}]}}
        catalog = {"assemblies": {"GCF_TEST": {"config": "test.config.json"}}}
        with patch.object(stage_site, "_read_config", return_value=config), \
                patch.object(stage_site, "signal_assets", return_value={}):
            stage_site.validate_v04_jbrowse_configs(Path("unused"), {}, catalog, 1)
            endpoint["category"] = ["Uncategorized"]
            with self.assertRaisesRegex(stage_site.StageError, "not clearly categorized"):
                stage_site.validate_v04_jbrowse_configs(Path("unused"), {}, catalog, 1)
