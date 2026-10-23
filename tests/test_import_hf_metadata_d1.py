import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import import_hf_metadata_d1 as importer


class MetadataImportTests(unittest.TestCase):
    def test_snapshot_preserves_json_and_counts_and_rejects_changed_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            revision = importer.REVISION
            published = []
            files = []
            cache = root / 'cache'
            counts = dict(tes_prediction=2, otu_augmentation_span=1, otu_augmentation_window=1,
                          rfam_training_span=0, rfam_training_window=0)
            row = ['G1', '000', 'OTU-1', "O'Brien", 'MAG', 1, 1, 0, 0, 'matched', 2]
            raw_by_id = {}
            for genome_id in ('G1', 'G2'):
                entry = dict(genome_id=genome_id, group='batter-000' if genome_id == 'G1' else 'experimental',
                             has_prediction=genome_id == 'G1', has_experimental=genome_id == 'G2')
                entry['metadata_path'] = f"genomes/{entry['group']}/{genome_id}/metadata.json"
                metadata = dict(batch='000', otu_id='OTU-1', feature_counts=counts)
                wrapper = {**entry, 'records': {'batter': metadata}, 'notes': "O'Brien\noriginal metadata"}
                raw = json.dumps(wrapper, ensure_ascii=False, indent=2).encode()
                raw_by_id[genome_id] = raw
                path = cache / entry['metadata_path']
                path.parent.mkdir(parents=True)
                path.write_bytes(raw)
                files.append(dict(path=entry['metadata_path'], byte_size=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
                published.append(entry)
            release = dict(release_version='v0.5.0', counts=dict(genomes=2, batter_genomes=1), files=files)
            snapshot = root / 'dist/hf-catalogue' / revision
            (snapshot / 'catalogues').mkdir(parents=True)
            (snapshot / 'release.json').write_text(json.dumps(release), encoding='utf-8')
            (snapshot / 'catalogues/genomes.json').write_text(json.dumps(published), encoding='utf-8')
            schema = root / 'database/migrations/0004_hf_metadata.sql'
            schema.parent.mkdir(parents=True)
            schema.write_bytes((ROOT / schema.relative_to(root)).read_bytes())
            catalogue = dict(revision=revision, layout='genome-first', partial=False, genomes=[row], reference_sizes={'G1': [100, 1]})
            output = root / 'sql'
            with patch.object(importer, 'ROOT', root):
                importer.build_sql(cache, release, catalogue, output)
                connection = sqlite3.connect(':memory:')
                for path in sorted(output.glob('*.sql')):
                    connection.executescript(path.read_text(encoding='utf-8'))
                records = connection.execute('SELECT genome_id, metadata_json, metadata_sha256 FROM hf_genome_metadata').fetchall()
                self.assertEqual(len(records), 2)
                for genome_id, raw, digest in records:
                    self.assertEqual(raw.encode(), raw_by_id[genome_id])
                    self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(), digest)
                stored_rows = json.loads(connection.execute('SELECT rows_json FROM hf_catalogue_pages').fetchone()[0])
                self.assertEqual(stored_rows, [row])
                self.assertEqual(connection.execute('SELECT status FROM hf_metadata_releases').fetchone()[0], 'loading')
                header = json.loads(connection.execute('SELECT catalogue_header_json FROM hf_metadata_releases').fetchone()[0])
                self.assertEqual(header['reference_sizes'], catalogue['reference_sizes'])
                self.assertEqual(connection.execute('SELECT count(*) FROM hf_registered_files').fetchone()[0], 2)
                (cache / published[0]['metadata_path']).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'invalid metadata'):
                    importer.build_sql(cache, release, catalogue, root / 'bad-sql')


if __name__ == '__main__':
    unittest.main()
