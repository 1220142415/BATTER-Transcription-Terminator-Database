"""Verify exact experimental assemblies and prepare a versioned D1 taxonomy migration.

Fetch is an explicit preparation operation, never a website runtime fallback.
Raw official responses and their URLs are retained beside the migration.
"""
import argparse
import csv
import gzip
import json
import re
import shutil
import sqlite3
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from build_genome_directory import compact, normal
from prepare_collections_d1 import COLS, RANKS, insert, literal, taxonomy_fields

ROOT = Path(__file__).resolve().parents[1]
NCBI = 'https://api.ncbi.nlm.nih.gov/datasets/v2'
GTDB = 'https://data.gtdb.ecogenomic.org/releases/release207/207.0/bac120_taxonomy_r207.tsv.gz'
NEW_VERSION = '202610220000000000000004'


def retrieve(url, path, requests):
    if not path.exists():
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'BTED-taxonomy-curation/1.0'}), timeout=90) as r:
                    path.write_bytes(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code in (400, 404):
                    path.write_bytes(e.read())
                    break
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
            except (OSError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
    requests[path.name] = {'url': url, 'retrieved_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}
    return path.read_bytes()


def ncbi_record(accession, report, taxonomy, retrieved_at):
    """Never substitute a newer assembly or infer an unresolved assembly from its name."""
    matches = [r for r in report.get('reports', []) if r.get('accession') == accession]
    base = dict(version=NEW_VERSION, genome_id=accession, system='ncbi', taxonomy_version='', tax_id=None,
                scientific_name='', matched_accession='', domain='', **dict.fromkeys(RANKS, ''), retrieved_at=retrieved_at,
                source_url=f'https://www.ncbi.nlm.nih.gov/datasets/genome/{accession}/')
    if not matches:
        return dict(base, status='pending', match_method='assembly_not_resolved', evidence_json=compact({
            'assembly_report_url': f'{NCBI}/genome/accession/{accession}/dataset_report',
            'note': 'No exact assembly-version report returned. No lineage inferred from another assembly or organism name.'}))
    assert len(matches) == 1
    organism = matches[0]['organism']
    taxid = organism['tax_id']
    taxon = taxonomy['reports'][0]['taxonomy']
    assert taxon['tax_id'] == taxid
    classification = taxon['classification']
    base.update(tax_id=taxid, matched_accession=accession, scientific_name=taxon['current_scientific_name']['name'],
                source_url=f'https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id={taxid}')
    for rank in ['domain', *RANKS]:
        base[rank] = classification.get(rank, {}).get('name', '')
        # Taxonomy reports may omit their own rank from ancestor classification.
        if not base[rank] and taxon.get('rank', '').lower() == rank:
            base[rank] = taxon['current_scientific_name']['name']
    assert base['domain'] == 'Bacteria'
    return dict(base, status='verified', match_method='exact_assembly_taxid', evidence_json=compact({
        'assembly_report_url': f'{NCBI}/genome/accession/{accession}/dataset_report',
        'taxonomy_report_url': f'{NCBI}/taxonomy/taxon/{taxid}/dataset_report',
        'assembly_organism': organism['organism_name'], 'assembly_strain': organism.get('infraspecific_names', {}).get('strain', ''),
        'current_accession': matches[0].get('current_accession'),
        'note': 'NCBI Taxonomy retrieval date is not a taxonomy release or gene-annotation version.'}))


def collect(output):
    output.mkdir(parents=True, exist_ok=True)
    evidence = output / 'evidence'
    evidence.mkdir(exist_ok=True)
    ids = sorted(json.loads((ROOT / 'dist/worker-site/assets/genome-browsers.json').read_bytes())['experimental'])
    requests = {}
    records = []
    for accession in ids:
        assembly = json.loads(retrieve(f'{NCBI}/genome/accession/{accession}/dataset_report', evidence / f'{accession}.json', requests))
        exact = [r for r in assembly.get('reports', []) if r.get('accession') == accession]
        taxonomy = None
        if exact:
            taxid = exact[0]['organism']['tax_id']
            taxonomy = json.loads(retrieve(f'{NCBI}/taxonomy/taxon/{taxid}/dataset_report', evidence / f'taxid-{taxid}.json', requests))
        retrieved_at = requests[f'taxid-{taxid}.json']['retrieved_at'] if exact else requests[f'{accession}.json']['retrieved_at']
        record = ncbi_record(accession, assembly, taxonomy, retrieved_at)
        records.append(record)
        retrieve(f'https://bted.1052596411.workers.dev/api/assemblies/{accession}/page-metadata', evidence / f'page-{accession}.json', requests)
        print(accession, record['status'], record['species'], flush=True)
        time.sleep(.4)
    data = retrieve(GTDB, evidence / 'bac120_taxonomy_r207.tsv.gz', requests)
    matches = {}
    for line in gzip.decompress(data).decode().splitlines():
        accession, lineage = line.split('\t')
        accession = re.sub(r'^(RS_|GB_)', '', accession)
        if accession in ids:
            assert accession not in matches
            matches[accession] = lineage
    for accession in ids:
        lineage = matches.get(accession, '')
        records.append(dict(version=NEW_VERSION, genome_id=accession, system='gtdb', taxonomy_version='R207.0',
            status='verified' if lineage else 'unmatched', tax_id=None, scientific_name='', matched_accession=accession if lineage else '',
            match_method='exact_assembly' if lineage else 'no_exact_assembly_match', domain='Bacteria' if lineage else '',
            **taxonomy_fields(lineage), source_url=GTDB, retrieved_at=requests['bac120_taxonomy_r207.tsv.gz']['retrieved_at'],
            evidence_json=compact({'catalogue_accession': 'RS_' + accession if lineage else None, 'lineage': lineage,
                'note': 'Exact assembly accession including version only; no substitution of paired or newer assemblies.'})))
    (output / 'requests.json').write_text(json.dumps(requests, indent=2) + '\n', encoding='utf-8')
    (output / 'records.json').write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def prepare(source, output):
    records = json.loads((output / 'records.json').read_bytes())
    assert len(records) == 42
    dbpath = output / 'verified.sqlite'
    if dbpath.exists():
        raise ValueError('Use a fresh verification database')
    shutil.copyfile(source, dbpath)
    db = sqlite3.connect(dbpath)
    db.row_factory = sqlite3.Row
    previous = dict(db.execute("SELECT * FROM bted_collections WHERE collection='experimental'").fetchone())
    assert previous['version'] != NEW_VERSION
    old = [dict(r) for r in db.execute('SELECT * FROM hf_directory_genomes WHERE version=? ORDER BY genome_id', (previous['version'],))]
    assert len(old) == 21 and {r['genome_id'] for r in old} == {r['genome_id'] for r in records}
    ncbi = {r['genome_id']: r for r in records if r['system'] == 'ncbi'}
    for r in old:
        # Keep the complete old mapping independently of the new default classification.
        ranks = {k: r[k] for k in RANKS}
        records.append(dict(version=NEW_VERSION, genome_id=r['genome_id'], system='gem_original', taxonomy_version='',
            status='retained' if any(ranks.values()) else 'unmatched', tax_id=None, scientific_name='',
            matched_accession=r['genome_id'] if any(ranks.values()) else '', match_method='retained_exact_assembly_mapping' if any(ranks.values()) else 'no_exact_assembly_match',
            domain='Bacteria' if any(ranks.values()) else '', **ranks,
            source_url='https://portal.nersc.gov/GEM/otus/otu_taxonomy.tsv', retrieved_at='2026-10-15',
            evidence_json=compact({'directory_version': previous['version'], 'note': 'Retained original mapping; exact GTDB release not established.'})))
    rows = []
    for original in old:
        r = {k: original[k] for k in COLS}
        r.update(version=NEW_VERSION, **{k: ncbi[r['genome_id']][k] for k in RANKS})
        # Build search from live reviewed study descriptions, not old mixed-catalogue
        # tokens (which contain superseded assay labels and computational datasets).
        page = json.loads((output / 'evidence' / f"page-{r['genome_id']}.json").read_bytes())
        assert page['metadata_source'] == 'd1' and page['assembly']['accession'] == r['genome_id']
        assert page['record_count'] == r['endpoints']
        values = [r['genome_id'], r['organism'], r['source'], page['assembly'].get('strain', ''), *(r[k] for k in RANKS)]
        for source in page['sources']:
            values.extend(source.get(key, '') for key in ['source_id','species','assay_family','publication_pmid'])
            values.append((source.get('publication') or {}).get('paper_title', ''))
            values.extend((source.get('metadata') or {}).get(key, '') for key in ['sample_strain','sample_id','raw_data_accessions'])
        r['search_text'] = ' '.join(dict.fromkeys(re.split(r'[^\w.-]+', normal(' '.join(str(v or '') for v in values)))))
        rows.append(r)
    release = dict(db.execute('SELECT * FROM hf_directory_releases WHERE version=?', (previous['version'],)).fetchone())
    summary = json.loads(release['summary_json'])
    summary['counts']['phylum'] = dict(Counter(r['phylum'] for r in rows))
    summary['phyla'] = sorted(p for p in summary['counts']['phylum'] if p)
    summary['taxonomy_system'] = 'ncbi'
    summary['taxonomy_version'] = ''
    sql = [(ROOT / 'database/migrations/0010_taxonomy_records.sql').read_text(encoding='utf-8') + '\n']
    sql.append(insert('hf_directory_releases', ['version','reference_revision','annotation_revision','summary_json','status'],
        [NEW_VERSION, release['reference_revision'], release['annotation_revision'], compact(summary), 'loading']))
    sql.extend(insert('hf_directory_genomes', COLS, [r[k] for k in COLS]) for r in rows)
    columns = list(records[0])
    sql.extend(insert('bted_taxonomy_records', columns, [r[k] for k in columns]) for r in records)
    # The existing GTDB and Legacy projections already contain the authoritative retained lineages.
    for collection, system, taxversion, url in [('gtdb','gtdb','R207.0',GTDB), ('gem','gem_original','','https://portal.nersc.gov/GEM/otus/otu_taxonomy.tsv')]:
        version = db.execute('SELECT version FROM bted_collections WHERE collection=?', (collection,)).fetchone()[0]
        sql.append(f'''INSERT INTO bted_taxonomy_records (version,genome_id,system,taxonomy_version,status,matched_accession,match_method,domain,phylum,class,"order",family,genus,species,source_url,retrieved_at,evidence_json)
SELECT version,genome_id,{literal(system)},{literal(taxversion)},'retained',genome_id,'retained_catalogue','Bacteria',phylum,class,"order",family,genus,species,{literal(url)},'',{literal(compact({'directory_version': version, 'note': 'Retained published catalogue classification; no new sequence classification performed.'}))}
FROM hf_directory_genomes WHERE version={literal(version)};\n''')
        sql.append(f"UPDATE bted_collections SET taxonomy_system={literal(system)},taxonomy_version={literal(taxversion)} WHERE collection={literal(collection)};\n")
    sql.append("INSERT INTO hf_directory_search(hf_directory_search) VALUES('rebuild');\n")
    sql.append(f"UPDATE hf_directory_releases SET status='ready' WHERE version='{NEW_VERSION}';\n")
    sql.append(f"UPDATE bted_collections SET version='{NEW_VERSION}',taxonomy_system='ncbi',taxonomy_version='',taxonomy_label='NCBI Taxonomy' WHERE collection='experimental' AND version={literal(previous['version'])};\n")
    statement = ''.join(sql)
    db.executescript('PRAGMA foreign_keys=ON; BEGIN;\n' + statement + '\nCOMMIT;')
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert db.execute('SELECT COUNT(*) FROM bted_taxonomy_records').fetchone()[0] == 27275 + 42904 + 63
    assert [dict(r) for r in db.execute('SELECT * FROM hf_directory_genomes WHERE version=? ORDER BY genome_id', (previous['version'],))] == old
    assert db.execute("SELECT COUNT(*) FROM hf_directory_search WHERE hf_directory_search MATCH '\"kit\"'").fetchone()[0] > 0
    for row in rows:
        for rank in RANKS:
            assert row[rank] == ncbi[row['genome_id']][rank]
    registry = json.loads((ROOT / 'data/registry/collections.json').read_bytes())
    registry['experimental'].update(version=NEW_VERSION, taxonomy_label='NCBI Taxonomy')
    (output / 'collections.json').write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'import.sql').write_text(statement, encoding='utf-8')
    (output / 'rollback.sql').write_text(f"UPDATE bted_collections SET version={literal(previous['version'])},taxonomy_system='',taxonomy_version='',taxonomy_label={literal(previous['taxonomy_label'])} WHERE collection='experimental';\n", encoding='utf-8')
    report = dict(version=NEW_VERSION, previous_version=previous['version'], references=len(rows),
        ncbi=dict(Counter(r['status'] for r in records if r['system']=='ncbi')),
        gtdb_r207=dict(Counter(r['status'] for r in records if r['system']=='gtdb')),
        original_gem=dict(Counter(r['status'] for r in records if r['system']=='gem_original')))
    (output / 'verified.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    # Human-readable evidence records; CSV permits direct inspection without a custom viewer.
    with (output / 'experimental-taxonomy-review.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader(); writer.writerows(records)
    db.close()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['collect','prepare'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--database', type=Path)
    args = parser.parse_args()
    if args.action == 'collect':
        collect(args.output)
    else:
        prepare(args.database, args.output)
