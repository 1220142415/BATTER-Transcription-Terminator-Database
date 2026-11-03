import sqlite3
import unittest
from pathlib import Path


class GemLabelTests(unittest.TestCase):
    def test_guarded_label_correction_and_rollback(self):
        change = Path(__file__).resolve().parents[1] / 'database/changes/2026-10-23-gem-r89'
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE bted_collections(collection,version,label,taxonomy_label)')
            rows = [('gem', '202610220000000000000003', 'GEM', 'GTDB R98 (GEM)'),
                    ('gtdb', 'other', 'GTDB', 'GTDB R207.0'),
                    ('gem', 'old', 'GEM', 'GTDB R98 (GEM)')]
            db.executemany('INSERT INTO bted_collections VALUES(?,?,?,?)', rows)
            db.executescript((change / 'apply.sql').read_text(encoding='utf-8'))
            after = db.execute('SELECT * FROM bted_collections').fetchall()
            self.assertEqual(after, [(*rows[0][:3], 'GTDB R89 (GEM)'), *rows[1:]])
            db.executescript((change / 'apply.sql').read_text(encoding='utf-8'))
            self.assertEqual(db.execute('SELECT * FROM bted_collections').fetchall(), after)
            db.executescript((change / 'rollback.sql').read_text(encoding='utf-8'))
            self.assertEqual(db.execute('SELECT * FROM bted_collections').fetchall(), rows)
