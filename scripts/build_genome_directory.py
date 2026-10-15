"""Prepare an indexed D1 directory from the verified, pinned website inputs."""
import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from html.parser import HTMLParser
from html import escape
from pathlib import Path

from build_v0_4_site import TAXONOMY_RANKS, load_reference_sizes

ROOT = Path(__file__).resolve().parents[1]


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def normal(value):
    return unicodedata.normalize('NFKC', value).lower()


def sort_key(value):
    value = ''.join(c for c in unicodedata.normalize('NFD', normal(value)) if unicodedata.category(c) != 'Mn')
    def number(match):
        digits = match[0].lstrip('0') or '0'
        return f'{len(digits):02d}{digits}'
    return re.sub(r'\d+', number, value)


class ExperimentalRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = {}
        self.current = None
        self.organism = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'tr' and 'data-genome-row' in attrs:
            self.current = {'dataset': {re.sub(r'-([a-z])', lambda m: m[1].upper(), k[5:]): v for k, v in attrs.items() if k.startswith('data-')}, 'study_search': []}
            self.rows[attrs['data-sort-accession'].upper()] = self.current
        if self.current:
            if 'data-source-filter' in attrs:
                self.current['study_search'].append(attrs.get('data-search', ''))
            if tag == 'span' and attrs.get('class') == 'genome-organism':
                self.organism = True

    def handle_data(self, text):
        if self.current and self.organism:
            self.current['organism'] = text

    def handle_endtag(self, tag):
        if tag == 'span':
            self.organism = False
        if tag == 'tr':
            self.current = None


def directory_rows(site):
    catalogue = json.loads((site / 'assets/batter-browser.json').read_bytes())
    registry = json.loads((site / 'assets/genome-browsers.json').read_bytes())
    recovery = registry.get('annotation_recovery', {})
    if recovery and recovery['reference_revision'] != catalogue['revision']:
        raise ValueError('Annotation reference mismatch')
    parser = ExperimentalRows()
    parser.feed((site / 'genomes.html').read_text(encoding='utf-8'))
    from experimental_predictions import load_predictions
    predictions = load_predictions()['genomes']
    original_sizes = load_reference_sizes()
    rows = {}
    for record in catalogue['genomes']:
        taxonomy = {taxon[0]: taxon[3:] for taxon in record[11].split(';') if len(taxon) > 3}
        dataset = {f'taxonomy{rank.capitalize()}': taxonomy.get(rank[0], '') for rank in TAXONOMY_RANKS}
        rows[record[0].upper()] = {'batter': record.copy(), 'dataset': dataset}
    for accession, item in parser.rows.items():
        row = rows.setdefault(accession, {'batter': [accession, '', '', item.get('organism', ''), '', 0, 0, 0, 0, 'unavailable', 0, '', 'NCBI-RefSeq']})
        row['dataset'] = item['dataset'].copy()
        row['batter'][3] = item.get('organism') or row['batter'][3]
        if int(item['dataset'].get('sortSize') or 0):
            row['referenceSize'] = original_sizes.get(row['batter'][0])
        row['studySearch'] = ' '.join(item['study_search'])
    for row in rows.values():
        record, dataset = row['batter'], row['dataset']
        prediction = predictions.get(record[0])
        if prediction:
            record[10] = prediction['prediction_count']
            row['referenceSize'] = [prediction['reference']['genome_length'], len(prediction['reference']['contigs'])]
        recovered = recovery.get('genomes', {}).get(record[0])
        if recovered:
            row['recoveredAnnotation'] = {k: recovered[k] for k in ('coverage', 'matched_reference_contigs', 'total_reference_contigs')}
        if record[0] in catalogue.get('reference_sizes', {}):
            row['referenceSize'] = catalogue['reference_sizes'][record[0]]
        source = {'NCBI-RefSeq': 'NCBI RefSeq', 'NCBI-MAG': 'NCBI GenBank', 'NCBI-SAG': 'NCBI GenBank'}.get(record[12], record[12] or 'Not cataloged')
        annotation = 'Available' if record[9] == 'matched' or recovered else dataset.get('genomeAnnotation', 'Missing')
        # Experimental-only annotation availability is taken from the verified public asset list.
        if record[0].upper() in parser.rows and not record[1]:
            record[9] = 'matched' if annotation == 'Available' else 'unavailable'
        dataset.update(genomeSource=source, genomeType=record[4] or 'unknown', genomeAnnotation=annotation,
                       sortAccession=record[0].lower(), sortOrganism=record[3].lower(),
                       sortEndpoints=dataset.get('sortEndpoints', '0'), sortPredictions=str(record[10]),
                       sortTraining=str(record[5] + record[7]), sortSize=str(row.get('referenceSize', [0])[0] or ''))
        search = ' '.join((dataset.get('genomeSearch', ''), record[0], record[2], record[3], record[11], source, row.pop('studySearch', ''),
                           'batter predictions 42402588' if record[10] else '', 'batter augmentation training 42402588' if record[5] + record[7] else ''))
        row['searchText'] = ' '.join(dict.fromkeys(re.split(r'[^\w.-]+', normal(search))))
        dataset.pop('genomeSearch', None)
        dataset.pop('genomeRow', None)
    return catalogue['revision'], recovery.get('annotation_revision', 'original'), list(rows.values())


