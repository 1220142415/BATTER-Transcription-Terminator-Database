"""Align experimental taxonomy to exact assembly membership in the original GEM catalogue."""
import argparse
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RANKS = ('phylum', 'class', 'order', 'family', 'genus', 'species')
TAXONOMY_URL = 'https://portal.nersc.gov/GEM/otus/otu_taxonomy.tsv'
MEMBERSHIP_URL = 'https://portal.nersc.gov/GEM/otus/genome_to_otu.tsv'


def read_tsv(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle, delimiter='\t'))


def align(rows, members, taxonomy):
    members = {row['genome_id']: row['otu_id'] for row in members}
    taxonomy = {row['otu_id']: row for row in taxonomy}
    result = []
    for original in rows:
        row = original.copy()
        otu = members.get(row['assembly'], '')
        lineage = taxonomy[otu] if otu else {}
        row.update({rank: '' if lineage.get('t_' + rank, '') == 'NULL' else lineage.get('t_' + rank, '') for rank in RANKS})
        row.update(taxonomy_source='GEM / GTDB (original)', taxonomy_url=TAXONOMY_URL,
                   retrieved_on='2026-10-15', gem_otu_id=otu,
                   taxonomy_note='' if otu else 'No exact assembly match in the original GEM catalogue.',
                   taxonomy_status='exact_accession' if otu else 'not_in_gem')
        result.append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, default=ROOT / 'dist/metadata-audit-2026-10-05')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    registry = ROOT / 'data/registry/genome_taxonomy.tsv'
    backup = args.output / 'genome_taxonomy.before.tsv'
    if not backup.exists():
        backup.write_bytes(registry.read_bytes())
    before = read_tsv(backup)
    after = align(before, read_tsv(args.evidence / 'gem-genome-to-otu.tsv'),
                  read_tsv(args.evidence / 'gem-otu-taxonomy.tsv'))
    assert len(before) == len(after) == 21
    assert sum(row['taxonomy_status'] == 'exact_accession' for row in after) == 16
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=list(after[0]), delimiter='\t', lineterminator='\n')
    writer.writeheader()
    writer.writerows(after)
    registry.write_bytes(output.getvalue().encode('utf-8'))
    changes = [{'assembly': old['assembly'], 'before': old, 'after': new,
                'evidence': [MEMBERSHIP_URL, TAXONOMY_URL]}
               for old, new in zip(before, after, strict=True)]
    (args.output / 'taxonomy-changes.json').write_text(json.dumps(changes, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Original GEM taxonomy: 16 exact assembly matches; 5 unmatched references left unassigned.')


if __name__ == '__main__':
    main()
