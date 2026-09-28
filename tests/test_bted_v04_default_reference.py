"""The static JBrowse view starts on the longest indexed reference sequence."""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import stage_site  # noqa: E402


class DefaultReferenceTests(unittest.TestCase):
    def test_longest_fai_record_and_name_tie_break(self) -> None:
        path = ROOT / "tmp" / f"fai-selection-{uuid.uuid4().hex}.fai"
        path.parent.mkdir(exist_ok=True)
        try:
            path.write_text("plasmid\t120\t0\t70\t71\nchr_z\t500\t0\t70\t71\nchr_a\t500\t0\t70\t71\n", encoding="utf-8")
            self.assertEqual(stage_site._longest_fai_reference(path, "test"), ("chr_a", 500))
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
