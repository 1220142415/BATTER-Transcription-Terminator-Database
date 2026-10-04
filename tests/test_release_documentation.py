from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseDocumentationTests(unittest.TestCase):
    def test_release_notes_explain_current_files_and_evidence(self) -> None:
        release = (ROOT / "docs/releases/v0.4.0.md").read_text(encoding="utf-8")
        for required in (
            "genomes/<GCF 组装编号>/", "`metadata.tsv`", "`endpoints.gff3.gz`",
            "`gene_associations.tsv.gz`", "`condition_observations.tsv.gz`",
            "29,460", "1,061", "196 条", "345 条", "2,277 条",
            "CP000100.1", "NC_007604.1", "BigWig", "SHA256SUMS.txt",
        ):
            with self.subTest(required=required):
                self.assertIn(required, release)
        self.assertIn("网页不把 JSON 当作阅读或下载入口", release)

    def test_docs_and_readme_point_to_current_release(self) -> None:
        docs = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").rglob("*.md"))
        self.assertEqual(docs, [
            "docs/PROMOTER_COMPARISON.md", "docs/SOURCES.md", "docs/UI_REVIEW.md", "docs/USAGE_ANALYTICS.md",
            "docs/deployment.md", "docs/releases/v0.4.0.md",
        ])
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/releases/v0.4.0.md", readme)
        self.assertIn("docs/deployment.md", readme)
        self.assertNotIn("docs/releases/v0.3.0.md", readme)


if __name__ == "__main__":
    unittest.main()
