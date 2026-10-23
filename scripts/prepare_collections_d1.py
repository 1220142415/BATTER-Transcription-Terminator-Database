"""Prepare independent collection projections from a pinned HF catalogue and a D1 export.

No scientific files or existing D1 rows are modified. Publish only after local checks.
"""
import argparse
import gzip
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from build_genome_directory import compact, normal, sort_key

ROOT = Path(__file__).resolve().parents[1]
RANKS = ['phylum', 'class', 'order', 'family', 'genus', 'species']
COLS = ['version', 'genome_id', 'accession_key', 'organism_key', 'organism', 'source', 'genome_type', 'annotation',
        'endpoints', 'predictions', 'training', 'size', 'contigs', *RANKS, 'search_text', 'recovered_matched', 'recovered_total', 'recovered_coverage']


def literal(value):
    return 'NULL' if value is None else "'" + str(value).replace("'", "''") + "'"


def insert(table, columns, values):
    return f'INSERT OR IGNORE INTO {table} (' + ','.join('"' + c + '"' for c in columns) + ') VALUES (' + ','.join(map(literal, values)) + ');\n'


def taxonomy_fields(taxonomy):
    values = {part[0]: part[3:] for part in taxonomy.split(';') if len(part) > 3}
    return {rank: values.get(rank[0], '') for rank in RANKS}


def directory_row(version, id, organism, taxonomy, source, genome_type, annotation, endpoints, predictions, training, size, contigs, recovered=None):
    row = dict(version=version, genome_id=id, accession_key=sort_key(id), organism_key=sort_key(organism), organism=organism,
               source=source, genome_type=genome_type or 'unknown', annotation=annotation, endpoints=endpoints,
               predictions=predictions, training=training, size=size or None, contigs=contigs, **taxonomy_fields(taxonomy))
    row['search_text'] = ' '.join(dict.fromkeys(re.split(r'[^\w.-]+', normal(' '.join([id, organism, taxonomy, source])))))
    row.update({key: (recovered or {}).get(key) for key in COLS[-3:]})
    return row


