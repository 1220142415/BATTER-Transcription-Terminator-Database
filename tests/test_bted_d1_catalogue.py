import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / "scripts" / "generate_bted_d1.py"


def write_jsonl(path: Path, rows):
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


class BtedD1CatalogueGeneratorTests(unittest.TestCase):
    def make_bundle(self, root: Path) -> None:
        manifest = {
            "release_version": "v0.2.0",
            "asset_origin": {
                "asset_origin_status": "verified",
                "base": "https://huggingface.co/datasets/example/resolve/pinned",
            },
            "materializer_version": "test-materializer",
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        write_jsonl(root / "release_versions.jsonl", [{
            "release_version": "v0.2.0",
            "release_date": "2026-08-22",
            "canonical_manifest_path": "release_manifest.json",
            "canonical_manifest_sha256": "a" * 64,
            "materializer_version": "test-materializer",
        }])
        write_jsonl(root / "publications.jsonl", [{
            "pmid": "12345678",
            "doi": "10.1000/example",
            "pmc": None,
            "published_year": 2020,
            "journal": "Example Journal",
            "paper_title": "Example BTED paper",
            "citation_json": {"pmid": "12345678"},
        }])
        write_jsonl(root / "assemblies.jsonl", [{
            "assembly_accession": "GCF_TEST.1",
            "assembly_name": "GCF_TEST.1",
            "organism_name": "Example bacterium",
            "strain": "test",
            "taxon_id": "1",
            "reference_url": "https://example.org/reference",
        }])
        write_jsonl(root / "contigs.jsonl", [{
            "assembly_accession": "GCF_TEST.1",
            "contig_accession": "CP_TEST.1",
            "contig_name": "CP_TEST.1",
            "length_bp": 100,
            "sequence_sha256": "b" * 64,
            "provenance_json": {"test": True},
        }])
        write_jsonl(root / "sources.jsonl", [{
            "source_id": "BATTER_S1_TEST",
            "assembly_id_ref": "GCF_TEST.1",
            "publication_id_ref": "12345678",
            "species": "Example bacterium",
            "phylum": "Example",
            "assay_family": "termseq",
            "evidence_class": "author_called_endpoint",
            "release_status": "published_standardized",
            "record_count": 1,
            "used_for_batter_augmentation": True,
            "has_jbrowse": True,
            "accessibility_status": "public",
            "coordinate_status": "verified",
            "processing_status": "published",
            "redistribution_status": "verified_redistributable",
            "manifest_path": "records/BATTER_S1_TEST/manifest.json",
            "manifest_sha256": "c" * 64,
            "record_root": "records/BATTER_S1_TEST",
            "source_note": "test",
            "decision_note": "test",
            "known_limitations": "none",
            "metadata_json": {"title": "Author's 3′ ends", "article_license": "CC BY 4.0", "future_field": "新增字段", "empty": ""},
        }])
        write_jsonl(root / "source_accessions.jsonl", [{
            "source_id_ref": "BATTER_S1_TEST",
            "accession_namespace": "SRA",
            "accession": "SRPTEST",
            "raw_value": "SRPTEST",
            "accession_type": "study",
            "ordinal": 1,
            "external_url": "https://example.org/SRPTEST",
        }])
        write_jsonl(root / "endpoints.jsonl", [{
            "end_id": "BTED_BATTER_S1_TEST_CP_TEST-1_plus_10_r000001",
            "release_version": "v0.2.0",
            "source_id": "BATTER_S1_TEST",
            "sample_id": "SAMPLE_TEST",
            "assay": "termseq",
            "evidence_class": "author_called_endpoint",
            "author_endpoint_id": "author-1",
            "published_reference_accession": "CP_TEST.1",
            "reference_assembly": "GCF_TEST.1",
            "reference_name": "CP_TEST.1",
            "replicon_label": "chromosome",
            "biological_coordinate_1based": 10,
            "bed_start_0based": 9,
            "bed_end_0based": 10,
            "strand": "+",
            "signal_or_score": "1",
            "author_category": "test",
            "associated_gene_or_locus": "gene-test",
            "pmid": "12345678",
            "doi": "10.1000/example",
            "source_table_or_file": "test.tsv",
            "coordinate_interpretation": "1-based biological endpoint",
            "original_row_reference": "row-1",
            "qc_status": "pass",
            "note": "test",
        }])
        asset_base = {
            "release_version": "v0.2.0",
            "origin_url": "https://huggingface.co/datasets/example/resolve/pinned",
            "origin_host": "huggingface.co",
            "supports_range": True,
            "redistribution_status": "verified_redistributable",
            "is_public": True,
        }
        assets = []
        for key, kind, logical, assembly, source, mime, size in [
            ("v0.2.0--assembly-GCF_TEST.1--fasta", "fasta", "assemblies/GCF_TEST.1/reference/reference.fna", "GCF_TEST.1", None, "text/plain", 100),
            ("v0.2.0--assembly-GCF_TEST.1--fai", "fai", "assemblies/GCF_TEST.1/reference/reference.fna.fai", "GCF_TEST.1", None, "text/plain", 20),
            ("v0.2.0--source-BATTER_S1_TEST--endpoints-bed", "bed", "records/BATTER_S1_TEST/endpoints.bed", None, "BATTER_S1_TEST", "text/plain", 20),
        ]:
            row = dict(asset_base)
            row.update({
                "asset_id": key,
                "asset_kind": kind,
                "logical_path": logical,
                "assembly_id_ref": assembly,
                "source_id_ref": source,
                "mime_type": mime,
                "byte_size": size,
                "sha256": "d" * 64,
            })
            assets.append(row)
        write_jsonl(root / "assets.jsonl", assets)

    def test_generates_catalogue_batches_and_preview_release(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp) / "bundle"
            output = Path(temp) / "output"
            bundle.mkdir()
            self.make_bundle(bundle)
            result = subprocess.run(
                [sys.executable, str(GENERATOR), "--bundle-dir", str(bundle), "--output-dir", str(output)],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            summary = json.loads((output / "IMPORT_SUMMARY.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["preview_status"], "preview")
            self.assertEqual(summary["counts"], {
                "publications": 1,
                "assemblies": 1,
                "contigs": 1,
                "sources": 1,
                "source_accessions": 1,
                "tracks": 1,
                "assets": 3,
                "public_assets": 3,
                "endpoints": 1,
            })
            self.assertIn("INSERT INTO release_versions", (output / "00_release.sql").read_text())
            self.assertIn("'preview'", (output / "00_release.sql").read_text())
            self.assertTrue((output / "08_endpoints_0000.sql").exists())
            endpoint_sql = (output / "08_endpoints_0000.sql").read_text(encoding="utf-8")
            self.assertIn("gff_start_1based, gff_end_1based", endpoint_sql)
            self.assertNotIn("bed_start_0based", endpoint_sql)
            schema = (output / "schema.sql").read_text(encoding="utf-8")
            self.assertIn("CREATE TABLE IF NOT EXISTS endpoints", schema)
            self.assertNotIn("CREATE TABLE IF NOT EXISTS genes", schema)
            self.assertNotIn("CREATE TABLE IF NOT EXISTS source_annotations", schema)
            self.assertIn('"preview_status": "preview"', result.stdout)
            with closing(sqlite3.connect(":memory:")) as database:
                database.executescript(schema)
                for path in sorted(output.glob("[0-9]*.sql")):
                    database.executescript(path.read_text(encoding="utf-8"))
                metadata = json.loads(database.execute("SELECT metadata_json FROM sources").fetchone()[0])
                self.assertEqual(metadata, {"title": "Author's 3′ ends", "article_license": "CC BY 4.0", "future_field": "新增字段", "empty": ""})
                self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_static_source_tracks_keep_license_gate_without_bed_assets(self):
        for redistribution_status, expected_public in (
            ("verified_redistributable", 1),
            ("external_link_only", 0),
        ):
            with self.subTest(redistribution_status=redistribution_status), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                bundle = root / "bundle"
                output = root / "output"
                bundle.mkdir()
                self.make_bundle(bundle)

                sources_path = bundle / "sources.jsonl"
                sources = [json.loads(line) for line in sources_path.read_text(encoding="utf-8").splitlines()]
                sources[0]["redistribution_status"] = redistribution_status
                write_jsonl(sources_path, sources)

                assets_path = bundle / "assets.jsonl"
                assets = [json.loads(line) for line in assets_path.read_text(encoding="utf-8").splitlines()]
                write_jsonl(assets_path, [asset for asset in assets if asset["asset_kind"] != "bed"])

                subprocess.run(
                    [sys.executable, str(GENERATOR), "--bundle-dir", str(bundle), "--output-dir", str(output)],
                    cwd=REPO_ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                track_sql = (output / "07_tracks.sql").read_text(encoding="utf-8")
                self.assertRegex(track_sql, rf", NULL, {expected_public}, 1,")


if __name__ == "__main__":
    unittest.main()
