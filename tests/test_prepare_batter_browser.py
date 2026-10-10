"""Release metadata checks use synthetic manifests and tables, never sequence files."""
import hashlib
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_batter_browser import build, build_release, carry_overlays


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        temp_root = (Path(__file__).resolve().parents[1] / "tmp").resolve()
        self.cache = temp_root / f"catalogue-test-{uuid.uuid4().hex}"
        self.cache.mkdir(parents=True)
        def cleanup():
            assert self.cache.resolve().is_relative_to(temp_root)
            shutil.rmtree(self.cache)
        self.addCleanup(cleanup)
        self.revision = "a" * 40
        self.root = self.cache / self.revision
        self.base = "genomes/batter-042/TEST_1/"
        self.table = "catalogues/provenance/batter/batches/042/genomes.tsv"
        self.release = {"schema": "bted-genome-first-v5-v1", "hf_repo": "liurulong/terminator",
                        "counts": {"genomes": 1, "batter_genomes": 1}, "files": [],
                        "original_revision": "b" * 40, "original_release_manifest_sha256": "c" * 64}
        self.write(self.table, "genome_id\totu_id\tgenome_type\tsource_collection\ttaxonomy\ttes_prediction\totu_augmentation_span\totu_augmentation_window\trfam_training_span\trfam_training_window\tannotation_status\n"
                   "TEST_1\tOTU-1\tMAG\tIMG\td__Bacteria;s__\t12\t1\t1\t0\t0\tmatched\n")
        self.write("catalogues/genomes.json", json.dumps([{"genome_id": "TEST_1", "group": "batter-042", "has_prediction": True, "metadata_path": self.base + "metadata.json"}]))
        proof = {"status": "complete", "hf_sha256_verified": True, "genome_count": 1,
                 "hf_revision": "b" * 40, "release_manifest_sha256": "c" * 64, "completed_groups": ["batter-042"]}
        entry = self.write("catalogues/provenance/original-release.complete.json", json.dumps(proof))
        self.release["original_proof_sha256"] = entry["sha256"]
        for name in ["metadata.json", "reference/reference.fa.gz", "reference/reference.fa.gz.fai", "reference/reference.fa.gz.gzi",
                     "predictions/prediction.gff3.gz", "predictions/prediction.gff3.gz.tbi", "training/augmentation.gff3.gz", "training/augmentation.gff3.gz.tbi",
                     "annotations/batter/genes.gff3.gz", "annotations/batter/genes.gff3.gz.tbi"]:
            self.release["files"].append({"path": self.base + name, "byte_size": 1, "sha256": "d" * 64})
        self.save_release()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode("utf-8")
        path.write_bytes(data)
        entry = {"path": name, "byte_size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        self.release["files"] = [f for f in self.release["files"] if f["path"] != name] + [entry]
        return entry

    def save_release(self):
        (self.root / "release.json").write_text(json.dumps(self.release), encoding="utf-8")

    def test_complete_metadata_requires_no_sequence_download(self):
        result, _ = build_release(self.cache, self.revision)
        self.assertFalse(result["partial"])
        self.assertEqual(result["layout"], "genome-first")
        self.assertEqual(result["genomes"][0][10], 12)
        self.assertFalse((self.root / "genomes").exists())

    def test_corrupt_table_is_rejected(self):
        (self.root / self.table).write_text("corrupt", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            build_release(self.cache, self.revision)

    def test_missing_batch_is_not_a_complete_catalogue(self):
        self.release["files"] = [f for f in self.release["files"] if f["path"] != self.table]
        self.save_release()
        with self.assertRaisesRegex(ValueError, "No uploaded genomes"):
            build_release(self.cache, self.revision)

    def test_missing_prediction_index_is_rejected(self):
        self.release["files"] = [f for f in self.release["files"] if not f["path"].endswith("prediction.gff3.gz.tbi")]
        self.save_release()
        with self.assertRaisesRegex(ValueError, "Missing published genome file"):
            build_release(self.cache, self.revision)

    def test_wrong_path_and_false_completion_are_rejected(self):
        self.write("catalogues/genomes.json", json.dumps([{"genome_id": "TEST_1", "group": "batter-000", "has_prediction": True, "metadata_path": self.base + "metadata.json"}]))
        self.save_release()
        with self.assertRaisesRegex(ValueError, "Genome path mismatch"):
            build_release(self.cache, self.revision)
        self.release["original_revision"] = "e" * 40
        self.save_release()
        with self.assertRaisesRegex(ValueError, "completion proof mismatch"):
            build_release(self.cache, self.revision)

    def test_negative_prediction_and_duplicate_genomes_are_rejected(self):
        path = self.root / self.table
        original = path.read_text(encoding="utf-8")
        path.write_text(original.replace("\t12\t", "\t-1\t"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Negative feature count"):
            build([("042", path)], self.revision)
        path.write_text(original + original.splitlines()[1] + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate genome"):
            build([("042", path)], self.revision)

    def test_prior_overlay_requires_unchanged_reference_hash(self):
        catalogue, release = build_release(self.cache, self.revision)
        path = self.cache / "overlays.json"
        for digest, expected in [("d" * 64, 1), ("e" * 64, 0)]:
            path.write_text(json.dumps({"revision": "b" * 40, "genomes": {"TEST_1": {"batter_reference_sha256": digest}}}), encoding="utf-8")
            carry_overlays(catalogue, release, path)
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["revision"], self.revision)
            self.assertEqual(len(result["genomes"]), expected)


if __name__ == "__main__":
    unittest.main()