def prepare(inputs, export, output):
    output.mkdir(parents=True, exist_ok=True)
    current = json.loads((inputs / 'current.json').read_bytes())
    snapshot = json.loads((inputs / 'snapshot.json').read_bytes())
    catalogue = json.loads(gzip.decompress((inputs / 'genomes.json.gz').read_bytes()))
    assert re.fullmatch('[0-9a-f]{40}', current['revision'])
    assert snapshot['taxonomy_version'] == 'r207.0'
    assert len(catalogue['genomes']) == current['genome_count'] == snapshot['genome_count']
    version = Path(current['path']).stem.removeprefix('snapshot-')
    assert re.fullmatch('[0-9a-f]{24}', version)
    versions = {'gtdb': version, 'experimental': '202610220000000000000002', 'gem': '202610220000000000000003'}
    local = output / 'verified.sqlite'
    if local.exists():
        raise ValueError('Use a fresh output folder')
    db = sqlite3.connect(local)
    db.row_factory = sqlite3.Row
    db.executescript('BEGIN;\n' + export.read_text(encoding='utf-8') + '\nCOMMIT;')
    db.executescript((ROOT / 'database/migrations/0005_genome_directory.sql').read_text(encoding='utf-8'))
    old_pin = json.loads((ROOT / 'data/registry/genome-directory.json').read_bytes())
    release = db.execute('SELECT * FROM hf_directory_releases WHERE version=?', (old_pin['version'],)).fetchone()
    assert release and release['status'] == 'ready'
    storage = json.loads(release['summary_json']).get('storage_version', old_pin['version'])
    old = {r['genome_id']: dict(r) for r in db.execute('SELECT * FROM hf_directory_genomes WHERE version=?', (storage,))}
    assert len(old) == 42923
    groups = {key: [] for key in versions}
    assets = []
    for values in catalogue['genomes']:
        r = dict(zip(catalogue['columns'], values, strict=True))
        assert re.fullmatch(r'GC[AF]_\d+\.\d+', r['genome_id']) and re.fullmatch(r'\d{4}', r['group'])
        assert re.fullmatch('[0-9a-f]{40}', r['revision']) and r['annotation_status'] in ('matched', 'unavailable')
        assert r['taxonomy'].startswith('d__Bacteria;')
        groups['gtdb'].append(directory_row(version, r['genome_id'], r['organism'], r['taxonomy'], 'GTDB R207.0', r['genome_type'],
                            'Available' if r['annotation_status'] == 'matched' else 'Missing', 0, r['tes_prediction'], 0, r['reference_bases'], r['reference_contigs']))
        assets.append([version, r['genome_id'], r['group'], r['revision']])
    for r in db.execute('SELECT * FROM hf_runtime_genomes'):
        r = dict(r)
        original = old[r['genome_id']]
        source = {'NCBI-RefSeq': 'NCBI RefSeq', 'NCBI-MAG': 'NCBI GenBank', 'NCBI-SAG': 'NCBI GenBank'}.get(r['source_collection'], r['source_collection'])
        row = directory_row(versions['gem'], r['genome_id'], r['organism'], r['taxonomy'], source, r['genome_type'], original['annotation'],
                            0, r['tes_prediction'], r['otu_augmentation_span'] + r['rfam_training_span'], r['reference_bases'], r['reference_contigs'], original)
        if r['otu_id'] and normal(r['otu_id']) not in row['search_text']:
            row['search_text'] += ' ' + normal(r['otu_id'])
        groups['gem'].append(row)
    experiments = json.loads((ROOT / 'dist/worker-site/assets/genome-browsers.json').read_bytes())['experimental']
    for id in experiments:
        row = {k: old[id].get(k) for k in COLS}
        if not row['endpoints']:
            continue
        row.update(version=versions['experimental'], training=0)
        groups['experimental'].append(row)
    assert len(groups['gem']) == 42904 and len(groups['experimental']) == 20
    labels = {'gtdb': 'GTDB predictions', 'experimental': 'Experimental 3′ ends', 'gem': 'GEM catalogue · Legacy'}
    taxonomy = {'gtdb': 'GTDB R207.0 (2022)', 'experimental': 'GEM / GTDB (original); exact assembly matches only', 'gem': 'GEM / GTDB (original; release not established)'}
    descriptions = {'gtdb': 'BATTER-TPE predictions on GTDB R207.0 assemblies. Fixed, partially published catalogue.',
                    'experimental': 'Study-reported transcript 3′ ends, original publications and condition-specific coverage tracks.',
                    'gem': 'Archived computational catalogue, including GEM, IMG, NCBI and published-study sources. Predictions are retained without further updates.'}
    statements = [(ROOT / 'database/migrations/0009_collections.sql').read_text(encoding='utf-8') + '\n']
    registry = {}
    for key, rows in groups.items():
        assert len({r['genome_id'] for r in rows}) == len(rows)
        counts = {field: dict(Counter(r[field] for r in rows)) for field in ['source', 'genome_type', 'annotation', 'phylum']}
        counts['dataset'] = {name: sum(r[field] > 0 for r in rows) for name, field in [('experimental', 'endpoints'), ('prediction', 'predictions'), ('augmentation', 'training')]}
        summary = dict(total=len(rows), sources=sorted(counts['source']), phyla=sorted(p for p in counts['phylum'] if p), counts=counts,
                       available=counts['annotation'].get('Available', 0), feature_totals={field: sum(r[field] for r in rows) for field in ['endpoints', 'predictions', 'training']})
        reference_revision = current['revision'] if key == 'gtdb' else old_pin['reference_revision']
        annotation_revision = 'ncbi-exact-assembly' if key == 'gtdb' else old_pin['annotation_revision']
        statements.append(insert('hf_directory_releases', ['version', 'reference_revision', 'annotation_revision', 'summary_json', 'status'],
                      [versions[key], reference_revision, annotation_revision, compact(summary), 'loading']))
        registry[key] = dict(version=versions[key], label=labels[key], taxonomy_label=taxonomy[key], reference_revision=reference_revision,
                            total=len(rows), source_genome_count=snapshot['source_genome_count'] if key == 'gtdb' else len(rows),
                            partial=bool(snapshot['partial']) if key == 'gtdb' else False, description=descriptions[key])
        for r in rows:
            statements.append(insert('hf_directory_genomes', COLS, [r[k] for k in COLS]))
    for values in assets:
        statements.append(insert('gtdb_genome_assets', ['version', 'genome_id', 'asset_group', 'asset_revision'], values))
    # Rebuild the shared external-content index so existing and new records remain searchable.
    statements.append("INSERT INTO hf_directory_search(hf_directory_search) VALUES('rebuild');\n")
    for key, r in registry.items():
        statements.append(f"UPDATE hf_directory_releases SET status='ready' WHERE version='{r['version']}' AND (SELECT COUNT(*) FROM hf_directory_genomes WHERE version='{r['version']}')={r['total']};\n")
        statements.append(insert('bted_collections', ['collection', 'version', 'label', 'taxonomy_label', 'description', 'source_genome_count', 'partial'],
                      [key, r['version'], r['label'], r['taxonomy_label'], r['description'], r['source_genome_count'], int(r['partial'])]))
    sql = ''.join(statements)
    db.executescript('BEGIN;\n' + sql + '\nCOMMIT;')
    db.commit()
    for key, r in registry.items():
        assert db.execute('SELECT COUNT(*) FROM hf_directory_genomes WHERE version=?', (r['version'],)).fetchone()[0] == r['total']
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert db.execute("SELECT COUNT(*) FROM hf_directory_search WHERE hf_directory_search MATCH '\"fus\"'").fetchone()[0] > 0
    plan = [r[3] for r in db.execute('EXPLAIN QUERY PLAN SELECT genome_id FROM hf_directory_genomes WHERE version=? ORDER BY predictions DESC,accession_key LIMIT 25', (version,))]
    assert any('directory_predictions' in item for item in plan)
    db.close()
    (output / 'import.sql').write_text(sql, encoding='utf-8')
    (output / 'collections.json').write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report = dict(collections=registry, local_bytes=local.stat().st_size, sql_bytes=(output/'import.sql').stat().st_size, first_page_plan=plan,
                  previous_directory_version=old_pin['version'], snapshot_path=current['path'], snapshot_revision=current['revision'])
    (output / 'verified.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--export', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.inputs, args.export, args.output)
