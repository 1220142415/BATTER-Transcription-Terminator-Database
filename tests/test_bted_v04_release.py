from __future__ import annotations

import gzip
import csv
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from bted_v04_common import INTERNAL_REL, V03_ARCHIVE_REL, V03_ARCHIVE_SUMS_REL, V04_REL, load_json, sha256_file
from build_bted_v0_4_release import EXPECTED_CASCINO_COUNTS, verify_v03_archive
from validate_bted_v0_4 import validate_release


class BtedV04ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = ROOT
        cls.report = validate_release(ROOT)
        cls.release = load_json(ROOT / V04_REL / "release.json")

    def test_full_release_row_and_table_contract(self) -> None:
        counts = self.report["counts"]
        self.assertEqual(self.report["old_endpoint_rows_compared"], 28_399)
        self.assertEqual(counts["endpoint_count"], 29_460)
        self.assertEqual(self.report["cascino_source_counts"], EXPECTED_CASCINO_COUNTS)
        self.assertEqual(self.report["linked_gene_rows"], 460)
        self.assertEqual(self.report["unlinked_gene_rows"], 345)
        self.assertEqual(self.report["condition_observations"], 2_277)

    def test_secondary_cascino_candidates_are_not_public(self) -> None:
        provenance = load_json(ROOT / INTERNAL_REL / "source_provenance.json")
        decision = provenance["cascino_decision"]
        self.assertEqual(decision["included_total"], 1_061)
        self.assertEqual(decision["excluded_secondary_rows"], 196)
        original_audit = decision["independent_original_table_audit"]
        self.assertEqual(original_audit["status"], "pass")
        self.assertEqual(original_audit["missing_rows"], 0)
        self.assertEqual(original_audit["extra_rows"], 0)
        self.assertEqual(
            original_audit["supplementary_zip_sha256"],
            "141c5eaf5d7e1923ec89d8ebf2db5d70255ded2b1e1a11f560375ee759b11071",
        )
        self.assertEqual(original_audit["license_verification"]["license"], "CC BY 4.0")
        source_status = {
            source["source_id"]: source["publication_status"]["release_status"]
            for source in provenance["sources"]
        }
        self.assertEqual(source_status["BATTER_S1_002"], "audit_only")
        trs = next(source for source in provenance["sources"] if source["source_id"] == "BATTER_S1_002")
        self.assertEqual(trs["license_status"]["redistribution_status"], "verified_redistributable")
        self.assertEqual(trs["publication_status"]["redistribution_status"], "verified_redistributable")
        self.assertEqual(int(trs["publication_status"]["record_count"]), 0)
        self.assertEqual(trs["publication_status"]["has_jbrowse"], "false")
        metadata = ROOT / V04_REL / "genomes/GCF_000005845.2/metadata.tsv"
        with metadata.open(encoding="utf-8", newline="") as handle:
            row = next(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(row["redistribution_status"], "verified_redistributable")
        self.assertEqual(row["release_status"], "audit_only")
        self.assertEqual(row["record_count"], "0")
        self.assertEqual(row["study_gff3"], "")
        self.assertNotIn("BTED_EXT_2026_101", source_status)
        self.assertFalse(any(
            source_id.startswith("BTED_EXT_2026_") and source_id not in EXPECTED_CASCINO_COUNTS
            for source_id in source_status
        ))

        release_dir = ROOT / V04_REL
        metadata_lines = (release_dir / "genomes/GCF_000012525.1/metadata.tsv").read_text(encoding="utf-8").splitlines()
        self.assertIn("evidence_class", metadata_lines[0].split("\t"))
        header = metadata_lines[0].split("\t")
        values = [dict(zip(header, line.split("\t"))) for line in metadata_lines[1:]]
        self.assertEqual(
            {row["source_id"] for row in values if row["evidence_class"] == "author_called_endpoint"},
            set(EXPECTED_CASCINO_COUNTS),
        )
        cascino_features = 0
        for path in (release_dir / "genomes/GCF_000012525.1/studies/PMID_42148773").glob("endpoints.gff3.gz"):
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if line and not line.startswith("#"):
                        self.assertIn("author_category=defined%20end", line)
                        cascino_features += 1
        self.assertEqual(cascino_features, 1_061)

    def test_v03_archive_is_verified_and_v02_archive_is_unchanged(self) -> None:
        archive_info = verify_v03_archive(ROOT)
        self.assertEqual(archive_info["file_count"], 43)
        self.assertEqual(len((ROOT / V03_ARCHIVE_SUMS_REL).read_text(encoding="utf-8").splitlines()), 43)
        self.assertTrue((ROOT / V03_ARCHIVE_REL).is_file())

        archived_release = self.release["legacy_archive"]["v0.2.0"]
        v02_path = ROOT / archived_release["path"]
        self.assertEqual(sha256_file(v02_path), archived_release["sha256"])

    def test_public_package_has_no_per_study_json_entry_points(self) -> None:
        release_dir = ROOT / V04_REL
        self.assertEqual(self.release["counts"]["study_count"], 14)
        self.assertEqual(self.release["counts"]["genome_study_count"], 23)
        self.assertFalse(any(
            path.name == "metadata.json" or (path.suffix == ".json" and path.name != "release.json")
            for path in release_dir.rglob("*")
            if path.is_file()
        ))


if __name__ == "__main__":
    unittest.main()
