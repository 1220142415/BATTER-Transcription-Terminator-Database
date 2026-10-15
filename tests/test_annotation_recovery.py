import gzip
import importlib.util
import hashlib
import json
import sys
import tempfile
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('annotation_recovery', Path(__file__).resolve().parents[1] / 'scripts/audit_annotation_recovery.py')
RECOVERY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECOVERY)
sys.modules['audit_annotation_recovery'] = RECOVERY
PACKAGE_SPEC = importlib.util.spec_from_file_location('prepare_annotation_recovery', Path(__file__).resolve().parents[1] / 'scripts/prepare_annotation_recovery.py')
PACKAGE = importlib.util.module_from_spec(PACKAGE_SPEC)
PACKAGE_SPEC.loader.exec_module(PACKAGE)


class AnnotationRecoveryTests(unittest.TestCase):
    def test_package_checks_verified_files_and_retains_partial_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'restored-partial').mkdir()
            raw = gzip.compress(b'##gff-version 3\na\tNCBI\tgene\t1\t4\t.\t+\t.\tID=G\n')
            (root / 'restored-partial/GCF_TEST.gff3.gz').write_bytes(raw)
            report = {'reference_revision': 'a' * 40, 'verified_sequences': True, 'genomes': [{
                'genome_id': 'GCF_TEST', 'batch': '007', 'result': 'verified_partial', 'reference_sha256': 'b' * 64,
                'output_bytes': len(raw), 'output_sha256': hashlib.sha256(raw).hexdigest(),
                'matched_reference_contigs': 1, 'total_reference_contigs': 2, 'features': 1,
                'gff_url': 'https://ftp.ncbi.nlm.nih.gov/example.gff.gz'}]}
            path = root / 'partial-verified-report.json'
            path.write_text(json.dumps(report), encoding='utf-8')
            manifest = PACKAGE.prepare(root, root / 'publish')
            entry = manifest['genomes']['GCF_TEST']
            self.assertEqual(entry['coverage'], 'partial')
            self.assertNotIn('path', entry['file'])
            self.assertEqual((root / 'publish' / PACKAGE.annotation_path('GCF_TEST', '007')).read_bytes(), gzip.decompress(raw))
            (root / 'restored-partial/GCF_TEST.gff3.gz').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'checksum_mismatch'):
                PACKAGE.prepare(root, root / 'publish')

    def test_published_cds_retains_coordinates_and_checks_both_strands(self):
        reference = {'display': b'AACGTT'}
        raw = gzip.compress(b'>source_1 # 2 # 4 # 1 # ID=1;partial=00\nACG\n>source_2 # 2 # 4 # -1 # ID=2;partial=00\nCGT\n')
        restored, count = RECOVERY.compatible_prodigal_ffn(raw, reference, {'source': 'display'})
        self.assertEqual(count, 2)
        self.assertIn(b'display\tProdigal\tCDS\t2\t4\t.\t-\t0\tID=source_2;partial=00', restored)
        with self.assertRaisesRegex(ValueError, 'cds_sequence_mismatch'):
            RECOVERY.compatible_prodigal_ffn(raw, {'display': b'AATGTT'}, {'source': 'display'})
        with self.assertRaisesRegex(ValueError, 'duplicate_cds'):
            RECOVERY.compatible_prodigal_ffn(gzip.compress(gzip.decompress(raw) * 2), reference, {'source': 'display'})
        with self.assertRaisesRegex(ValueError, 'cds_contig_not_verified'):
            RECOVERY.compatible_prodigal_ffn(raw, reference, {})
        proteins = gzip.compress(b'>source_1 # 2 # 4 # 1 # ID=1;partial=00\nT\n')
        restored, count = RECOVERY.compatible_prodigal_ffn(proteins, reference, {'source': 'display'}, protein=True)
        self.assertEqual(count, 1)
        self.assertIn(b'\tCDS\t2\t4\t', restored)
        with self.assertRaisesRegex(ValueError, 'cds_protein_length_mismatch'):
            RECOVERY.compatible_prodigal_ffn(gzip.compress(gzip.decompress(proteins).replace(b'\nT\n', b'\nTT\n')),
                                            reference, {'source': 'display'}, protein=True)

    def test_only_identical_contigs_reuse_coordinates(self):
        reference = {'display': b'ACGT'}
        mapping = RECOVERY.matching_contigs(reference, {'original': b'ACGT', 'extra': b'TTTT'})
        self.assertEqual(mapping, {'original': 'display'})
        raw = gzip.compress(b'##gff-version 3\noriginal\tNCBI\tgene\t1\t4\t.\t+\t.\tID=G\nextra\tNCBI\tgene\t1\t4\t.\t+\t.\tID=X\n')
        restored, features, omitted = RECOVERY.compatible_gff(raw, reference, mapping)
        self.assertIn(b'display\tNCBI\tgene\t1\t4', restored)
        self.assertNotIn(b'ID=X', restored)
        self.assertEqual((features, omitted), (1, 1))
        with self.assertRaisesRegex(ValueError, 'sequence_difference'):
            RECOVERY.matching_contigs(reference, {'original': b'ACGA'})
        with self.assertRaisesRegex(ValueError, 'ambiguous_contigs'):
            RECOVERY.matching_contigs(reference, {'a': b'ACGT', 'b': b'ACGT'})
        self.assertEqual(RECOVERY.matching_contigs({'display': b'ACGT', 'missing': b'TTTT'}, {'original': b'ACGT'}, partial=True), {'original': 'display'})
        with self.assertRaisesRegex(ValueError, 'no_identical_reference_contigs'):
            RECOVERY.matching_contigs(reference, {'original': b'TTTT'}, partial=True)
        with self.assertRaisesRegex(ValueError, 'feature_outside_reference'):
            RECOVERY.compatible_gff(gzip.compress(b'original\tNCBI\tgene\t1\t5\t.\t+\t.\tID=G\n'), reference, mapping)

    def test_declared_circular_features_preserve_published_coordinates(self):
        reference = {'original': b'ACGT'}
        region = b'original\tNCBI\tregion\t1\t4\t.\t+\t.\tID=R;Is_circular=true\n'
        feature = b'original\tNCBI\tgene\t3\t6\t.\t+\t.\tID=G\n'
        restored, count, _ = RECOVERY.compatible_gff(gzip.compress(region + feature), reference, {'original': 'original'})
        self.assertIn(feature, restored)
        self.assertEqual(count, 1)
        with self.assertRaisesRegex(ValueError, 'feature_outside_reference'):
            RECOVERY.compatible_gff(gzip.compress(region + feature.replace(b'\t3\t6\t', b'\t3\t9\t')), reference, {'original': 'original'})


if __name__ == '__main__':
    unittest.main()
