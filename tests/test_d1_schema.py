"""Production schema fixture and retained legacy-link contract."""
import sqlite3
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class D1SchemaTests(unittest.TestCase):
    def test_schema_accepts_reference_with_two_independent_studies(self):
        with sqlite3.connect(":memory:") as connection:
            connection.executescript((REPO_ROOT / "database/schema.sql").read_text(encoding="utf-8"))
            connection.executescript((REPO_ROOT / "tests/fixtures/d1-seed.sql").read_text(encoding="utf-8"))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM assemblies").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 6)
            self.assertEqual(connection.execute("SELECT COUNT(*), SUM(record_count) FROM tracks").fetchone(), (2, 2848))
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_legacy_accession_url_redirects_to_genome_search(self) -> None:
        builder = (REPO_ROOT / "scripts/build_v0_4_site.py").read_text(encoding="utf-8")
        script = (REPO_ROOT / "site/assets/genome-index.js").read_text(encoding="utf-8")
        self.assertIn('site_root / "accession-range-demo.html"', builder)
        self.assertIn('params.get("accession")', builder)
        self.assertIn('searchParams.set("search",value)', builder)
        self.assertIn('URLSearchParams', script)
        self.assertNotIn("data-accession-demo", builder)
        self.assertNotIn("accession-range-demo.js", builder)
