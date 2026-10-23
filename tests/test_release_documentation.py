from __future__ import annotations

import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseDocumentationTests(unittest.TestCase):
    def test_project_documentation_and_code_are_english(self) -> None:
        paths = list(ROOT.glob("*.md"))
        for directory in ("docs", "scripts", "worker/src", "bted_pipeline", "tests", "database", "site", "jbrowse-plugin/src", ".github", "data"):
            paths.extend(p for p in (ROOT / directory).rglob("*") if p.is_file()
                         and (p.suffix == ".md" or (directory != "data" and p.suffix in {".py", ".js", ".mjs", ".sql", ".html", ".css", ".yml"})))
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(re.search(r"[\u3400-\u9fff]", path.read_text(encoding="utf-8")))

    def test_release_notes_explain_current_files_and_evidence(self) -> None:
        release = (ROOT / "docs/releases/v0.4.0.md").read_text(encoding="utf-8")
        for required in (
            "genomes/<assembly-accession>/", "`metadata.tsv`", "`endpoints.gff3.gz`",
            "`gene_associations.tsv.gz`", "`condition_observations.tsv.gz`",
            "29,460", "1,061", "196", "345", "2,277",
            "CP000100.1", "NC_007604.1", "BigWig", "SHA256SUMS.txt",
        ):
            with self.subTest(required=required):
                self.assertIn(required, release)
        self.assertIn("production ZIP metadata is generated from corrected D1 fields", release)

    def test_docs_and_readme_point_to_current_release(self) -> None:
        for name in ["ARCHITECTURE.md", "COLLECTIONS.md", "D1_METADATA.md", "GENOME_METADATA.md", "SOURCES.md", "deployment.md", "releases/current.md"]:
            self.assertTrue((ROOT / "docs" / name).is_file(), name)
        self.assertFalse((ROOT / "prototype").exists())
        self.assertTrue((ROOT / "database/schema.sql").is_file())
        self.assertTrue((ROOT / "worker/src/worker.js").is_file())
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
