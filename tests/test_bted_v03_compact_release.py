"""Regression checks for the compact BTED v0.3.0 release and importer."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import unittest
from pathlib import Path

from scripts.import_bted_v03 import _canonical_data_file_refs
from scripts.validate_bted_v0_3 import (
    RELEASE_FILES,
    RELEASE_REL,
    ROOT,
    _check_lossless_tables,
    _read_tsv_bytes,
    _verify_archive,
    validate_release,
)


class TestCompactV03Release(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.release_dir = ROOT / RELEASE_REL
        cls.legacy_files, cls.archive_count = _verify_archive(ROOT)

    def test_release_reconstructs_all_rows_and_has_only_compact_files(self) -> None:
        summary = validate_release(ROOT)

        self.assertEqual(
            summary,
            {
                "release_version": "v0.3.0",
                "source_count": 22,
                "study_count": 13,
                "endpoint_count": 28_399,
                "annotation_count": 24_887,
                "gene_association_count": 805,
                "unlinked_gene_association_count": 345,
                "condition_observation_count": 2_277,
                "archive_file_count": 153,
            },
        )
        self.assertEqual({path.name for path in self.release_dir.iterdir()}, RELEASE_FILES)
        studies = sorted((self.release_dir / "studies").iterdir())
        self.assertEqual(len(studies), 13)
        for study in studies:
            expected_files = {"endpoints.gff3.gz", "metadata.json", "metadata.tsv"}
            if study.name == "PMID_31594819":
                expected_files.add("gene_associations.tsv.gz")
            if study.name == "PMID_37402717":
                expected_files.add("condition_observations.tsv.gz")
            self.assertEqual({path.name for path in study.iterdir()}, expected_files)
            metadata = json.loads((study / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["pmid"], study.name.removeprefix("PMID_"))
            self.assertEqual(metadata["source_count"], len(metadata["sources"]))
        audit_only = self.release_dir / "studies/PMID_38030608"
        audit_metadata = json.loads((audit_only / "metadata.json").read_text(encoding="utf-8"))
        with gzip.open(audit_only / "endpoints.gff3.gz", "rt", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "##gff-version 3\n")
        self.assertEqual(audit_metadata["record_count"], 0)
        self.assertTrue(audit_metadata["audit_only"])

    def test_any_archived_table_field_change_is_detected(self) -> None:
        cases = (
            (
                "data/public/v0.2.0/records/BATTER_S1_001/endpoints.tsv",
                "Endpoint rows changed for BATTER_S1_001",
            ),
            (
                "data/public/v0.2.0/records/BATTER_S1_006/source_annotations.tsv",
                "Annotation field values changed",
            ),
            (
                "data/public/v0.2.0/records/BATTER_S1_008/gene_associations.tsv",
                "gene_associations.tsv.gz rows or fields changed for BATTER_S1_008",
            ),
            (
                "data/public/v0.2.0/records/BATTER_S1_021/condition_observations.tsv",
                "condition_observations.tsv.gz rows or fields changed for BATTER_S1_021",
            ),
        )
        for relative, expected_error in cases:
            with self.subTest(table=relative):
                self._assert_changed_archive_row_is_rejected(relative, expected_error)

    def _assert_changed_archive_row_is_rejected(self, relative: str, expected_error: str) -> None:
        header, rows = _read_tsv_bytes(self.legacy_files[relative], relative)
        field = next(name for name in reversed(header) if name not in {"end_id", "source_id"})
        rows[0][field] = rows[0].get(field, "") + " changed"
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=header, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        modified_legacy = dict(self.legacy_files)
        modified_legacy[relative] = buffer.getvalue().encode("utf-8")

        with self.assertRaisesRegex(ValueError, expected_error):
            _check_lossless_tables(ROOT, modified_legacy, self.release_dir)

    def test_import_manifest_references_compact_files_and_checksums(self) -> None:
        refs = _canonical_data_file_refs(ROOT)
        studies = refs["studies"]
        self.assertEqual(len(studies), 13)
        self.assertEqual(
            sum("gene_associations" in study for study in studies),
            1,
        )
        self.assertEqual(
            sum("condition_observations" in study for study in studies),
            1,
        )
        for study in studies:
            for name in ("endpoints", "metadata", "metadata_tsv", "gene_associations", "condition_observations"):
                if name not in study:
                    continue
                path = ROOT / study[name]["path"]
                self.assertEqual(study[name]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(next(study for study in studies if "gene_associations" in study)["pmid"], "31594819")
        self.assertEqual(next(study for study in studies if "condition_observations" in study)["pmid"], "37402717")


if __name__ == "__main__":
    unittest.main()