def build(site, output):
    revision, annotation, rows = directory_rows(site)
    content = compact(rows)
    version = hashlib.sha256(('directory-v4:' + revision + annotation + content).encode()).hexdigest()[:24]
    summary = {'total': len(rows), 'sources': sorted({r['dataset']['genomeSource'] for r in rows}),
               'phyla': sorted({r['dataset'].get('taxonomyPhylum') for r in rows if r['dataset'].get('taxonomyPhylum')}),
               'available': sum(r['dataset']['genomeAnnotation'] == 'Available' for r in rows)}
    summary['counts'] = {field: dict(Counter(r['dataset'].get(key, '') for r in rows)) for field, key in
                         [('source', 'genomeSource'), ('genome_type', 'genomeType'), ('annotation', 'genomeAnnotation'), ('phylum', 'taxonomyPhylum')]}
    from experimental_predictions import load_predictions
    summary['experimental_predictions'] = {g: r['prediction_count'] for g, r in load_predictions()['genomes'].items()}
    summary['counts']['dataset'] = {field: sum(int(r['dataset'][key]) > 0 for r in rows) for field, key in
                                   [('experimental', 'sortEndpoints'), ('prediction', 'sortPredictions'), ('augmentation', 'sortTraining')]}
    output.mkdir(parents=True, exist_ok=True)
    schema = (ROOT / 'prototype/accession-range/migrations/0005_genome_directory.sql').read_text(encoding='utf-8')
    sql_value = lambda value: 'NULL' if value is None else "'" + str(value).replace("'", "''") + "'"
    initial = schema + '\nINSERT OR IGNORE INTO hf_directory_releases VALUES (' + ','.join(map(sql_value, [version, revision, annotation, compact(summary), 'loading'])) + ');\n'
    (output / '000-schema.sql').write_text(initial, encoding='utf-8')
    chunks, statements, size = [], [], 0
    local_path = output / 'directory.sqlite'
    if local_path.exists():
        raise ValueError('Use a fresh output directory for local verification')
    database = sqlite3.connect(local_path)
    database.executescript(initial)
    for row in rows:
        ds, record = row['dataset'], row['batter']
        recovered = row.get('recoveredAnnotation', {})
        values = [version, record[0], sort_key(record[0]), sort_key(record[3]), record[3], ds['genomeSource'], ds['genomeType'], ds['genomeAnnotation'],
                  int(ds['sortEndpoints']), int(ds['sortPredictions']), int(ds['sortTraining']), int(ds['sortSize']) if ds['sortSize'] else None,
                  row.get('referenceSize', [0, None])[1], *(ds.get(f'taxonomy{rank.capitalize()}', '') for rank in TAXONOMY_RANKS), row['searchText'],
                  recovered.get('matched_reference_contigs'), recovered.get('total_reference_contigs'), recovered.get('coverage')]
        statement = 'INSERT OR IGNORE INTO hf_directory_genomes (' + ','.join(['version', 'genome_id', 'accession_key', 'organism_key', 'organism', 'source', 'genome_type', 'annotation', 'endpoints', 'predictions', 'training', 'size', 'contigs', 'phylum', 'class', '"order"', 'family', 'genus', 'species', 'search_text', 'recovered_matched', 'recovered_total', 'recovered_coverage']) + ') VALUES (' + ','.join(map(sql_value, values)) + ');'
        database.execute(statement)
        statements.append(statement)
        size += len(statement.encode())
        if size >= 3 * 1024 * 1024:
            path = output / f'{len(chunks)+1:03d}-rows.sql'
            path.write_text('\n'.join(statements) + '\n', encoding='utf-8')
            chunks.append(path.name)
            statements, size = [], 0
    if statements:
        path = output / f'{len(chunks)+1:03d}-rows.sql'
        path.write_text('\n'.join(statements) + '\n', encoding='utf-8')
        chunks.append(path.name)
    finish = "INSERT INTO hf_directory_search(hf_directory_search) VALUES('rebuild');\n"
    # One indexed aggregate checks the imported snapshot before activation.
    finish += f"UPDATE hf_directory_releases SET status='ready' WHERE version='{version}' AND (SELECT COUNT(*) FROM hf_directory_genomes WHERE version='{version}')={len(rows)};\n"
    (output / '999-ready.sql').write_text(finish, encoding='utf-8')
    database.executescript(finish)
    database.commit()
    assert database.execute('SELECT COUNT(*) FROM hf_directory_genomes').fetchone()[0] == summary['total']
    assert database.execute("SELECT COUNT(*) FROM hf_directory_genomes WHERE annotation='Available'").fetchone()[0] == summary['available']
    assert database.execute("SELECT COUNT(*) FROM hf_directory_search WHERE hf_directory_search MATCH '\"765\"'").fetchone()[0] >= 1
    plan = [r[3] for r in database.execute('EXPLAIN QUERY PLAN SELECT genome_id FROM hf_directory_genomes WHERE version=? ORDER BY endpoints DESC, accession_key LIMIT 25', (version,))]
    assert any('directory_endpoints' in value for value in plan), plan
    database.close()
    result = dict(version=version, reference_revision=revision, annotation_revision=annotation, summary=summary,
                  sqlite_bytes=local_path.stat().st_size, first_page_plan=plan, files=['000-schema.sql', *chunks, '999-ready.sql'])
    (output / 'manifest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    apply_binding(site, result)
    print(json.dumps({k: result[k] for k in ('version', 'sqlite_bytes', 'first_page_plan')}, indent=2))
    return result


def apply_binding(site, result):
    revision, annotation, rows = directory_rows(site)
    version = hashlib.sha256(('directory-v4:' + revision + annotation + compact(rows)).encode()).hexdigest()[:24]
    if version != result['version']:
        raise ValueError('Directory inputs changed: rebuild and verify the D1 projection before publishing')
    summary = result['summary']
    (site / 'assets/genome-directory.json').write_text(compact({k: result[k] for k in ('version', 'reference_revision', 'annotation_revision')}), encoding='utf-8')
    path = site / 'genomes.html'
    html = path.read_text(encoding='utf-8')
    html = re.sub(r' data-genome-catalogue="[^"]*"', '', html)
    html = re.sub(r' data-genome-pages="[^"]*"', '', html)
    html = html.replace('data-genome-search-form inert>', f'data-genome-search-form data-genome-pages="api/genome-directory?v={version}" inert>')
    for selector, values, label in [('data-genome-source-filter', summary['sources'], 'All sources'), ('data-taxonomy-rank="phylum"', summary['phyla'], 'All')]:
        html = re.sub(r'(<select ' + re.escape(selector) + r'>).*?(</select>)', lambda match: match[1] + f'<option value="">{label}</option>' + ''.join(f'<option value="{escape(value, quote=True)}">{escape(value)}</option>' for value in values) + match[2], html, count=1, flags=re.S)
    path.write_text(html, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, default=ROOT / 'dist/worker-site')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.site, args.output)
