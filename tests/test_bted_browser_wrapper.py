"""Static contract checks for the BTED user-facing JBrowse wrapper."""

from __future__ import annotations

import json
import re
import shutil
import sys
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = REPO_ROOT / "site"
TMP_ROOT = REPO_ROOT / "tmp"
TMP_ROOT.mkdir(exist_ok=True)
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_assembly_downloads  # noqa: E402
import build_v0_3_site  # noqa: E402
import stage_site  # noqa: E402


class TestBtedBrowserWrapper(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.wrapper = (SITE_ROOT / "browser.html").read_text(encoding="utf-8")
        cls.script = (SITE_ROOT / "assets/browser-wrapper.js").read_text(encoding="utf-8")
        cls.temp_root = TMP_ROOT / f"bted-browser-wrapper-{uuid.uuid4().hex}"
        cls.temp_root.mkdir()
        cls.generated_site = cls.temp_root / "site"
        stage_site.copy_site_source(cls.generated_site)
        downloads = cls.generated_site / "downloads" / build_assembly_downloads.RELEASE_VERSION
        build_assembly_downloads.build(downloads)
        stage_site.copy_v03_download_tables(downloads)
        cls.catalog = build_v0_3_site.build_site(cls.generated_site, downloads)
        cls.assemblies = json.loads((cls.generated_site / "data/assemblies.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp_root)

    def test_wrapper_loads_tracks_from_release_metadata(self) -> None:
        generated_wrapper = (self.generated_site / "browser.html").read_text(encoding="utf-8")
        self.assertIn('data-browser-wrapper', generated_wrapper)
        self.assertIn('data-browser-assembly-select', generated_wrapper)
        self.assertIn('data-browser-frame', generated_wrapper)
        self.assertIn('browser-wrapper.js', generated_wrapper)
        self.assertIn("jbrowse/index.html?", self.script)
        self.assertIn('data/assemblies.json', self.script)
        self.assertIn('data-browser-coverage', generated_wrapper)
        self.assertIn('url.searchParams.set("assembly"', self.script)
        self.assertIn('assemblySelect.value = assembly.assembly.accession', self.script)
        self.assertIn('url.searchParams.set("assembly", assembly.assembly.accession)', self.script)
        self.assertNotIn("SOURCES_BY_ASSEMBLY", generated_wrapper + self.script)
        self.assertNotIn("COMBINED_CONFIGS", generated_wrapper + self.script)

    def test_wrapper_exposes_source_links_and_source_switch(self) -> None:
        for token in (
            "Publication",
            "PubMed",
            "DOI",
            "Raw data",
            "Download GFF3",
            "Dataset details",
            "Source track",
            "All source tracks",
        ):
            self.assertIn(token, self.wrapper + self.script)
        self.assertIn("source_id", self.script)
        self.assertIn("Studies on the same assembly remain separate", self.script)
        self.assertIn("renderStudyLinks", self.script)
        self.assertIn("jbrowse_static_config_url", self.script)
        self.assertIn("new URL(path, window.location.href)", self.script)
        self.assertIn('["loc", "session", "tracks", "highlight"]', self.script)
        self.assertNotIn('["loc", "session", "tracks", "highlight", "assembly"]', self.script)
        self.assertNotIn('query.get("config")', self.script)
        self.assertNotIn("bted-catalogue-v03-preview", self.script)

    def test_static_metadata_has_links_for_single_and_shared_assemblies(self) -> None:
        assemblies = self.assemblies["assemblies"]
        checks = {
            "GCF_000005845.1": {"BATTER_S1_001"},
            "GCF_000739105.1": {"BATTER_S1_007", "BATTER_S1_013"},
        }
        self.assertEqual(
            assemblies["GCF_000739105.1"]["jbrowse_config_url"],
            "/api/assemblies/GCF_000739105.1/jbrowse-config",
        )
        self.assertEqual(
            assemblies["GCF_000739105.1"]["jbrowse_static_config_url"],
            "jbrowse/assemblies/GCF_000739105.1.config.json",
        )
        for accession, source_ids in checks.items():
            tracks = {track["source_id"]: track for track in assemblies[accession]["tracks"]}
            self.assertEqual(set(tracks), source_ids)
            for source_id in source_ids:
                track = tracks[source_id]
                self.assertRegex(track["publication_url"], r"pubmed\.ncbi\.nlm\.nih\.gov/\d+")
                self.assertRegex(track["doi_url"], r"https://doi\.org/.+")
                self.assertTrue(track["raw_data_accession"])
                self.assertTrue(track["raw_data_url"])
                self.assertEqual(
                    track["jbrowse_static_config_url"],
                    f"jbrowse/{track['source_id']}.config.json",
                )
                self.assertIn(source_id, track["gff3_url"])
                self.assertEqual(track["record_url"], f"records/{source_id}.html")

    def test_generated_public_links_use_wrapper_and_audit_source_stays_out(self) -> None:
        for source in self.catalog["sources"]:
            page = (self.generated_site / source["record_url"]).read_text(encoding="utf-8")
            self.assertEqual("browser.html?assembly=" in page, source["has_jbrowse"], source["source_id"])
            if source["has_jbrowse"]:
                self.assertIn(
                    f"browser.html?assembly={source['assembly']}&amp;source_id={source['source_id']}",
                    page,
                )
        for assembly in self.catalog["assemblies"]:
            page = (self.generated_site / assembly["page_url"]).read_text(encoding="utf-8")
            self.assertEqual("browser.html?assembly=" in page, bool(assembly["browser_config"]), assembly["assembly"])
        audit_page = (self.generated_site / "records/BATTER_S1_002.html").read_text(encoding="utf-8")
        self.assertNotIn("browser.html?assembly=", audit_page)
        self.assertNotIn("BATTER_S1_002--endpoints-gff3", self.script)

    def test_legacy_accession_search_moves_to_genome_directory(self) -> None:
        redirect = (self.generated_site / "accession-range-demo.html").read_text(encoding="utf-8")
        site_script = (SITE_ROOT / "assets/site.js").read_text(encoding="utf-8")
        self.assertIn('params.get("accession")', redirect)
        self.assertIn('target.searchParams.set("search", value)', redirect)
        self.assertIn('params.get("search") || params.get("accession")', site_script)
        self.assertNotIn("accession-range-demo.js", redirect)


if __name__ == "__main__":
    unittest.main()
