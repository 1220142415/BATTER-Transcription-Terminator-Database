"""Package verified annotations in the existing genome directory layout."""
import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path

from audit_annotation_recovery import ROOT

PREFIX = 'v0.5.0/genomes'
MANIFEST_PATH = 'v0.5.0/catalogues/annotation-recovery.json'


def annotation_path(genome, batch):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', genome) or not re.fullmatch(r'\d{3}', batch):
        raise ValueError('invalid_genome_or_batch')
    return f'{PREFIX}/batter-{batch}/{genome}/annotations/recovered/genes.gff3'


def prepare(audit_root, output):
    reports = [json.loads((audit_root / name).read_text(encoding='utf-8'))
               for name in ['partial-verified-report.json', 'gem-verified-report.json', 'almeida-verified-report.json']
               if (audit_root / name).exists()]
    if not reports or len({report['reference_revision'] for report in reports}) != 1:
        raise ValueError('missing_or_mixed_reference_revisions')
    manifest = {'reference_revision': reports[0]['reference_revision'], 'path_prefix': PREFIX,
                'genomes': {}}
    for report in reports:
        if report['verified_sequences'] is not True:
            raise ValueError('unverified_report')
        for row in report['genomes']:
            if row['result'] not in {'verified_restorable', 'verified_partial'}:
                continue
            genome = row['genome_id']
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', genome):
                raise ValueError('invalid_genome_identifier')
            if genome in manifest['genomes']:
                raise ValueError('duplicate_genome')
            raw = (audit_root / 'restored-partial' / (genome + '.gff3.gz')).read_bytes()
            if len(raw) != row['output_bytes'] or hashlib.sha256(raw).hexdigest() != row['output_sha256']:
                raise ValueError('recovered_file_checksum_mismatch')
            path = annotation_path(genome, row['batch'])
            data = gzip.decompress(raw)
            target = output / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.with_name('provenance.json').write_text(json.dumps(row, indent=2) + '\n', encoding='utf-8')
            manifest['genomes'][genome] = {
                'reference_sha256': row['reference_sha256'],
                'coverage': 'partial' if row['result'] == 'verified_partial' else 'full',
                'matched_reference_contigs': row['matched_reference_contigs'],
                'total_reference_contigs': row['total_reference_contigs'],
                'features': row['features'], 'source_url': row['gff_url'],
                'source_annotation_type': row.get('source_annotation_type', 'published_NCBI_GFF3'),
                'file': {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()},
            }
    target = output / MANIFEST_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-root', type=Path, default=ROOT / 'dist/annotation-recovery-2026-10-14')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/annotation-recovery-2026-10-14/publish')
    args = parser.parse_args()
    manifest = prepare(args.audit_root, args.output)
    print(json.dumps({'genomes': len(manifest['genomes']),
                      'full': sum(row['coverage'] == 'full' for row in manifest['genomes'].values()),
                      'partial': sum(row['coverage'] == 'partial' for row in manifest['genomes'].values()),
                      'annotation_bytes': sum(row['file']['bytes'] for row in manifest['genomes'].values())}))
