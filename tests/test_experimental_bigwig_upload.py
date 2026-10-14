import struct
import tempfile
import unittest
from pathlib import Path

from scripts.publish_experimental_bigwigs import identity_check, prepare_bigwig, sample_root


class ExperimentalBigWigUploadTests(unittest.TestCase):
    def bigwig(self, directory):
        path = Path(directory) / "sample.bw"
        header = struct.pack("<IHHQQQHHQQIQ", 0x888FFC26, 4, 0, 64, 120, 128,
                             0, 0, 0, 136, 0, 0)
        tree = struct.pack("<IIIIQQ", 0x78CA8C91, 1, 12, 8, 1, 0)
        leaf = struct.pack("<BBH", 1, 0, 1) + b"NC_000913_2\0" + struct.pack("<II", 0, 4639675)
        summary = struct.pack("<Qdddd", 2, 1, 8, 9, 65)
        path.write_bytes(header + tree + leaf + b"DATAxxxxINDXxxxx" + summary)
        return path

    def test_alias_changes_only_name_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.bigwig(directory)
            original = source.read_bytes()
            target = Path(directory) / "out.bw"
            result = prepare_bigwig(source, target, {"NC_000913.2": 4639675},
                                    {"NC_000913_2": "NC_000913.2"})
            self.assertEqual(source.read_bytes(), original)
            differences = [(a, b) for a, b in zip(original, target.read_bytes()) if a != b]
            self.assertEqual(differences, [(ord("_"), ord("."))])
            self.assertEqual(result["changed_header_bytes"], 1)
            self.assertEqual(result["signal_summary"]["sum_values"], 9)

    def test_wrong_reference_length_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Reference name/length mismatch"):
                prepare_bigwig(self.bigwig(directory), Path(directory) / "out.bw",
                               {"NC_000913_2": 4641652}, {})

    def test_implicit_chromosome_rename_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Reference name/length mismatch"):
                prepare_bigwig(self.bigwig(directory), Path(directory) / "out.bw",
                               {"NC_000913.2": 4639675}, {})

    def test_path_traversal_rejected(self):
        sample = dict(group="experimental-only", genome_id="GCF_000005845.1", pmid="29606352",
                      source_id="BATTER_S1_001", sample_id="../GSM2500131")
        with self.assertRaisesRegex(ValueError, "Invalid identifier"):
            sample_root(sample)

    def test_wrong_study_mapping_rejected(self):
        sample = dict(group="experimental-only", genome_id="GCF_000005845.1", pmid="29606352",
                      source_id="BATTER_S1_001", series_accession="GSE95211")
        source = dict(source_id="BATTER_S1_001", pmid="99999", assembly="GCF_000005845.1",
                      raw_data_accessions="GSE95211")
        meta = dict(group=sample["group"], genome_id=sample["genome_id"],
                    records={"experimental": {"sources": [source]}})
        with self.assertRaisesRegex(ValueError, "Study/source mapping mismatch"):
            identity_check(sample, meta)
        source["pmid"] = sample["pmid"]
        source["raw_data_accessions"] = "GSE12345"
        with self.assertRaisesRegex(ValueError, "Series does not match"):
            identity_check(sample, meta)


if __name__ == "__main__":
    unittest.main()
