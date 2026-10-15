"""Measure verified local D1 inputs and lossless alternatives; never connects to D1."""
import argparse
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def open_local(path):
    if path.exists():
        raise ValueError(f'Use a fresh audit directory: {path}')
    database = sqlite3.connect(path)
    database.execute('PRAGMA journal_mode=OFF')
    database.execute('PRAGMA synchronous=OFF')
    return database


def size(database):
    database.commit()
    return database.execute('PRAGMA page_count').fetchone()[0] * database.execute('PRAGMA page_size').fetchone()[0]


def audit(output):
    output.mkdir(parents=True, exist_ok=True)
    database = open_local(output / 'hf-baseline.sqlite')
    bundle = ROOT / 'dist/d1-hf-metadata'
    manifest = json.loads((bundle / 'import-manifest.json').read_text(encoding='utf-8'))
    for index, file in enumerate(['000-schema.sql', *manifest['chunks']]):
        database.executescript((bundle / file).read_text(encoding='utf-8'))
        if index % 15 == 0:
            print('LOCAL_IMPORT', index, '/', len(manifest['chunks']), flush=True)
    assert database.execute('SELECT COUNT(*) FROM hf_genome_metadata').fetchone()[0] == 42923
    assert database.execute('SELECT COUNT(*) FROM hf_registered_files').fetchone()[0] == 457805
    report = {'method': 'Fresh SQLite copies of verified import inputs; allocated pages include primary keys',
              'production_bytes_before': 431210496, 'hf_baseline_bytes': size(database), 'tables': {}, 'metadata': {}}
    for table in ['hf_metadata_releases', 'hf_genome_metadata', 'hf_registered_files', 'hf_catalogue_pages']:
        copy = open_local(output / (table + '.sqlite'))
        copy.execute(database.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()[0])
        cursor = database.execute(f'SELECT * FROM {table}')
        statement = f'INSERT INTO {table} VALUES ({",".join("?" for _ in cursor.description)})'
        copy.executemany(statement, cursor)
        report['tables'][table] = {'allocated_bytes': size(copy), 'rows': copy.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]}
        copy.close()
        print('TABLE', table, report['tables'][table], flush=True)
    compact = open_local(output / 'metadata-compact.sqlite')
    compressed = open_local(output / 'metadata-gzip.sqlite')
    definition = database.execute("SELECT sql FROM sqlite_master WHERE name='hf_genome_metadata'").fetchone()[0]
    compact.execute(definition)
    compressed.execute(definition.replace('metadata_json TEXT NOT NULL CHECK (json_valid(metadata_json))', 'metadata_gzip BLOB NOT NULL'))
    original_bytes = compact_bytes = gzip_bytes = 0
    original_identity = hashlib.sha256()
    for count, row in enumerate(database.execute('SELECT * FROM hf_genome_metadata ORDER BY genome_id'), 1):
        raw = row[5].encode('utf-8')
        assert hashlib.sha256(raw).hexdigest() == row[6], row[1]
        normalized = json.dumps(json.loads(raw), ensure_ascii=False, separators=(',', ':'))
        assert json.loads(normalized) == json.loads(raw), row[1]
        encoded = gzip.compress(raw, compresslevel=6, mtime=0)
        assert gzip.decompress(encoded) == raw, row[1]
        compact.execute('INSERT INTO hf_genome_metadata VALUES (?,?,?,?,?,?,?)', (*row[:5], normalized, row[6]))
        compressed.execute('INSERT INTO hf_genome_metadata VALUES (?,?,?,?,?,?,?)', (*row[:5], encoded, row[6]))
        original_bytes += len(raw)
        compact_bytes += len(normalized.encode('utf-8'))
        gzip_bytes += len(encoded)
        original_identity.update(row[1].encode() + b'\0' + bytes.fromhex(row[6]))
        if count % 10000 == 0:
            print('LOSSLESS_VERIFIED', count, '/', 42923, flush=True)
    # Re-read every stored gzip blob rather than checking only the compression input.
    stored_identity = hashlib.sha256()
    for genome, blob, checksum in compressed.execute('SELECT genome_id,metadata_gzip,metadata_sha256 FROM hf_genome_metadata ORDER BY genome_id'):
        assert hashlib.sha256(gzip.decompress(blob)).hexdigest() == checksum, genome
        stored_identity.update(genome.encode() + b'\0' + bytes.fromhex(checksum))
    assert original_identity.digest() == stored_identity.digest()
    report['metadata'] = {'rows_verified': 42923, 'raw_json_bytes': original_bytes, 'compact_json_bytes': compact_bytes,
                          'gzip_bytes': gzip_bytes, 'compact_table_bytes': size(compact), 'gzip_table_bytes': size(compressed),
                          'gzip_roundtrip_identity': original_identity.hexdigest()}
    registry = report['tables']['hf_registered_files']['allocated_bytes']
    current_metadata = report['tables']['hf_genome_metadata']['allocated_bytes']
    report['estimated_production_bytes'] = {
        'without_unused_file_registry': report['production_bytes_before'] - registry,
        'without_registry_and_compact_json': report['production_bytes_before'] - registry - current_metadata + size(compact),
        'without_registry_and_lossless_gzip': report['production_bytes_before'] - registry - current_metadata + size(compressed),
    }
    for name, store in [('directory', ROOT / 'dist/d1-directory-merged-2026-10-14/directory.sqlite'),
                        ('experimental', ROOT / 'dist/v04-d1-checked.sqlite')]:
        local = sqlite3.connect(f'{store.as_uri()}?mode=ro', uri=True)
        report[name + '_bytes'] = size(local)
        local.close()
    (output / 'storage-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    compact.close()
    compressed.close()
    database.close()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    audit(parser.parse_args().output.resolve())
