"""Prepare guarded, reversible imports of reviewed display fields into D1.

The registry files are migration inputs only. Live pages never fall back to them.
"""
import argparse
import copy
import csv
import json
from pathlib import Path

from build_v0_4_site import SOURCE_PAGE_CAVEATS
from generate_bted_d1 import sql_value

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("sample_strain", "genotype", "conditions", "replicate_type", "replicate_label",
          "reused_data_with", "shared_raw_data_accessions")


def prepare(snapshot, output):
    data = copy.deepcopy(snapshot)
    context = {row['source_id']: row for row in csv.DictReader(
        (ROOT / 'data/registry/source_context.tsv').read_text(encoding='utf-8-sig').splitlines(), delimiter='\t')}
    references = {row['assembly']: row for row in csv.DictReader(
        (ROOT / 'data/registry/genome_taxonomy.tsv').read_text(encoding='utf-8-sig').splitlines(), delimiter='\t')}
    forward, rollback, changes = [], [], []
    for row in data['sources']:
        old = row['metadata_json']
        metadata = json.loads(old)
        imported = {key: value for key in FIELDS if (value := context.get(row['source_id'], {}).get(key)) and not metadata.get(key)}
        if note := SOURCE_PAGE_CAVEATS.get(row['source_id']):
            if not metadata.get('interpretation_note'):
                imported['interpretation_note'] = note
        if not imported:
            continue
        metadata.update(imported)
        new = json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))
        identity = f"source_pk={int(row['source_pk'])} AND release_version='v0.4.0'"
        forward.append(f"UPDATE sources SET metadata_json={sql_value(new)} WHERE {identity} AND metadata_json={sql_value(old)};")
        rollback.insert(0, f"UPDATE sources SET metadata_json={sql_value(old)} WHERE {identity} AND metadata_json={sql_value(new)};")
        changes.append({'source_id': row['source_id'], 'added_fields': imported})
        row['metadata_json'] = new
    for row in data['assemblies']:
        reference = references[row['accession']]
        new_strain = row['strain'] or reference['reference_strain'] or None
        new_taxon = row['taxon_id'] or reference['taxid'] or None
        if (new_strain, new_taxon) == (row['strain'], row['taxon_id']):
            continue
        identity = f"assembly_pk={int(row['assembly_pk'])} AND release_version='v0.4.0'"
        forward.append(f"UPDATE assemblies SET strain={sql_value(new_strain)},taxon_id={sql_value(new_taxon)} WHERE {identity} AND strain IS {sql_value(row['strain'])} AND taxon_id IS {sql_value(row['taxon_id'])};")
        rollback.insert(0, f"UPDATE assemblies SET strain={sql_value(row['strain'])},taxon_id={sql_value(row['taxon_id'])} WHERE {identity} AND strain IS {sql_value(new_strain)} AND taxon_id IS {sql_value(new_taxon)};")
        changes.append({'assembly': row['accession'], 'strain': new_strain, 'taxon_id': new_taxon})
        row.update(strain=new_strain, taxon_id=new_taxon)
    totals = {row['version']: {key: int(row[key]) for key in ('predictions', 'training')} for row in data['directory_totals']}
    for release in data['directory_releases']:
        old = release['summary_json']
        summary = json.loads(old)
        summary['feature_totals'] = totals[summary.get('storage_version', release['version'])]
        new = json.dumps(summary, ensure_ascii=False, separators=(',', ':'))
        identity = f"version={sql_value(release['version'])}"
        forward.append(f"UPDATE hf_directory_releases SET summary_json={sql_value(new)} WHERE {identity} AND summary_json={sql_value(old)};")
        rollback.insert(0, f"UPDATE hf_directory_releases SET summary_json={sql_value(old)} WHERE {identity} AND summary_json={sql_value(new)};")
        release['summary_json'] = new
    output.mkdir(parents=True, exist_ok=True)
    (output / 'update.sql').write_text('\n'.join(forward) + '\n', encoding='utf-8')
    (output / 'rollback.sql').write_text('\n'.join(rollback) + '\n', encoding='utf-8')
    (output / 'expected.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'changes.json').write_text(json.dumps({'changes': changes, 'statements': len(forward), 'evidence': [
        'data/registry/source_context.tsv', 'docs/GENOME_METADATA.md',
        'data/registry/genome_taxonomy.tsv', 'scripts/build_v0_4_site.py:SOURCE_PAGE_CAVEATS',
    ]}, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    prepare(json.loads(args.snapshot.read_text(encoding='utf-8')), args.output)
