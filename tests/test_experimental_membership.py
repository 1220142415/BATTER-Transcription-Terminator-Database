"""Experimental membership is based on published endpoints, not predictions."""
import json
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_collections_d1 import COLS, directory_row
from prepare_experimental_membership import prepare


class ExperimentalMembershipTests(unittest.TestCase):
    def test_projection_search_and_rollback_preserve_audit_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / 'source.sqlite'
            old, new = '1' * 24, '2' * 24
            with closing(sqlite3.connect(database)) as db, db:
                for name in ['0005_genome_directory.sql', '0009_collections.sql', '0010_taxonomy_records.sql']:
                    db.executescript((ROOT / 'database/migrations' / name).read_text(encoding='utf-8'))
                db.execute('INSERT INTO hf_directory_releases VALUES(?,?,?,?,?)', (old, 'a'*40, 'b'*40, '{}', 'ready'))
                db.execute('INSERT INTO bted_collections VALUES(?,?,?,?,?,?,?,?,?)',
                           ('experimental', old, 'Experimental', 'NCBI Taxonomy', 'Studies', 2, 0, 'ncbi', ''))
                for id, endpoints in [('published', 5), ('audit_only', 0)]:
                    row = directory_row(old, id, id, 'p__P', 'RefSeq', 'isolate', 'Available', endpoints, 10, 0, 100, 1)
                    db.execute('INSERT INTO hf_directory_genomes (' + ','.join('"'+k+'"' for k in COLS) + ') VALUES (' + ','.join('?' for _ in COLS) + ')', [row[k] for k in COLS])
                db.commit()
            result = prepare(database, new, root / 'change')
            self.assertEqual(result['excluded'], ['audit_only'])
            self.assertEqual(result['summary']['feature_totals'], dict(endpoints=5, predictions=10, training=0))
            with closing(sqlite3.connect(database)) as db, db:
                self.assertEqual(db.execute('SELECT version FROM bted_collections').fetchone()[0], old)
                db.executescript((root/'change/apply.sql').read_text())
                self.assertEqual(db.execute('SELECT genome_id FROM hf_directory_genomes WHERE version=?', (new,)).fetchall(), [('published',)])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM hf_directory_genomes WHERE version=?', (old,)).fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM hf_directory_search WHERE hf_directory_search MATCH ?', ('pub',)).fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT version,source_genome_count FROM bted_collections').fetchone(), (new, 1))
                db.executescript((root/'change/rollback.sql').read_text())
                self.assertEqual(db.execute('SELECT version,source_genome_count FROM bted_collections').fetchone(), (old, 2))
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
