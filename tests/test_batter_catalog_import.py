"""Checks for the local BATTER metadata projection and audit boundary."""

from __future__ import annotations

import csv
import importlib.util
import json
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("import_batter_catalog", ROOT / "scripts/import_batter_catalog.py")
assert SPEC and SPEC.loader
catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog)


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


class BatterCatalogImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data_dir = ROOT / "dist" / f"batter-import-test-{uuid.uuid4().hex}"
        self.data_dir.mkdir()
        self.addCleanup(self.clean_data_dir)
        self.manifest = [
            dict(batch_rank="1", otu_id="OTU-1", genome_id="2228664028", tes_prediction="10",
                 otu_augmentation_window="2", otu_augmentation_span="3", rfam_training_window="1",
                 rfam_training_span="1", prediction_gff3_path="genomes/2228664028/prediction.gff3",
                 prediction_gff3_sha256="a" * 64,
                 augmentation_gff3_path="genomes/2228664028/augmentation.gff3",
                 augmentation_gff3_sha256="b" * 64, augmentation_status="has_features"),
            dict(batch_rank="2", otu_id="OTU-2", genome_id="GCF_000007485.1", tes_prediction="5",
                 otu_augmentation_window="0", otu_augmentation_span="0", rfam_training_window="0",
                 rfam_training_span="0", prediction_gff3_path="genomes/GCF_000007485.1/prediction.gff3",
                 prediction_gff3_sha256="c" * 64,
                 augmentation_gff3_path="genomes/GCF_000007485.1/augmentation.gff3",
                 augmentation_gff3_sha256="d" * 64, augmentation_status="no_records_in_source"),
        ]
        taxonomy = []
        references = []
        for row in self.manifest:
            taxonomy.append(dict(otu_id=row["otu_id"], genome_id=row["genome_id"], genome_type="isolate",
                                 source_collection="NCBI-RefSeq", taxonomy="d__Bacteria;p__Proteobacteria",
                                 domain="Bacteria", phylum="Proteobacteria", **{"class": "Gammaproteobacteria"},
                                 order="", family="", genus="", species=""))
            references.append(dict(otu_id=row["otu_id"], representative_genome_id=row["genome_id"],
                                   cohort="test", fasta_path=f"genomes/{row['otu_id']}.fna.gz",
                                   compressed_bytes="100", sha256="e" * 64, contigs="1", bases="500"))
        write_tsv(self.data_dir / "taxonomy_by_genome.tsv", taxonomy)
        write_tsv(self.data_dir / "gem_references_manifest.tsv", references)
        self.audit = dict(genomes=2, otus_with_training_records=1,
                          genome_types={"isolate": 2},
                          feature_totals=dict(tes_prediction=15, otu_augmentation_window=2,
                                              otu_augmentation_span=3, rfam_training_window=1,
                                              rfam_training_span=1))
        self.save_inputs()

    def clean_data_dir(self) -> None:
        for filename in ("batch_manifest.tsv", "taxonomy_by_genome.tsv", "gem_references_manifest.tsv", "audit.json"):
            (self.data_dir / filename).unlink(missing_ok=True)
        self.data_dir.rmdir()

    def save_inputs(self) -> None:
        write_tsv(self.data_dir / "batch_manifest.tsv", self.manifest)
        (self.data_dir / "audit.json").write_text(json.dumps(self.audit), encoding="utf-8")

    def test_numeric_id_separate_paths_and_no_augmentation(self) -> None:
        rows, metrics = catalog.build_rows(self.data_dir)
        self.assertEqual([row["genome_id"] for row in rows], ["2228664028", "GCF_000007485.1"])
        self.assertNotEqual(rows[0]["prediction_gff3_path"], rows[0]["augmentation_gff3_path"])
        self.assertEqual(rows[1]["augmentation_status"], "no_records_in_source")
        self.assertEqual(metrics["no_augmentation_genomes"], 1)
        self.assertEqual(metrics["reference_matches"], 2)

    def test_stale_audit_cannot_replace_current_counts(self) -> None:
        self.audit["feature_totals"]["tes_prediction"] = 16
        self.save_inputs()
        with self.assertRaisesRegex(catalog.ImportError, "manifest does not match audit"):
            catalog.build_rows(self.data_dir)

    def test_no_records_status_rejects_nonzero_feature_counts(self) -> None:
        self.manifest[1]["rfam_training_span"] = "1"
        self.audit["feature_totals"]["rfam_training_span"] = 2
        self.save_inputs()
        with self.assertRaisesRegex(catalog.ImportError, "No-records status conflicts"):
            catalog.build_rows(self.data_dir)

    def test_gem_reference_must_match_the_catalogue_genome_id(self) -> None:
        reference_path = self.data_dir / "gem_references_manifest.tsv"
        references = catalog.read_tsv(reference_path, catalog.REQUIRED_REFERENCE)
        references[1]["representative_genome_id"] = "GCF_999999999.1"
        write_tsv(reference_path, references)
        with self.assertRaisesRegex(catalog.ImportError, "GEM representative genome mismatch"):
            catalog.build_rows(self.data_dir)


if __name__ == "__main__":
    unittest.main()
