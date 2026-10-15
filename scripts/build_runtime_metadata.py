"""Build current scalar D1 records; omit historical coordinate correction logs."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ['reference.fa.gz', 'reference.fa.gz.fai', 'reference.fa.gz.gzi', 'augmentation.gff3.gz',
         'augmentation.gff3.gz.tbi', 'prediction.gff3.gz', 'prediction.gff3.gz.tbi', 'genes.gff3.gz', 'genes.gff3.gz.tbi']
COUNTS = ['otu_augmentation_span', 'otu_augmentation_window', 'rfam_training_span', 'rfam_training_window', 'tes_prediction']
ANNOTATION = ['accession', 'features', 'reason', 'source_gff_sha256', 'circular_overhang_features']


def metadata_from_fields(row, files):
    annotation = {'status': row['annotation_status']}
    annotation.update({key: row['annotation_' + key] for key in ANNOTATION if row['annotation_' + key] is not None})
    validation = {key: row['validation_' + key] for key in ['augmentation', 'augmentation_features', 'prediction', 'prediction_features']}
    return {**{key: row[key] for key in ['genome_id', 'batch', 'batch_rank', 'otu_id', 'genome_type', 'source_collection', 'taxonomy', 'augmentation_status']},
            'annotation': annotation, 'feature_counts': {key: row[key] for key in COUNTS},
            'reference': {**{key: row['reference_' + key] for key in ['bases', 'contigs', 'source', 'source_sha256']}, 'source_path': f"genomes/{row['otu_id']}.fna.gz"},
            'files': {FILES[entry['file_kind']]: {'bytes': entry['byte_size'], 'sha256': entry['sha256']} for entry in files}, 'validation': validation}


def build(source, output):
    output.mkdir(parents=True, exist_ok=True)
    local = output / 'runtime.sqlite'
    if local.exists():
        raise ValueError('Use a fresh output directory')
    origin = sqlite3.connect(f'{source.resolve().as_uri()}?mode=ro', uri=True)
    origin.row_factory = sqlite3.Row
    release = origin.execute('SELECT revision FROM hf_metadata_releases').fetchall()
    assert len(release) == 1
    revision = release[0]['revision']
    database = sqlite3.connect(local)
    database.row_factory = sqlite3.Row
    database.execute('PRAGMA journal_mode=OFF')
    database.execute('PRAGMA synchronous=OFF')
    schema = (ROOT / 'prototype/accession-range/migrations/0006_runtime_metadata.sql').read_text(encoding='utf-8')
    initial = schema + f"\nINSERT OR IGNORE INTO hf_runtime_release VALUES(1,'{revision}','loading',0,0,'pending');\n"
    database.executescript(initial)
    (output / '000-schema.sql').write_text(initial, encoding='utf-8')
    sql_files, statements, sql_bytes = [], [], 0

    def flush():
        nonlocal statements, sql_bytes
        if statements:
            name = f'{len(sql_files)+1:03d}-rows.sql'
            (output / name).write_text('\n'.join(statements) + '\n', encoding='utf-8')
            sql_files.append(name)
            statements, sql_bytes = [], 0

    def insert(table, values):
        nonlocal sql_bytes
        statement = f'INSERT OR IGNORE INTO {table} VALUES(' + ','.join('NULL' if value is None else "'" + str(value).replace("'", "''") + "'" for value in values) + ');'
        assert len(statement.encode()) < 100000
        database.execute(f'INSERT INTO {table} VALUES({",".join("?" for _ in values)})', values)
        statements.append(statement)
        sql_bytes += len(statement.encode())
        if sql_bytes >= 3*1024*1024:
            flush()

    identity = hashlib.sha256()
    file_count = excluded_history = genomes = 0
    for stored in origin.execute('SELECT * FROM hf_genome_metadata ORDER BY genome_id'):
        raw = stored['metadata_json'].encode()
        assert hashlib.sha256(raw).hexdigest() == stored['metadata_sha256']
        wrapper = json.loads(raw)
        metadata = wrapper.get('records', {}).get('batter')
        if metadata is None:
            assert stored['catalogue_row_json'] is None
            continue
        record = json.loads(stored['catalogue_row_json'])
        assert wrapper['genome_id'] == metadata['genome_id'] == record[0]
        assert metadata['batch'] == record[1] and metadata['otu_id'] == record[2]
        assert metadata['reference']['source_path'] == f"genomes/{metadata['otu_id']}.fna.gz"
        assert set(metadata) == {'genome_id','batch','batch_rank','otu_id','genome_type','source_collection','taxonomy','augmentation_status','annotation','feature_counts','reference','files','validation'}
        assert set(metadata['feature_counts']) == set(COUNTS)
        assert set(metadata['reference']) == {'bases','contigs','source','source_path','source_sha256'}
        assert set(metadata['annotation']) <= {'status', *ANNOTATION}
        assert set(metadata['files']) <= set(FILES)
        validation = metadata['validation']
        assert set(validation) <= {'augmentation','augmentation_features','prediction','prediction_features','prediction_end_correction_rule','prediction_end_corrections'}
        genomes += 1
        values = [genomes, record[0], metadata['batch'], metadata['batch_rank'], metadata['otu_id'], record[3], metadata['genome_type'], metadata['source_collection'], metadata['taxonomy'], metadata['augmentation_status'],
                  *(metadata['feature_counts'][key] for key in COUNTS), *(metadata['reference'][key] for key in ['bases','contigs','source','source_sha256']), metadata['annotation']['status'],
                  *(metadata['annotation'].get(key) for key in ANNOTATION), *(validation[key] for key in ['augmentation','augmentation_features','prediction','prediction_features']),
                  stored['metadata_sha256']]
        insert('hf_runtime_genomes', values)
        for file, entry in metadata['files'].items():
            assert set(entry) == {'bytes','sha256'}
            insert('hf_runtime_files', [genomes, FILES.index(file), entry['bytes'], entry['sha256']])
            file_count += 1
        for entry in validation.get('prediction_end_corrections', []):
            assert set(entry) == {'contig','feature_id','start','original_end','corrected_end'}
            assert entry['original_end'] == entry['corrected_end'] + 1
            excluded_history += 1
        # Released GFF3 already contains the corrected coordinates. These keys
        # describe past preprocessing and are not required to read current files.
        validation.pop('prediction_end_correction_rule', None)
        validation.pop('prediction_end_corrections', None)
        row = database.execute('SELECT * FROM hf_runtime_genomes WHERE id=?', (genomes,)).fetchone()
        file_rows = database.execute('SELECT * FROM hf_runtime_files WHERE genome_key=?', (genomes,)).fetchall()
        assert metadata_from_fields(row, file_rows) == metadata, record[0]
        assert record == [row['genome_id'],row['batch'],row['otu_id'],row['organism'],row['genome_type'],*(row[key] for key in COUNTS[:4]),row['annotation_status'],row['tes_prediction'],row['taxonomy'],row['source_collection']]
        identity.update(record[0].encode()+b'\0'+bytes.fromhex(stored['metadata_sha256']))
        if genomes % 10000 == 0:
            print('FIELD_ROUNDTRIP', genomes, '/ 42904', flush=True)
    flush()
    assert genomes == 42904 and excluded_history == 1019
    checksum = identity.hexdigest()
    finish = f"UPDATE hf_runtime_release SET genome_count={genomes},file_count={file_count},projection_sha256='{checksum}',status='ready' WHERE singleton=1 AND reference_revision='{revision}' AND (SELECT COUNT(*) FROM hf_runtime_genomes)={genomes} AND (SELECT COUNT(*) FROM hf_runtime_files)={file_count};\n"
    (output / '999-ready.sql').write_text(finish, encoding='utf-8')
    database.executescript(finish)
    database.commit()
    assert database.execute('SELECT status FROM hf_runtime_release').fetchone()[0] == 'ready'
    database.close()
    origin.close()
    report = dict(reference_revision=revision, genomes=genomes, files=file_count, excluded_historical_corrections=excluded_history, projection_sha256=checksum,
                  metadata_roundtrip='Every current scalar and file checksum equals the verified original metadata; historical correction keys omitted', sqlite_bytes=local.stat().st_size,
                  sql_files=['000-schema.sql',*sql_files,'999-ready.sql'])
    (output / 'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key!='sql_files'},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    build(args.source,args.output)
