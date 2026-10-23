"""Prepare an additive experimental directory release containing published endpoints only.

Reads a local D1 export. Emits reviewed SQL and rollback; never contacts production.
"""
import argparse
import json
import re
import sqlite3
from contextlib import closing
from collections import Counter
from pathlib import Path

from prepare_collections_d1 import compact, literal


def prepare(database, version, output):
    if not re.fullmatch(r'[0-9a-f]{24}', version):
        raise ValueError('Use a new 24-character directory version')
    output.mkdir(parents=True, exist_ok=False)
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        current = dict(db.execute("SELECT * FROM bted_collections WHERE collection='experimental'").fetchone())
        if db.execute('SELECT 1 FROM hf_directory_releases WHERE version=?', (version,)).fetchone():
            raise ValueError('Directory version already exists')
        old = current['version']
        release = dict(db.execute('SELECT * FROM hf_directory_releases WHERE version=?', (old,)).fetchone())
        rows = [dict(r) for r in db.execute('SELECT * FROM hf_directory_genomes WHERE version=?', (old,))]
        included = [r for r in rows if r['endpoints'] > 0]
        excluded = [r['genome_id'] for r in rows if r['endpoints'] == 0]
        if not included or len(included) + len(excluded) != len(rows):
            raise ValueError('Invalid experimental endpoint counts')
        summary = json.loads(release['summary_json'])
        # Audit-only reference URLs keep their last explicit classification binding.
        summary.setdefault('reference_registry_version', old)
        counts = {k: dict(Counter(r[k] for r in included)) for k in ['source', 'genome_type', 'annotation', 'phylum']}
        counts['dataset'] = {name: sum(r[field] > 0 for r in included) for name, field in
                             [('experimental', 'endpoints'), ('prediction', 'predictions'), ('augmentation', 'training')]}
        summary.update(total=len(included), counts=counts, sources=sorted(counts['source']),
                       phyla=sorted(p for p in counts['phylum'] if p), available=counts['annotation'].get('Available', 0),
                       feature_totals={k: sum(r[k] for r in included) for k in ['endpoints', 'predictions', 'training']})
        columns = [r['name'] for r in db.execute('PRAGMA table_info(hf_directory_genomes)') if r['name'] != 'id']
        taxcols = [r['name'] for r in db.execute('PRAGMA table_info(bted_taxonomy_records)')]
    sql = [f"INSERT INTO hf_directory_releases VALUES ({literal(version)},{literal(release['reference_revision'])},{literal(release['annotation_revision'])},{literal(compact(summary))},'loading');"]
    for table, fields, condition in [
        ('hf_directory_genomes', columns, 'endpoints > 0'),
        ('bted_taxonomy_records', taxcols, f"genome_id IN (SELECT genome_id FROM hf_directory_genomes WHERE version={literal(version)})"),
    ]:
        names = ','.join('"' + f + '"' for f in fields)
        values = ','.join(literal(version) if f == 'version' else '"' + f + '"' for f in fields)
        sql.append(f'INSERT INTO {table} ({names}) SELECT {values} FROM {table} WHERE version={literal(old)} AND {condition};')
    sql += [
        f"INSERT INTO hf_directory_search(rowid,search_text) SELECT id,search_text FROM hf_directory_genomes WHERE version={literal(version)};",
        f"UPDATE hf_directory_releases SET status='ready' WHERE version={literal(version)} AND (SELECT COUNT(*) FROM hf_directory_genomes WHERE version={literal(version)})={len(included)};",
        f"UPDATE bted_collections SET version={literal(version)},source_genome_count={len(included)} WHERE collection='experimental' AND version={literal(old)} AND EXISTS (SELECT 1 FROM hf_directory_releases WHERE version={literal(version)} AND status='ready');",
    ]
    (output / 'apply.sql').write_text('\n'.join(sql) + '\n', encoding='utf-8')
    (output / 'rollback.sql').write_text(f"UPDATE bted_collections SET version={literal(old)},source_genome_count={current['source_genome_count']} WHERE collection='experimental' AND version={literal(version)};\n", encoding='utf-8')
    result = dict(previous_version=old, version=version, excluded=excluded, summary=summary)
    (output / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.database, args.version, args.output), ensure_ascii=False, indent=2))
