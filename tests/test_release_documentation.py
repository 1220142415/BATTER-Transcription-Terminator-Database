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
            "docs/ANNOTATION_RECOVERY.md",
            "docs/D1_METADATA.md", "docs/GENOME_METADATA.md", "docs/HF_REFRESH_2026-10-07.md",
            "docs/PROMOTER_COMPARISON.md", "docs/SOURCES.md", "docs/UI_REVIEW.md", "docs/USAGE_ANALYTICS.md",
            "docs/browser-controls.md", "docs/deployment.md", "docs/releases/v0.4.0.md",
        ])
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/releases/v0.4.0.md", readme)
        self.assertIn("docs/deployment.md", readme)
        self.assertNotIn("docs/releases/v0.3.0.md", readme)


    def test_cloudflare_is_production_and_pages_deployment_is_opt_in(self) -> None:
        pages = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("  workflow_dispatch:", pages)
        self.assertNotIn("  push:", pages)
        self.assertIn("  push:", ci)
        self.assertIn("  pull_request:", ci)
        self.assertIn("--mode pages", ci)
        self.assertIn("--mode worker", ci)


if __name__ == "__main__":
    unittest.main()
