from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import sys
import uuid
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / "tmp"
TEMP_ROOT.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / "scripts"))

import build_assembly_downloads  # noqa: E402
import build_v0_3_site  # noqa: E402
import stage_site  # noqa: E402
from v03_tables import iter_endpoint_feature_lines  # noqa: E402


@contextmanager
def temporary_directory() -> Iterator[Path]:
    path = TEMP_ROOT / f"v03-site-test-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def feature_lines(path: Path) -> list[str]:
    return [
        line.rstrip("\n")
        for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
        if line.strip() and not line.startswith("#")
    ]


class V03SiteBuildTests(unittest.TestCase):
    def test_pages_and_downloads_are_materialized_from_merged_release(self) -> None:
        with temporary_directory() as root:
            site = root / "site"
            stage_site.copy_site_source(site)
            self.assertFalse((site / "records").exists())
            self.assertFalse((site / "assemblies").exists())
            self.assertFalse((site / "data/catalog.json").exists())
            self.assertFalse((site / "data/assemblies.json").exists())
            self.assertFalse((site / "studies").exists())
            self.assertFalse((site / "bted-augmentation.html").exists())

            downloads = site / "downloads" / build_assembly_downloads.RELEASE_VERSION
            download_catalog = build_assembly_downloads.build(downloads)
            stage_site.copy_v03_download_tables(downloads)
            catalog = build_v0_3_site.build_site(site, downloads)

            self.assertEqual(catalog["release_version"], "v0.3.0")
            self.assertEqual(len(catalog["studies"]), 13)
            self.assertEqual(len(catalog["sources"]), 22)
            self.assertEqual(len(catalog["assemblies"]), 20)
            self.assertEqual(len(list((site / "studies").glob("PMID_*.html"))), 13)
            self.assertEqual(len(list((site / "records").glob("BATTER_S1_*.html"))), 22)
            self.assertEqual(len(list((site / "assemblies").glob("GCF_*.html"))), 20)
            self.assertEqual(sum(entry["record_count"] for entry in catalog["assemblies"]), 28399)

            source_page = (site / "records/BATTER_S1_001.html").read_text(encoding="utf-8")
            audit_page = (site / "records/BATTER_S1_002.html").read_text(encoding="utf-8")
            assembly_page = (site / "assemblies/GCF_000005845.1.html").read_text(encoding="utf-8")
            audit_assembly_page = (site / "assemblies/GCF_000005845.2.html").read_text(encoding="utf-8")
            self.assertIn("../downloads/v0.3.0/studies/PMID_29606352/endpoints.gff3.gz", source_page)
            self.assertIn("../downloads/v0.3.0/studies/PMID_29606352/metadata.tsv", source_page)
            self.assertIn("../downloads/v0.3.0/studies/PMID_29606352/metadata.json", source_page)
            self.assertIn("../downloads/v0.3.0/assemblies/GCF_000005845.1/endpoints.gff3", assembly_page)
            self.assertNotIn("PMID_38030608/endpoints.gff3.gz", audit_page)
            self.assertIn("PMID_38030608/metadata.tsv", audit_page)
            self.assertNotIn("data/public/v0.3.0", audit_page)
            self.assertNotIn("endpoints.gff3", audit_assembly_page)
            self.assertIn("browser.html?assembly=", source_page)
            self.assertNotIn("browser.html?assembly=", audit_page)
            self.assertNotIn("evidence-layers-preview.html", audit_page)
            combined_study_page = (site / "studies/PMID_33319794.html").read_text(encoding="utf-8")
            self.assertIn("Study package · PMID 33319794", combined_study_page)
            self.assertIn("BATTER_S1_010", combined_study_page)
            self.assertIn("BATTER_S1_015", combined_study_page)
            catalog_page = (site / "catalog.html").read_text(encoding="utf-8")
            self.assertIn("downloads/v0.3.0/studies/PMID_29606352/endpoints.gff3.gz", catalog_page)
            self.assertIn("downloads/v0.3.0/studies/PMID_31594819/gene_associations.tsv.gz", catalog_page)
            self.assertIn("downloads/v0.3.0/studies/PMID_37402717/condition_observations.tsv.gz", catalog_page)
            self.assertNotIn("downloads/v0.3.0/endpoints.gff3.gz", catalog_page)
            home_page = (site / "index.html").read_text(encoding="utf-8")
            self.assertIn("Genome browser", home_page)
            self.assertIn('href="browser.html"', home_page)
            self.assertNotIn("downloads/v0.3.0/sources.json", catalog_page)
            self.assertNotIn("downloads/v0.3.0/sources.tsv", catalog_page)
            self.assertNotRegex(catalog_page, r"endpoints\.(?:csv|tsv(?:\.gz)?|bed)")
            self.assertNotIn("annotations.jsonl.gz", catalog_page)
            self.assertNotIn("Augmentation", catalog_page)
            self.assertNotIn("Quick search", (site / "sources.html").read_text(encoding="utf-8"))
            self.assertNotIn("Find this genome by accession", (site / "assemblies/GCF_000739105.1.html").read_text(encoding="utf-8"))
            self.assertNotIn("Download by genome", catalog_page)
            self.assertNotIn('data-download-choice', catalog_page)
            self.assertIn('data-download-choice', (site / "sources.html").read_text(encoding="utf-8"))
            self.assertIn('data-browser-wrapper', (site / "browser.html").read_text(encoding="utf-8"))
            self.assertIn('data-browser-coverage', (site / "browser.html").read_text(encoding="utf-8"))
            self.assertIn('browser-wrapper.js', (site / "browser.html").read_text(encoding="utf-8"))
            about_redirect = (site / "about.html").read_text(encoding="utf-8")
            self.assertIn('methodology.html', about_redirect)
            search_redirect = (site / "accession-range-demo.html").read_text(encoding="utf-8")
            self.assertIn('params.get("accession")', search_redirect)
            self.assertIn('search', search_redirect)
            quick_search_redirect = (site / "quick-search.html").read_text(encoding="utf-8")
            self.assertIn('params.get("query")', quick_search_redirect)
            self.assertIn('target.searchParams.set("search", value)', quick_search_redirect)

            for page_path in site.rglob("*.html"):
                page = page_path.read_text(encoding="utf-8")
                self.assertNotIn('<span>BTED v0.2.0</span>', page, str(page_path))
                self.assertNotIn('content="BTED v0.2.0"', page, str(page_path))
                self.assertNotIn("bted-augmentation.html", page, str(page_path))

            assembly_json = json.loads((site / "data/assemblies.json").read_text(encoding="utf-8"))
            release_config = json.loads((site / "assets/data-release.json").read_text(encoding="utf-8"))
            self.assertEqual(release_config["baseUrl"], "downloads/v0.3.0")
            self.assertIsNone(release_config["revision"])
            self.assertEqual(assembly_json["release_version"], "v0.3.0")
            self.assertTrue(assembly_json["assemblies"]["GCF_000005845.1"]["gff3_url"].startswith("downloads/v0.3.0/"))
            self.assertIsNone(assembly_json["assemblies"]["GCF_000005845.2"]["gff3_url"])
            self.assertNotIn("bed_url", assembly_json["assemblies"]["GCF_000005845.1"])
            self.assertNotIn("csv_url", assembly_json["assemblies"]["GCF_000005845.1"])

            first_endpoint, first_feature = next(iter_endpoint_feature_lines(build_assembly_downloads.RELEASE_ROOT))
            source_index = {source["source_id"]: source for source in build_assembly_downloads.load_sources()}
            first_source = source_index[first_endpoint["source_id"]]
            first_study_dir = downloads / "studies" / f"PMID_{first_source['pmid']}"
            with gzip.open(first_study_dir / "endpoints.gff3.gz", "rt", encoding="utf-8") as handle:
                study_features = [
                    line.rstrip("\n")
                    for line in handle
                    if line.strip() and not line.startswith("#")
                ]
            study_metadata = json.loads((first_study_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(len(study_features), study_metadata["record_count"])
            self.assertIn(first_feature, study_features)
            self.assertIn(first_endpoint["source_id"], [source["source_id"] for source in study_metadata["sources"]])

            source_dir = downloads / "records" / first_endpoint["source_id"]
            self.assertIn(first_feature, feature_lines(source_dir / "endpoints.gff3"))
            source_metadata = json.loads((source_dir / "metadata.json").read_text(encoding="utf-8"))
            expected_source = next(source for source in study_metadata["sources"] if source["source_id"] == first_endpoint["source_id"])
            self.assertEqual(source_metadata["source_metadata"], expected_source)
            self.assertIn("repository archive", source_metadata["source_metadata_context"])
            self.assertIn("not v0.3.0 download paths", source_metadata["source_metadata_context"])

            _, annotated_feature = next(
                (row, line)
                for row, line in iter_endpoint_feature_lines(build_assembly_downloads.RELEASE_ROOT)
                if row["source_id"] == "BATTER_S1_006"
            )
            annotated_source_gff3 = downloads / "records/BATTER_S1_006/endpoints.gff3"
            annotated_assembly_gff3 = downloads / "assemblies/GCF_000006885.1/endpoints.gff3"
            self.assertIn("ann_", annotated_feature)
            self.assertIn(annotated_feature, feature_lines(annotated_source_gff3))
            self.assertIn(annotated_feature, feature_lines(annotated_assembly_gff3))

            for assembly, entry in download_catalog["assemblies"].items():
                assembly_dir = downloads / "assemblies" / assembly
                metadata_path = assembly_dir / "metadata.json"
                self.assertTrue(metadata_path.is_file(), assembly)
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                self.assertEqual(metadata["record_count"], entry["record_count"], assembly)
                if entry["record_count"]:
                    self.assertEqual(len(feature_lines(assembly_dir / "endpoints.gff3")), entry["record_count"], assembly)
                    self.assertTrue(all("endpoint_field_defaults" in source for source in metadata["sources"]), assembly)
                    self.assertTrue(all("source_metadata" in source for source in metadata["sources"]), assembly)
                    self.assertTrue(all("repository archive" in source["source_metadata_context"] for source in metadata["sources"]), assembly)
                    self.assertTrue(all("not v0.3.0 download paths" in source["source_metadata_context"] for source in metadata["sources"]), assembly)
                else:
                    self.assertFalse((assembly_dir / "endpoints.gff3").exists(), assembly)

            source_feature_count = sum(
                len(feature_lines(path)) for path in (downloads / "records").glob("*/endpoints.gff3")
            )
            self.assertEqual(source_feature_count, 28399)
            study_dirs = sorted((downloads / "studies").glob("PMID_*"))
            self.assertEqual(len(study_dirs), 13)
            for study_dir in study_dirs:
                study_metadata = json.loads((study_dir / "metadata.json").read_text(encoding="utf-8"))
                self.assertEqual(study_dir.name, f"PMID_{study_metadata['pmid']}")
                self.assertTrue((study_dir / "metadata.tsv").is_file())
                if int(study_metadata["record_count"]) > 0:
                    self.assertTrue((study_dir / "endpoints.gff3.gz").is_file())
                else:
                    zero_study_page = (site / f"studies/{study_dir.name}.html").read_text(encoding="utf-8")
                    self.assertNotIn("endpoints.gff3.gz", zero_study_page)
                self.assertTrue(study_metadata["sources"])
            self.assertEqual(
                {path.name for path in downloads.iterdir()},
                {"studies", "release.json", "SHA256SUMS.txt", "records", "assemblies", "catalog.json"},
            )
            endpoint_formats = {"endpoints.csv", "endpoints.tsv", "endpoints.tsv.gz", "endpoints.bed"}
            self.assertFalse([
                path for path in downloads.rglob("*") if path.is_file() and path.name in endpoint_formats
            ])
            self.assertFalse(list(downloads.rglob("*.jsonl.gz")))
            self.assertFalse((downloads / "endpoints.gff3.gz").exists())
            self.assertFalse((downloads / "gene_associations.tsv.gz").exists())
            self.assertFalse((downloads / "condition_observations.tsv.gz").exists())
            self.assertFalse((downloads / "sources.json").exists())
            self.assertFalse((downloads / "sources.tsv").exists())
            self.assertTrue((downloads / "release.json").is_file())
            self.assertTrue((downloads / "SHA256SUMS.txt").is_file())

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/validate-site.py"), str(site)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            commit = "0123456789abcdef0123456789abcdef01234567"
            hf_base = f"https://huggingface.co/datasets/liurulong/terminator/resolve/{commit}/v0.3.0"
            remote_site = root / "remote-site"
            stage_site.copy_site_source(remote_site)
            remote_catalog = build_v0_3_site.build_site(
                remote_site,
                downloads,
                hf_data_base_url=hf_base,
            )
            remote_config = json.loads((remote_site / "assets/data-release.json").read_text(encoding="utf-8"))
            self.assertEqual(remote_config["baseUrl"], hf_base)
            self.assertEqual(remote_config["revision"], commit)
            self.assertTrue(remote_catalog["downloads"]["release_manifest"].startswith(hf_base))
            remote_assemblies = json.loads((remote_site / "data/assemblies.json").read_text(encoding="utf-8"))
            self.assertTrue(remote_assemblies["assemblies"]["GCF_000739105.1"]["gff3_url"].startswith(hf_base))
            remote_study = (remote_site / "catalog.html").read_text(encoding="utf-8")
            self.assertIn(f"{hf_base}/studies/PMID_29606352/endpoints.gff3.gz", remote_study)


if __name__ == "__main__":
    unittest.main()
